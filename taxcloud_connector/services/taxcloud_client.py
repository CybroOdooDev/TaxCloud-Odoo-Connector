# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
"""HTTP client for the TaxCloud API v3.

This module has no ORM dependency on purpose: it only speaks HTTP and JSON so it
can be unit tested with a fake session and reused outside of Odoo models.

Reference: https://docs.taxcloud.com (API v3 pages only).
"""
import email.utils
import logging
import time
from datetime import UTC, datetime
from urllib.parse import quote

import requests

_logger = logging.getLogger(__name__)

BASE_URL = 'https://api.v3.taxcloud.com'
USER_AGENT = 'Odoo-TaxCloud-Connector/20.0'

# 429 and 5xx are transient; 400 (malformed) and 422 (invalid content) are not.
RETRYABLE_STATUS_CODES = frozenset({429})


class TaxCloudError(Exception):
    """Raised for any failed TaxCloud call.

    :param message: human readable message (RFC 7807 ``detail`` or ``title``).
    :param status_code: HTTP status, or None for transport errors (timeout, DNS, ...).
    :param errors: list of ``{location, message, value}`` dicts from the RFC 7807 body.
    """

    def __init__(self, message, status_code=None, errors=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors or []

    @property
    def is_retryable(self):
        if self.status_code is None:
            return True
        return self.status_code in RETRYABLE_STATUS_CODES or self.status_code >= 500

    def __str__(self):
        details = '; '.join(
            ': '.join(str(part) for part in (error.get('location'), error.get('message')) if part)
            for error in self.errors
            if isinstance(error, dict)
        )
        prefix = f"[{self.status_code}] " if self.status_code else ''
        return f"{prefix}{self.message}" + (f" ({details})" if details else '')


class TaxCloudClient:
    """Thin wrapper around the TaxCloud API v3.

    :param api_key: sent in the ``X-API-KEY`` header; never logged.
    :param connection_id: TaxCloud connection ID (test and production have different IDs).
    :param log_hook: optional callable receiving one dict per HTTP attempt with keys
        ``method, url, endpoint, request_body, status_code, response_body, duration_ms,
        attempt, error``. It never receives headers.
    """

    def __init__(self, api_key, connection_id, *, base_url=BASE_URL, timeout=20,
                 max_retries=2, backoff_factor=0.5, max_backoff=30,
                 session=None, log_hook=None, sleep=time.sleep):
        if not api_key or not connection_id:
            raise ValueError("TaxCloud API key and connection ID are required.")
        self.connection_id = connection_id
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        self.log_hook = log_hook
        self._sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update({
            'X-API-KEY': api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
        })

    # Endpoints
    # =========
    def ping(self):
        """``GET /tax/connections/{connectionId}/ping``"""
        return self._request('GET', self._connection_path('ping'))

    def verify_address(self, address):
        """``POST /tax/verify-address`` (not connection scoped).

        :param address: ``{line1, line2?, city, state, zip, countryCode?}``
        """
        return self._request('POST', '/tax/verify-address', json=address)

    def create_carts(self, carts, transaction_date=None):
        """``POST /tax/connections/{connectionId}/carts`` (upsert by ``cartId``).

        :param carts: list of Cart dicts.
        :param transaction_date: RFC 3339 string, defaults to now on TaxCloud's side.
        """
        body = {'items': carts}
        if transaction_date:
            body['transactionDate'] = transaction_date
        return self._request('POST', self._connection_path('carts'), json=body)

    def convert_cart_to_order(self, cart_id, order_id, completed=True, completed_date=None):
        """``POST /tax/connections/{connectionId}/carts/orders``"""
        body = {'cartId': cart_id, 'orderId': order_id, 'completed': completed}
        if completed_date:
            body['completedDate'] = completed_date
        return self._request('POST', self._connection_path('carts', 'orders'), json=body)

    def create_order(self, order):
        """``POST /tax/connections/{connectionId}/orders`` (e.g. ``kind: "credit"``)."""
        return self._request('POST', self._connection_path('orders'), json=order)

    def get_order(self, order_id, expand_refunds=False):
        """``GET /tax/connections/{connectionId}/orders/{orderId}``"""
        params = {'expand': 'refunds'} if expand_refunds else None
        return self._request('GET', self._connection_path('orders', order_id), params=params)

    def update_order(self, order_id, completed_date):
        """``PATCH /tax/connections/{connectionId}/orders/{orderId}``"""
        return self._request('PATCH', self._connection_path('orders', order_id), json={'completedDate': completed_date})

    def void_order(self, order_id):
        """``DELETE /tax/connections/{connectionId}/orders/{orderId}`` (204, no body)."""
        return self._request('DELETE', self._connection_path('orders', order_id))

    def refund_order(self, order_id, items=None, returned_date=None, idempotency_key=None):
        """``POST /tax/connections/{connectionId}/orders/refunds/{orderId}``

        :param items: None for a full refund, else ``[{itemId, quantity, cartItemIndex?}]``.
        """
        body = {}
        if items:
            body['items'] = items
        if returned_date:
            body['returnedDate'] = returned_date
        if idempotency_key:
            body['idempotencyKey'] = idempotency_key
        return self._request('POST', self._connection_path('orders', 'refunds', order_id), json=body)

    # Internals
    # =========
    def _connection_path(self, *segments):
        return '/' + '/'.join(
            quote(str(segment), safe='')
            for segment in ('tax', 'connections', self.connection_id, *segments)
        )

    def _request(self, method, endpoint, json=None, params=None):
        url = self.base_url + endpoint
        attempt = 0
        while True:
            attempt += 1
            start = time.monotonic()
            response = None
            try:
                response = self.session.request(method, url, json=json, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                error = TaxCloudError(f"Could not reach TaxCloud: {e.__class__.__name__}: {e}")
            else:
                error = None if response.ok else self._parse_error(response)
            duration_ms = int((time.monotonic() - start) * 1000)

            self._call_log_hook({
                'method': method,
                'url': url,
                'endpoint': endpoint,
                'request_body': json,
                'status_code': response.status_code if response is not None else None,
                'response_body': response.text if response is not None else None,
                'duration_ms': duration_ms,
                'attempt': attempt,
                'error': str(error) if error else None,
            })

            if not error:
                return self._parse_success(response)
            if not error.is_retryable or attempt > self.max_retries:
                raise error
            delay = self._retry_delay(attempt, response)
            _logger.info("TaxCloud %s %s failed (%s), retry %s/%s in %.1fs",
                         method, endpoint, error.status_code, attempt, self.max_retries, delay)
            self._sleep(delay)

    def _call_log_hook(self, entry):
        if not self.log_hook:
            return
        try:
            self.log_hook(entry)
        except Exception:  # noqa: BLE001 - logging must never break a tax call
            _logger.exception("TaxCloud log hook failed")

    def _retry_delay(self, attempt, response):
        retry_after = response.headers.get('Retry-After') if response is not None else None
        delay = self._parse_retry_after(retry_after)
        if delay is None:
            delay = self.backoff_factor * (2 ** (attempt - 1))
        return max(0.0, min(delay, self.max_backoff))

    @staticmethod
    def _parse_retry_after(value):
        """Retry-After is either a number of seconds or an HTTP date."""
        if not value:
            return None
        value = value.strip()
        if value.isdigit():
            return float(value)
        try:
            date = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        return (date - datetime.now(UTC)).total_seconds()

    @staticmethod
    def _parse_success(response):
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise TaxCloudError("TaxCloud returned an invalid JSON response.", response.status_code)

    @staticmethod
    def _parse_error(response):
        """Parse an RFC 7807 problem body: ``{title, detail, errors: [{location, message, value}]}``."""
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            text = (response.text or '').strip()[:500]
            return TaxCloudError(text or response.reason or f"HTTP {response.status_code}", response.status_code)
        errors = body.get('errors')
        message = body.get('detail') or body.get('title') or response.reason or f"HTTP {response.status_code}"
        return TaxCloudError(message, response.status_code, errors if isinstance(errors, list) else [])
