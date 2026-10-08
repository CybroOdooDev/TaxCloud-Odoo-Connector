# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from contextlib import ExitStack
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudClient, TaxCloudError
from .common import TaxCloudInvoiceCommon


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudReporting(TaxCloudInvoiceCommon):

    def setUp(self):
        super().setUp()
        self.date = fields.Date.today() - timedelta(days=7)
        self.orders = {}  # orderId -> order dict, what TaxCloud "knows"
        self.mocks = {}
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.mocks['create_carts'] = stack.enter_context(self._patch_carts())
        for name, side_effect in (
            ('convert_cart_to_order', self._fake_convert),
            ('get_order', self._fake_get_order),
            ('refund_order', self._fake_refund),
            ('void_order', self._fake_void),
            ('create_order', self._fake_create_order),
        ):
            self.mocks[name] = stack.enter_context(
                patch.object(TaxCloudClient, name, autospec=True, side_effect=side_effect),
            )

    # Fake TaxCloud
    # =============
    def _fake_convert(self, client, cart_id, order_id, completed=True, completed_date=None):
        if order_id in self.orders:
            raise TaxCloudError('Order already exists', 400)
        cart = self.carts_sent[-1]['carts'][0]
        self.orders[order_id] = {'orderId': order_id, 'customerId': cart['customerId'], 'refunds': []}
        return self.orders[order_id]

    def _fake_get_order(self, client, order_id, expand_refunds=False):
        if order_id not in self.orders:
            raise TaxCloudError('Order not found', 404)
        return self.orders[order_id]

    def _fake_refund(self, client, order_id, items=None, returned_date=None, idempotency_key=None):
        order = self.orders[order_id]
        refund = {'idempotencyKey': idempotency_key, 'items': [
            {'itemId': item['itemId'], 'quantity': item['quantity'], 'tax': {'amount': -1.0}} for item in items or []
        ]}
        order['refunds'].append(refund)
        return order['refunds']

    def _fake_void(self, client, order_id):
        self.orders.pop(order_id, None)
        return {}

    def _fake_create_order(self, client, order):
        if order['orderId'] in self.orders:
            raise TaxCloudError('Order already exists', 400)
        self.orders[order['orderId']] = {**order, 'refunds': []}
        return order

    # Helpers
    # =======
    def _posted_invoice(self, **vals):
        return self._invoice([
            self._line(self.product_shirt, quantity=3.0, price_unit=10.0),
            self._line(self.product_book, quantity=2.0),
        ], invoice_date=self.date, post=True, **vals)

    def _run_cron(self):
        self.env['account.move']._cron_taxcloud_report()

    def _reverse(self, invoice, post=True):
        credit_note = invoice._reverse_moves([{'invoice_date': self.date}])
        if post:
            credit_note.action_post()
        return credit_note

    # Invoices
    # ========
    def test_post_marks_to_report_and_triggers_cron(self):
        cron = self.env.ref('taxcloud_connector.ir_cron_taxcloud_report')
        triggers_before = self.env['ir.cron.trigger'].search_count([('cron_id', '=', cron.id)])
        invoice = self._posted_invoice()
        self.assertEqual(invoice.taxcloud_sync_state, 'to_sync')
        self.assertGreater(self.env['ir.cron.trigger'].search_count([('cron_id', '=', cron.id)]), triggers_before)

    def test_report_success(self):
        invoice = self._posted_invoice()
        invoice.name = 'INV/2026/00042'
        self._run_cron()
        self.assertRecordValues(invoice, [{
            'taxcloud_sync_state': 'synced', 'taxcloud_order_id': 'INV-2026-00042', 'taxcloud_sync_error': False,
        }])
        self.assertTrue(invoice.taxcloud_synced_date)
        convert = self.mocks['convert_cart_to_order']
        convert.assert_called_once()
        _client, cart_id, order_id = convert.call_args.args
        self.assertEqual(cart_id, invoice._taxcloud_get_cart_id())
        self.assertEqual(order_id, 'INV-2026-00042')
        self.assertEqual(convert.call_args.kwargs, {'completed': True, 'completed_date': f'{self.date.isoformat()}T12:00:00Z'})
        # The cart is upserted from the posted invoice right before the conversion.
        self.assertEqual(self.carts_sent[-1]['carts'][0]['cartId'], cart_id)

    def test_report_today_lets_taxcloud_date_it(self):
        invoice = self._invoice([self._line(self.product_book)], invoice_date=fields.Date.today(), post=True)
        self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'synced')
        self.assertIsNone(self.mocks['convert_cart_to_order'].call_args.kwargs['completed_date'])

    def test_transient_error_retried_then_gives_up(self):
        invoice = self._posted_invoice()
        self.mocks['convert_cart_to_order'].side_effect = TaxCloudError('Service Unavailable', 503)
        self._run_cron()
        self.assertRecordValues(invoice, [{'taxcloud_sync_state': 'to_sync', 'taxcloud_sync_attempts': 1}])
        self.assertIn('Service Unavailable', invoice.taxcloud_sync_error)
        for _i in range(4):
            self._run_cron()
        self.assertRecordValues(invoice, [{'taxcloud_sync_state': 'error', 'taxcloud_sync_attempts': 5}])
        self._run_cron()
        self.assertEqual(self.mocks['convert_cart_to_order'].call_count, 5, "No more attempts after 5")

    def test_permanent_error_stops_immediately(self):
        invoice = self._posted_invoice()
        self.mocks['convert_cart_to_order'].side_effect = TaxCloudError('Invalid content', 422)
        self._run_cron()
        self.assertRecordValues(invoice, [{'taxcloud_sync_state': 'error', 'taxcloud_sync_attempts': 1}])
        self.mocks['get_order'].assert_called_once()  # checked whether the order already existed

    def test_idempotent_retry_counts_existing_order(self):
        invoice = self._posted_invoice()
        order_id = invoice._taxcloud_get_report_order_id()
        self.orders[order_id] = {'orderId': order_id, 'customerId': str(self.partner_us.id), 'refunds': []}
        self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'synced')

    def test_existing_order_of_other_customer_is_error(self):
        invoice = self._posted_invoice()
        order_id = invoice._taxcloud_get_report_order_id()
        self.orders[order_id] = {'orderId': order_id, 'customerId': '999999', 'refunds': []}
        self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'error')
        self.assertIn('another customer', invoice.taxcloud_sync_error)

    def test_tax_changed_since_posting_is_error(self):
        invoice = self._posted_invoice()
        self.tax_overrides = {line.taxcloud_item_id: {'amount': 99.0, 'rate': self.RATE} for line in invoice.invoice_line_ids}
        self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'error')
        self.assertIn('was posted', invoice.taxcloud_sync_error)
        self.mocks['convert_cart_to_order'].assert_not_called()

    def test_retry_button(self):
        invoice = self._posted_invoice()
        self.mocks['convert_cart_to_order'].side_effect = TaxCloudError('Invalid content', 422)
        self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'error')
        self.mocks['convert_cart_to_order'].side_effect = self._fake_convert
        invoice.action_taxcloud_retry_report()
        self.assertRecordValues(invoice, [{'taxcloud_sync_state': 'synced', 'taxcloud_sync_attempts': 0}])

    def test_one_failure_does_not_stop_batch(self):
        bad = self._posted_invoice()
        good = self._posted_invoice()
        bad_order_id = bad._taxcloud_get_report_order_id()

        def convert(client, cart_id, order_id, **kwargs):
            if order_id == bad_order_id:
                raise TaxCloudError('Invalid content', 422)
            return self._fake_convert(client, cart_id, order_id, **kwargs)
        self.mocks['convert_cart_to_order'].side_effect = convert
        self._run_cron()
        self.assertEqual(bad.taxcloud_sync_state, 'error')
        self.assertEqual(good.taxcloud_sync_state, 'synced')

    def test_not_reported(self):
        canada = self.env['res.partner'].create({
            'name': 'CA', 'street': '1 Rue', 'city': 'Montreal', 'zip': 'H2X', 'country_id': self.env.ref('base.ca').id,
        })
        foreign = self._invoice([self._line(self.product_book)], partner=canada, post=True)
        plain = self._invoice([self._line(self.product_book)], fiscal_position_id=False, post=True)
        self.assertFalse(foreign.taxcloud_sync_state)
        self.assertFalse(plain.taxcloud_sync_state)

    def test_errors_are_logged_with_document(self):
        invoice = self._posted_invoice()
        written = []

        def failing_convert(client, cart_id, order_id, **kwargs):
            client._call_log_hook({
                'method': 'POST', 'endpoint': '/carts/orders', 'request_body': {'orderId': order_id},
                'status_code': 422, 'response_body': '{}', 'duration_ms': 1, 'attempt': 1, 'error': 'boom',
            })
            raise TaxCloudError('boom', 422)
        self.mocks['convert_cart_to_order'].side_effect = failing_convert
        # Capture instead of writing: the report savepoint would roll back entries made on the test cursor.
        with patch.object(type(self.env['taxcloud.log']), '_write_log', autospec=True,
                          side_effect=lambda log, vals: written.append(vals)):
            self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'error')
        self.assertRecordValues(invoice, [{'taxcloud_sync_error': '[422] boom'}])
        self.assertEqual([(v['res_model'], v['res_id'], v['level']) for v in written], [('account.move', invoice.id, 'error')])

    # Refunds
    # =======
    def test_full_refund(self):
        invoice = self._posted_invoice()
        credit_note = self._reverse(invoice)
        self.assertEqual(credit_note.taxcloud_sync_state, 'to_sync')
        self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'synced')
        self.assertRecordValues(credit_note, [{'taxcloud_sync_state': 'synced', 'taxcloud_order_id': invoice.taxcloud_order_id}])
        refund = self.mocks['refund_order']
        refund.assert_called_once()
        self.assertEqual(refund.call_args.args[1], invoice.taxcloud_order_id)
        self.assertIsNone(refund.call_args.kwargs['items'], "Full refund: empty body")
        self.assertEqual(refund.call_args.kwargs['returned_date'], f'{self.date.isoformat()}T12:00:00Z')
        self.assertTrue(refund.call_args.kwargs['idempotency_key'].endswith(f'-refund-{credit_note.id}'))

    def test_partial_refunds(self):
        invoice = self._posted_invoice()
        self._run_cron()
        shirt_item = invoice.invoice_line_ids.filtered(lambda line: line.product_id == self.product_shirt).taxcloud_item_id

        def partial(quantity):
            credit_note = self._reverse(invoice, post=False)
            shirt = credit_note.invoice_line_ids.filtered(lambda line: line.product_id == self.product_shirt)
            book = credit_note.invoice_line_ids - shirt
            credit_note.write({'invoice_line_ids': [Command.update(shirt.id, {'quantity': quantity}), Command.unlink(book.id)]})
            credit_note.action_post()
            self._run_cron()
            return credit_note

        first = partial(1.0)
        second = partial(2.0)
        self.assertEqual((first | second).mapped('taxcloud_sync_state'), ['synced', 'synced'])
        calls = self.mocks['refund_order'].call_args_list
        self.assertEqual(calls[0].kwargs['items'], [{'itemId': shirt_item, 'quantity': 1.0}])
        self.assertEqual(calls[1].kwargs['items'], [{'itemId': shirt_item, 'quantity': 2.0}])

    def test_full_quantities_after_partial_refund_sent_by_item(self):
        invoice = self._posted_invoice()
        self._run_cron()
        self._reverse(invoice)
        self._run_cron()
        second = self._reverse(invoice)
        self._run_cron()
        self.assertEqual(second.taxcloud_sync_state, 'synced')
        self.assertIsNotNone(self.mocks['refund_order'].call_args.kwargs['items'],
                             "An empty body would only refund the remaining balance")

    def test_refund_waits_for_invoice(self):
        invoice = self._posted_invoice()
        self.mocks['convert_cart_to_order'].side_effect = TaxCloudError('Service Unavailable', 503)
        credit_note = self._reverse(invoice)
        self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'to_sync')
        self.assertRecordValues(credit_note, [{
            'taxcloud_sync_state': 'to_sync', 'taxcloud_sync_attempts': 0, 'taxcloud_waiting_for_origin': True,
        }])
        self.mocks['refund_order'].assert_not_called()

        self.mocks['convert_cart_to_order'].side_effect = self._fake_convert
        self._run_cron()
        self.assertEqual(invoice.taxcloud_sync_state, 'synced')
        self.assertEqual(credit_note.taxcloud_sync_state, 'synced', "Invoices are processed before their refunds")

    def test_refund_tax_difference_noted(self):
        invoice = self._posted_invoice()
        self._run_cron()
        credit_note = self._reverse(invoice, post=False)
        credit_note.write({'invoice_line_ids': [Command.update(credit_note.invoice_line_ids[0].id, {'quantity': 1.0}),
                                                Command.unlink(credit_note.invoice_line_ids[1].id)]})
        credit_note.action_post()
        self._run_cron()
        self.assertTrue(credit_note.message_ids.filtered(lambda m: 'TaxCloud refunded' in (m.body or '')))

    def test_refund_over_limit_is_error(self):
        invoice = self._posted_invoice()
        self._run_cron()
        self.mocks['refund_order'].side_effect = TaxCloudError('Refund exceeds remaining amount', 422)
        credit_note = self._reverse(invoice)
        self._run_cron()
        self.assertEqual(credit_note.taxcloud_sync_state, 'error')

    # Standalone credits
    # ==================
    def test_standalone_credit(self):
        credit_note = self._invoice([self._line(self.product_book, quantity=2.0)], move_type='out_refund',
                                    invoice_date=self.date, post=True)
        self.assertEqual(credit_note.taxcloud_report_kind, 'credit')
        self._run_cron()
        self.assertEqual(credit_note.taxcloud_sync_state, 'synced')
        order = self.mocks['create_order'].call_args.args[1]
        line = credit_note.invoice_line_ids
        self.assertEqual(order['kind'], 'credit')
        self.assertEqual(order['orderId'], credit_note._taxcloud_get_report_order_id())
        self.assertEqual(order['completedDate'], f'{self.date.isoformat()}T12:00:00Z')
        self.assertEqual(order['transactionDate'], order['completedDate'])
        self.assertNotIn('cartId', order)
        self.assertEqual(order['lineItems'], [{
            'index': 0, 'itemId': f'line-{line.id}', 'price': 100.0, 'quantity': 2.0, 'tic': 30070,
            'tax': {'amount': credit_note.amount_tax, 'rate': self.RATE},
        }])

    # Reset to draft
    # ==============
    def test_reset_to_draft_voids_and_reports_again(self):
        invoice = self._posted_invoice()
        self._run_cron()
        order_id = invoice.taxcloud_order_id
        invoice.button_draft()
        self.mocks['void_order'].assert_called_once()
        self.assertEqual(self.mocks['void_order'].call_args.args[1], order_id)
        self.assertRecordValues(invoice, [{'state': 'draft', 'taxcloud_sync_state': False, 'taxcloud_order_id': False}])
        invoice.action_post()
        self._run_cron()
        self.assertRecordValues(invoice, [{'taxcloud_sync_state': 'synced', 'taxcloud_order_id': order_id}])

    def test_reset_to_draft_blocked_after_void_cutoff(self):
        invoice = self._posted_invoice()
        self._run_cron()
        self.mocks['void_order'].side_effect = TaxCloudError('Cannot void after filing cutoff', 422)
        with self.assertRaisesRegex(UserError, '10th of the month'):
            invoice.button_draft()
        # Drop values still pending in the cache (a real request discards them with its transaction).
        self.env.invalidate_all(flush=False)
        self.assertRecordValues(invoice, [{'state': 'posted', 'taxcloud_sync_state': 'synced'}])

    def test_reset_to_draft_blocked_with_reported_refund(self):
        invoice = self._posted_invoice()
        credit_note = self._reverse(invoice)
        self._run_cron()
        with self.assertRaisesRegex(UserError, 'refunds .* were already reported'):
            invoice.button_draft()
        with self.assertRaisesRegex(UserError, 'cannot be undone'):
            credit_note.button_draft()
        self.mocks['void_order'].assert_not_called()

    def test_reset_unreported_invoice(self):
        invoice = self._posted_invoice()
        invoice.button_draft()
        self.mocks['void_order'].assert_not_called()
        self.assertFalse(invoice.taxcloud_sync_state)

    def test_void_not_found_is_fine(self):
        invoice = self._posted_invoice()
        self._run_cron()
        self.mocks['void_order'].side_effect = TaxCloudError('Order not found', 404)
        invoice.button_draft()
        self.assertEqual(invoice.state, 'draft')
