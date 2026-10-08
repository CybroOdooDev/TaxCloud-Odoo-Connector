# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from contextlib import ExitStack
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudClient, TaxCloudError
from odoo.addons.taxcloud_connector.tests.common import TaxCloudInvoiceCommon
from odoo.addons.taxcloud_connector.tests import test_taxcloud_reporting


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudPos(TaxCloudInvoiceCommon):

    # Fake TaxCloud order endpoints, shared with the invoice reporting tests
    _fake_convert = test_taxcloud_reporting.TestTaxCloudReporting._fake_convert
    _fake_get_order = test_taxcloud_reporting.TestTaxCloudReporting._fake_get_order
    _fake_refund = test_taxcloud_reporting.TestTaxCloudReporting._fake_refund

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('point_of_sale.group_pos_manager')
        cls.company.account_default_pos_receivable_account_id = cls.env['account.account'].create({
            'code': 'X1012.POS', 'name': 'Debtors - (POS)', 'account_type': 'asset_receivable', 'reconcile': True,
        })
        cash_journal = cls.company_data['default_journal_cash']
        cash_journal.pos_payment_method_ids.unlink()
        cls.cash_pm = cls.env['pos.payment.method'].create({
            'name': 'Cash', 'type': 'cash', 'journal_id': cash_journal.id, 'company_id': cls.company.id,
        })
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'TaxCloud Shop',
            'journal_id': cls.company_data['default_journal_sale'].id,
            'payment_method_ids': [Command.set(cls.cash_pm.ids)],
            'default_fiscal_position_id': cls.fpos_taxcloud.id,
        })
        cls.product_book.available_in_pos = True
        cls.partner_us.write({'street': '9 Customer Rd', 'zip': '98109'})

    def setUp(self):
        super().setUp()
        self.orders = {}  # orderId -> order dict, what TaxCloud "knows"
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.create_carts = stack.enter_context(self._patch_carts())
        self.mocks = {
            name: stack.enter_context(patch.object(TaxCloudClient, name, autospec=True, side_effect=side_effect))
            for name, side_effect in (
                ('convert_cart_to_order', self._fake_convert),
                ('get_order', self._fake_get_order),
                ('refund_order', self._fake_refund),
            )
        }
        self.pos_config.open_ui()
        self.session = self.pos_config.current_session_id
        self.session.set_opening_control(0, None)

    # Helpers
    # =======
    def _order_data(self, quantity=1.0, partner=None, **vals):
        uuid = str(uuid4())
        price = self.product_book.lst_price
        return {
            'uuid': uuid,
            'name': f'Order {uuid}',
            'session_id': self.session.id,
            'user_id': self.env.uid,
            'partner_id': partner and partner.id,
            'fiscal_position_id': self.fpos_taxcloud.id,
            'date_order': fields.Datetime.to_string(fields.Datetime.now()),
            'state': 'draft',
            'amount_paid': 0.0, 'amount_return': 0.0, 'amount_tax': 0.0, 'amount_total': price * quantity,
            'lines': [Command.create({
                'product_id': self.product_book.id, 'qty': quantity, 'price_unit': price, 'discount': 0.0,
                'price_subtotal': price * quantity, 'price_subtotal_incl': price * quantity, 'tax_ids': [Command.set([])],
            })],
            'payment_ids': [],
            **vals,
        }

    def _pay_button(self, order_data):
        """ What the POS does when the cashier opens the payment screen. """
        res = self.env['pos.order'].taxcloud_get_order_tax_details([order_data])
        return self.env['pos.order'].browse(res['pos.order'][0]['id'])

    def _pay(self, order):
        order._compute_prices()
        order.add_payment({'pos_order_id': order.id, 'amount': order.amount_total, 'payment_method_id': self.cash_pm.id})
        order.action_pos_order_paid()
        return order

    def _refund(self, order, quantity=None):
        refund = order._refund()
        if quantity is not None:
            refund.lines.qty = -quantity
        refund.action_taxcloud_compute_taxes()
        return self._pay(refund)

    # Tax computation
    # ===============
    def test_tax_computed_at_payment(self):
        order = self._pay_button(self._order_data())
        self.assertTrue(order.is_taxcloud_computed)
        self.assertTrue(order.lines.tax_ids.is_taxcloud)
        order._compute_prices()
        self.assertAlmostEqual(order.amount_tax, round(100.0 * self.RATE, 2))
        cart = self.carts_sent[-1]['carts'][0]
        self.assertEqual(cart['destination']['line1'], '100 Origin Way', "Sold at the counter: taxed at the shop")
        self.assertEqual(cart['customerId'], f'{self.company.id}-anonymous')

    def test_unchanged_order_not_recomputed(self):
        data = self._order_data()
        self._pay_button(data)
        self._pay_button({**data, 'lines': []})
        self.assertEqual(self.create_carts.call_count, 1)

    def test_delivery_taxed_at_customer_address(self):
        preset = self.env['pos.preset'].create({'name': 'Delivery', 'identification': 'address', 'fiscal_position_id': self.fpos_taxcloud.id})
        self._pay_button(self._order_data(partner=self.partner_us, preset_id=preset.id))
        self.assertEqual(self.carts_sent[-1]['carts'][0]['destination']['line1'], '9 Customer Rd')
        self.assertEqual(self.carts_sent[-1]['carts'][0]['customerId'], str(self.partner_us.id))

    def test_not_taxcloud(self):
        order = self._pay_button(self._order_data(fiscal_position_id=False))
        self._pay(order)
        self.assertFalse(self.create_carts.called)
        self.assertFalse(order.taxcloud_sync_state)

    def test_unavailable_blocks_payment(self):
        self.create_carts.side_effect = TaxCloudError('Service Unavailable', 503)
        with self.assertRaisesRegex(UserError, 'Service Unavailable'):
            self._pay_button(self._order_data())

    # Reporting
    # =========
    def test_paid_order_reported(self):
        order = self._pay(self._pay_button(self._order_data()))
        self.assertEqual(order.taxcloud_sync_state, 'to_sync')
        self.env['pos.order']._cron_taxcloud_report()
        self.assertEqual(order.taxcloud_sync_state, 'synced', order.taxcloud_sync_error)
        self.assertEqual(order.taxcloud_order_id, order._taxcloud_get_report_order_id())
        self.assertIn(order.taxcloud_order_id, self.orders)
        self.assertNotRegex(order.taxcloud_order_id, r'[^A-Za-z0-9._-]')

    def test_full_refund(self):
        order = self._pay(self._pay_button(self._order_data(quantity=2.0)))
        self.env['pos.order']._cron_taxcloud_report()
        refund = self._refund(order)
        self.assertAlmostEqual(refund.amount_tax, -order.amount_tax, msg="The tax of the order is given back")
        self.assertEqual(self.create_carts.call_count, 2, "Order + its report; the refund creates no cart")
        self.env['pos.order']._cron_taxcloud_report()
        self.assertEqual(refund.taxcloud_sync_state, 'synced', refund.taxcloud_sync_error)
        self.mocks['refund_order'].assert_called_once()
        self.assertIsNone(self.mocks['refund_order'].call_args.kwargs['items'], "Full refund")

    def test_partial_refund(self):
        order = self._pay(self._pay_button(self._order_data(quantity=2.0)))
        self.env['pos.order']._cron_taxcloud_report()
        refund = self._refund(order, quantity=1.0)
        self.assertAlmostEqual(refund.amount_tax, -order.currency_id.round(order.amount_tax / 2))
        self.env['pos.order']._cron_taxcloud_report()
        self.assertEqual(refund.taxcloud_sync_state, 'synced', refund.taxcloud_sync_error)
        self.assertEqual(
            self.mocks['refund_order'].call_args.kwargs['items'],
            [{'itemId': f'line-{order.lines.id}', 'quantity': 1.0}],
        )

    def test_refund_waits_for_order(self):
        order = self._pay(self._pay_button(self._order_data()))
        refund = self._refund(order)
        self.assertTrue(refund.taxcloud_waiting_for_origin)
        self.env['pos.order']._cron_taxcloud_report()
        self.assertEqual(order.taxcloud_sync_state, 'synced')
        self.assertEqual(refund.taxcloud_sync_state, 'synced', "Oldest first: the order goes before its refund")

    def test_unlinked_return_reported_as_credit(self):
        with patch.object(TaxCloudClient, 'create_order', autospec=True, return_value={}) as create_order:
            order = self._pay(self._pay_button(self._order_data(quantity=-1.0)))
            self.assertAlmostEqual(order.amount_tax, -round(100.0 * self.RATE, 2))
            self.assertEqual(order.taxcloud_report_kind, 'credit')
            self.env['pos.order']._cron_taxcloud_report()
        self.assertEqual(order.taxcloud_sync_state, 'synced', order.taxcloud_sync_error)
        self.assertFalse(self.mocks['convert_cart_to_order'].called, "A return is never reported as a sale")
        sent = create_order.call_args.args[1]
        self.assertEqual(sent['kind'], 'credit')
        self.assertEqual(sent['lineItems'][0]['quantity'], 1.0)

    def test_invoice_not_reported_separately(self):
        order = self._pay(self._pay_button(self._order_data(partner=self.partner_us)))
        order.action_pos_order_invoice()
        invoice = order.account_move
        self.assertTrue(invoice)
        self.assertFalse(invoice.is_taxcloud_computed)
        self.assertFalse(invoice.taxcloud_sync_state)
        self.assertAlmostEqual(invoice.amount_tax, order.amount_tax)
        self.assertEqual(self.create_carts.call_count, 1, "The invoice keeps the order's taxes")
