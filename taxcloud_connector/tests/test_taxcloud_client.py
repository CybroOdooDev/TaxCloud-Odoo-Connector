# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from email.utils import format_datetime
from datetime import UTC, datetime, timedelta

import requests

from odoo.tests import BaseCase, tagged

from odoo.addons.taxcloud_connector.services.taxcloud_client import BASE_URL, TaxCloudClient, TaxCloudError
from .common import FAKE_API_KEY, FakeResponse, FakeSession

PROBLEM_422 = {
    'type': 'about:blank',
    'title': 'Unprocessable Entity',
    'status': 422,
    'detail': 'validation failed',
    'errors': [{'location': 'body.items[0].destination.zip', 'message': 'invalid zip', 'value': '1'}],
}


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudClient(BaseCase):

    def _client(self, *responses, connection_id='conn-1', **kwargs):
        self.session = FakeSession(*responses)
        self.sleeps = []
        self.logged = []
        return TaxCloudClient(
            FAKE_API_KEY, connection_id, session=self.session, sleep=self.sleeps.append,
            log_hook=self.logged.append, **kwargs,
        )

    def test_headers_and_ping(self):
        client = self._client(FakeResponse(200, {'message': 'Success'}))
        self.assertEqual(client.ping(), {'message': 'Success'})
        self.assertEqual(self.session.headers['X-API-KEY'], FAKE_API_KEY)
        call = self.session.calls[0]
        self.assertEqual((call['method'], call['url']), ('GET', f'{BASE_URL}/tax/connections/conn-1/ping'))
        self.assertTrue(call['timeout'])

    def test_requires_credentials(self):
        with self.assertRaises(ValueError):
            TaxCloudClient('', 'conn-1', session=FakeSession())
        with self.assertRaises(ValueError):
            TaxCloudClient('key', '', session=FakeSession())

    def test_url_encoding(self):
        client = self._client(FakeResponse(200, {}), FakeResponse(200, {}), FakeResponse(201, []),
                              connection_id='conn/1 ?')
        client.get_order('INV/2026/0001', expand_refunds=True)
        client.void_order('a#b')
        client.refund_order('INV/1')
        urls = [call['url'] for call in self.session.calls]
        self.assertEqual(urls, [
            f'{BASE_URL}/tax/connections/conn%2F1%20%3F/orders/INV%2F2026%2F0001',
            f'{BASE_URL}/tax/connections/conn%2F1%20%3F/orders/a%23b',
            f'{BASE_URL}/tax/connections/conn%2F1%20%3F/orders/refunds/INV%2F1',
        ])
        self.assertEqual(self.session.calls[0]['params'], {'expand': 'refunds'})

    def test_payloads(self):
        client = self._client(*[FakeResponse(200, {}) for _i in range(6)])
        client.verify_address({'line1': '1 Main St', 'city': 'Seattle', 'state': 'WA', 'zip': '98104'})
        client.create_carts([{'cartId': 'c1'}], transaction_date='2026-10-08T00:00:00Z')
        client.convert_cart_to_order('c1', 'INV-1', completed=True)
        client.refund_order('INV-1', items=[{'itemId': 'line-1', 'quantity': 2}],
                            returned_date='2026-10-09T00:00:00Z', idempotency_key='k1')
        client.refund_order('INV-1')
        client.update_order('INV-1', '2026-10-10T00:00:00Z')
        calls = self.session.calls
        self.assertEqual(calls[0]['url'], f'{BASE_URL}/tax/verify-address')
        self.assertEqual(calls[1]['json'], {'items': [{'cartId': 'c1'}], 'transactionDate': '2026-10-08T00:00:00Z'})
        self.assertEqual(calls[2]['url'], f'{BASE_URL}/tax/connections/conn-1/carts/orders')
        self.assertEqual(calls[2]['json'], {'cartId': 'c1', 'orderId': 'INV-1', 'completed': True})
        self.assertEqual(calls[3]['json'], {
            'items': [{'itemId': 'line-1', 'quantity': 2}],
            'returnedDate': '2026-10-09T00:00:00Z',
            'idempotencyKey': 'k1',
        })
        self.assertEqual(calls[4]['json'], {}, "Empty body means full refund")
        self.assertEqual((calls[5]['method'], calls[5]['json']), ('PATCH', {'completedDate': '2026-10-10T00:00:00Z'}))

    def test_void_returns_empty_dict_on_204(self):
        client = self._client(FakeResponse(204))
        self.assertEqual(client.void_order('INV-1'), {})
        self.assertEqual(self.session.calls[0]['method'], 'DELETE')

    def test_retry_5xx_with_exponential_backoff(self):
        client = self._client(FakeResponse(503), FakeResponse(500), FakeResponse(200, {'ok': 1}), backoff_factor=0.5)
        self.assertEqual(client.ping(), {'ok': 1})
        self.assertEqual(self.sleeps, [0.5, 1.0])
        self.assertEqual(len(self.session.calls), 3)

    def test_retry_after_seconds_and_http_date(self):
        future = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
        client = self._client(
            FakeResponse(429, headers={'Retry-After': '7'}),
            FakeResponse(429, headers={'Retry-After': future}),
            FakeResponse(200, {}),
        )
        client.ping()
        self.assertEqual(self.sleeps[0], 7.0)
        self.assertTrue(5 < self.sleeps[1] <= 10)

    def test_retry_after_is_capped(self):
        client = self._client(FakeResponse(429, headers={'Retry-After': '3600'}), FakeResponse(200, {}), max_backoff=30)
        client.ping()
        self.assertEqual(self.sleeps, [30])

    def test_retries_exhausted(self):
        client = self._client(*[FakeResponse(429) for _i in range(3)], max_retries=2)
        with self.assertRaises(TaxCloudError) as cm:
            client.ping()
        self.assertEqual(cm.exception.status_code, 429)
        self.assertTrue(cm.exception.is_retryable)
        self.assertEqual(len(self.session.calls), 3)

    def test_transport_error_retried(self):
        client = self._client(requests.ConnectionError('boom'), requests.Timeout('slow'), max_retries=1)
        with self.assertRaises(TaxCloudError) as cm:
            client.ping()
        self.assertIsNone(cm.exception.status_code)
        self.assertTrue(cm.exception.is_retryable)
        self.assertIn('Timeout', str(cm.exception))
        self.assertEqual(len(self.session.calls), 2)

    def test_non_retryable_errors_parse_rfc7807(self):
        for status in (400, 401, 404, 422):
            body = dict(PROBLEM_422, status=status)
            client = self._client(FakeResponse(status, body))
            with self.assertRaises(TaxCloudError) as cm:
                client.create_carts([])
            error = cm.exception
            self.assertEqual(error.status_code, status)
            self.assertFalse(error.is_retryable)
            self.assertEqual(error.message, 'validation failed')
            self.assertEqual(error.errors, PROBLEM_422['errors'])
            self.assertIn('body.items[0].destination.zip: invalid zip', str(error))
            self.assertEqual(len(self.session.calls), 1, "4xx must not be retried")
            self.assertFalse(self.sleeps)

    def test_error_without_json_body(self):
        client = self._client(FakeResponse(400, text='<html>Bad gateway</html>'))
        with self.assertRaises(TaxCloudError) as cm:
            client.ping()
        self.assertEqual(cm.exception.message, '<html>Bad gateway</html>')

    def test_error_title_fallback(self):
        client = self._client(FakeResponse(400, {'title': 'Bad Request'}))
        with self.assertRaises(TaxCloudError) as cm:
            client.ping()
        self.assertEqual(cm.exception.message, 'Bad Request')

    def test_invalid_json_success(self):
        client = self._client(FakeResponse(200, text='not json'))
        with self.assertRaises(TaxCloudError):
            client.ping()

    def test_log_hook_per_attempt_without_api_key(self):
        client = self._client(FakeResponse(503, {'title': 'down'}), FakeResponse(200, {'message': 'Success'}))
        client.ping()
        self.assertEqual([entry['attempt'] for entry in self.logged], [1, 2])
        self.assertTrue(self.logged[0]['error'])
        self.assertIsNone(self.logged[1]['error'])
        self.assertEqual(self.logged[1]['status_code'], 200)
        self.assertNotIn(FAKE_API_KEY, repr(self.logged))

    def test_log_hook_failure_does_not_break_call(self):
        def broken_hook(entry):
            raise RuntimeError('log failure')
        client = TaxCloudClient(FAKE_API_KEY, 'conn-1', session=FakeSession(FakeResponse(200, {'ok': 1})),
                                log_hook=broken_hook)
        with self.assertLogs('odoo.addons.taxcloud_connector.services.taxcloud_client', 'ERROR'):
            self.assertEqual(client.ping(), {'ok': 1})
