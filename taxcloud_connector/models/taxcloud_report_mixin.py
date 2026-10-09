# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
import logging
import re

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.modules import module

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudError

_logger = logging.getLogger(__name__)

MAX_REPORT_ATTEMPTS = 5


class TaxCloudReportMixin(models.AbstractModel):
    """ Reporting of completed documents (invoices, POS orders) to TaxCloud: a queue processed by a
    cron, with retries for transient errors. Inherit it next to `taxcloud.tax.mixin` and
    implement the hooks below; the inheriting model also defines the computed fields
    ``taxcloud_report_kind`` ('order', 'refund', 'credit' or False) and ``taxcloud_waiting_for_origin``. """
    _name = 'taxcloud.report.mixin'
    _description = "TaxCloud Reporting"

    taxcloud_sync_state = fields.Selection(
        selection=[
            ('to_sync', "To Report"),
            ('synced', "Reported"),
            ('error', "Error"),
        ],
        string="TaxCloud Status",
        copy=False,
        readonly=True,
        index=True,
    )
    taxcloud_order_id = fields.Char(string="TaxCloud Order ID", copy=False, readonly=True)
    taxcloud_sync_attempts = fields.Integer(string="TaxCloud Report Attempts", copy=False, readonly=True)
    taxcloud_sync_error = fields.Text(string="TaxCloud Report Error", copy=False, readonly=True)
    taxcloud_synced_date = fields.Datetime(string="Reported to TaxCloud On", copy=False, readonly=True)

    # Hooks
    # =====
    def _taxcloud_get_report_cron(self):
        """ The cron processing the queue of this model. """
        raise NotImplementedError()

    def _taxcloud_get_report_reference(self):
        """ Document number used as TaxCloud order ID (made URL-safe). """
        return self.name

    def _taxcloud_get_report_date(self):
        """ Date of the sale or return. """
        raise NotImplementedError()

    def _taxcloud_get_refund_origin(self):
        """ The reported document this refund returns items of. """
        raise NotImplementedError()

    def _taxcloud_get_refund_quantities(self):
        """ ``(returned, sold)``: quantities by TaxCloud item ID returned by this refund and sold
        on its origin. """
        raise NotImplementedError()

    def _taxcloud_has_other_reported_refunds(self):
        """ Whether another refund of the same origin was already reported. """
        raise NotImplementedError()

    def _taxcloud_get_mismatch_hint(self):
        """ What the user should do when TaxCloud no longer computes the recorded tax. """
        return ""

    # Queue
    # =====
    def _taxcloud_mark_to_report(self):
        self.write({
            'taxcloud_sync_state': 'to_sync',
            'taxcloud_sync_attempts': 0,
            'taxcloud_sync_error': False,
        })
        self._taxcloud_get_report_cron()._trigger()

    @api.model
    def _cron_taxcloud_report(self):
        """ Report documents to TaxCloud, oldest first so sales go before their refunds. """
        records = self.search([('taxcloud_sync_state', '=', 'to_sync')], order='id')
        remaining = len(records)
        for record in records:
            remaining -= 1
            if not record.try_lock_for_update(allow_referencing=True):
                continue  # being processed elsewhere
            record._taxcloud_report_with_savepoint()
            if not module.current_test:
                if self.env['ir.cron']._commit_progress(1, remaining=remaining) <= 0:
                    break

    def action_taxcloud_retry_report(self):
        """ Reset the attempt counter and try to report right away. """
        records = self.filtered(lambda record: record.taxcloud_sync_state in ('to_sync', 'error'))
        records.write({'taxcloud_sync_state': 'to_sync', 'taxcloud_sync_attempts': 0, 'taxcloud_sync_error': False})
        for record in records:
            record._taxcloud_report_with_savepoint()
        return True

    def _taxcloud_report_with_savepoint(self):
        """ Report one document; never raises, the outcome is stored on the document. """
        self.ensure_one()
        if self.taxcloud_waiting_for_origin:
            return
        try:
            with self.env.cr.savepoint():
                self.with_company(self.company_id)._taxcloud_report()
        except TaxCloudError as e:
            self._taxcloud_set_report_error(str(e), retryable=e.is_retryable)
        except UserError as e:
            self._taxcloud_set_report_error(str(e), retryable=False)
        except Exception as e:  # noqa: BLE001 - one broken document must not stop the batch
            _logger.exception("Unexpected error while reporting %s to TaxCloud", self.display_name)
            self._taxcloud_set_report_error(str(e), retryable=True)
        else:
            self.write({
                'taxcloud_sync_state': 'synced',
                'taxcloud_sync_error': False,
                'taxcloud_synced_date': fields.Datetime.now(),
            })

    def _taxcloud_set_report_error(self, message, retryable):
        attempts = self.taxcloud_sync_attempts + 1
        give_up = not retryable or attempts >= MAX_REPORT_ATTEMPTS
        self.write({
            'taxcloud_sync_state': 'error' if give_up else 'to_sync',
            'taxcloud_sync_attempts': attempts,
            'taxcloud_sync_error': message,
        })

    # Reporting
    # =========
    def _taxcloud_report(self):
        {
            'order': self._taxcloud_report_order,
            'refund': self._taxcloud_report_refund,
            'credit': self._taxcloud_report_credit,
        }[self.taxcloud_report_kind]()

    def _taxcloud_get_report_order_id(self):
        """ The document number, restricted to the characters TaxCloud order IDs safely accept. """
        return re.sub(r'[^A-Za-z0-9._-]', '-', self._taxcloud_get_report_reference())

    def _taxcloud_get_completed_date(self):
        """ The document date (noon UTC) when in the past, None (= now) otherwise: TaxCloud rejects future dates. """
        date = self._taxcloud_get_report_date()
        if date >= fields.Date.context_today(self):
            return None
        return self._taxcloud_format_date(date)

    def _taxcloud_get_posted_tax_amount(self, line):
        manual_tax_amounts = (line.extra_tax_data or {}).get('manual_tax_amounts') or {}
        return sum(values.get('tax_amount_currency', 0.0) for values in manual_tax_amounts.values())

    def _taxcloud_build_posted_cart(self):
        """ Cart rebuilt from the recorded lines, plus {cart index: line}. """
        base_lines = self._taxcloud_get_base_lines()
        if not base_lines:
            raise UserError(self.env._("%(move)s has no line to report to TaxCloud.", move=self.display_name))
        return self._taxcloud_prepare_cart(base_lines)

    def _taxcloud_report_order(self):
        """ Upsert the cart from the recorded lines, check TaxCloud still computes the recorded tax,
        then convert it to a completed order. """
        client = self.company_id._get_taxcloud_client(res_model=self._name, res_id=self.id)
        order_id = self.taxcloud_order_id or self._taxcloud_get_report_order_id()
        cart, line_by_index = self._taxcloud_build_posted_cart()
        transaction_date = self._taxcloud_format_date(self._taxcloud_get_document_date())

        response = client.create_carts([cart], transaction_date=transaction_date)
        tax_by_index = self._taxcloud_parse_cart_response(response, cart['cartId'])
        taxcloud_total = self.currency_id.round(sum((tax or {}).get('amount') or 0.0 for tax in tax_by_index.values()))
        posted_total = self.currency_id.round(sum(self._taxcloud_get_posted_tax_amount(line) for line in line_by_index.values()))
        if self.currency_id.compare_amounts(taxcloud_total, posted_total):
            raise UserError(self.env._(
                "TaxCloud now computes %(taxcloud)s of tax for %(move)s, but %(posted)s was posted. %(hint)s",
                taxcloud=taxcloud_total, posted=posted_total, move=self.display_name, hint=self._taxcloud_get_mismatch_hint(),
            ))

        completed_date = self._taxcloud_get_completed_date()
        try:
            client.convert_cart_to_order(cart['cartId'], order_id, completed=True, completed_date=completed_date)
        except TaxCloudError as e:
            if e.is_retryable or not self._taxcloud_order_exists(client, order_id, cart):
                raise
            _logger.info("TaxCloud order %s already exists, counting %s as reported", order_id, self.display_name)
        self.taxcloud_order_id = order_id

    def _taxcloud_order_exists(self, client, order_id, cart):
        """ Idempotent retry: a previous attempt may have created the order before failing.

        Order IDs are document numbers, so another document or another database sharing the
        connection (e.g. a staging copy) can have used the same ID: the existing order only counts
        as this document's when it has the same customer and items. """
        try:
            order = client.get_order(order_id)
        except TaxCloudError as e:
            if e.status_code == 404:
                return False
            raise
        if str(order.get('customerId')) != str(cart['customerId']):
            raise UserError(self.env._(
                "TaxCloud order %(order)s already exists for another customer.", order=order_id,
            ))
        if self._taxcloud_get_items_signature(order.get('lineItems')) != self._taxcloud_get_items_signature(cart['lineItems']):
            raise UserError(self.env._(
                "TaxCloud order %(order)s already exists with other items. It was probably reported by another "
                "document or by another database using the same TaxCloud connection.", order=order_id,
            ))
        return True

    @api.model
    def _taxcloud_get_items_signature(self, line_items):
        return sorted(
            (str(item.get('itemId')), round(float(item.get('quantity') or 0.0), 6), round(float(item.get('price') or 0.0), 6))
            for item in line_items or []
        )

    def _taxcloud_get_refund_idempotency_key(self):
        return f"odoo-{self._taxcloud_get_dbuuid()[:8]}-{self._name}-refund-{self.id}"

    def _taxcloud_report_refund(self):
        """ Refund the original TaxCloud order: in full when this refund returns everything and is
        its first refund, otherwise by item and quantity. """
        origin = self._taxcloud_get_refund_origin()
        client = self.company_id._get_taxcloud_client(res_model=self._name, res_id=self.id)
        returned, sold = self._taxcloud_get_refund_quantities()
        is_full = not self._taxcloud_has_other_reported_refunds() and returned == sold
        items = None if is_full else [
            {'itemId': item_id, 'quantity': quantity} for item_id, quantity in returned.items()
        ]
        idempotency_key = self._taxcloud_get_refund_idempotency_key()
        refunds = client.refund_order(
            origin.taxcloud_order_id,
            items=items,
            returned_date=self._taxcloud_get_completed_date(),
            idempotency_key=idempotency_key,
        )
        self.taxcloud_order_id = origin.taxcloud_order_id

        refund = next((r for r in refunds or [] if isinstance(r, dict) and r.get('idempotencyKey') == idempotency_key), None)
        if refund:
            refunded_tax = self.currency_id.round(sum((item.get('tax') or {}).get('amount') or 0.0 for item in refund.get('items') or []))
            if self.currency_id.compare_amounts(abs(refunded_tax), abs(self.amount_tax)):
                self._taxcloud_post_note(self.env._(
                    "TaxCloud refunded %(taxcloud)s of tax, Odoo credited %(odoo)s.",
                    taxcloud=abs(refunded_tax), odoo=abs(self.amount_tax),
                ))

    def _taxcloud_report_credit(self):
        """ Standalone credit: create a completed order of kind "credit" carrying the recorded taxes. """
        client = self.company_id._get_taxcloud_client(res_model=self._name, res_id=self.id)
        order_id = self.taxcloud_order_id or self._taxcloud_get_report_order_id()
        cart, line_by_index = self._taxcloud_build_posted_cart()
        for item in cart['lineItems']:
            line = line_by_index[item['index']]
            amount = self._taxcloud_get_posted_tax_amount(line)
            rate = line.tax_ids.filtered('is_taxcloud')[:1].amount / 100.0
            item['tax'] = {'amount': amount, 'rate': rate}
        date = self._taxcloud_get_completed_date() or self._taxcloud_format_date(fields.Date.context_today(self))
        order = {
            **{key: value for key, value in cart.items() if key != 'cartId'},
            'orderId': order_id,
            'kind': 'credit',
            'transactionDate': date,
            'completedDate': date,
        }
        try:
            client.create_order(order)
        except TaxCloudError as e:
            if e.is_retryable or not self._taxcloud_order_exists(client, order_id, cart):
                raise
        self.taxcloud_order_id = order_id

    def _taxcloud_get_dbuuid(self):
        return self.env['ir.config_parameter'].sudo().get_str('database.uuid')
