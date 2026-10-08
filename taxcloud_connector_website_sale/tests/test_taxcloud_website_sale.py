# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged

from odoo.addons.taxcloud_connector.models import res_partner as res_partner_module
from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudClient, TaxCloudError
from odoo.addons.taxcloud_connector.tests.common import TaxCloudInvoiceCommon
from odoo.addons.website_sale.tests.common import MockRequest
from odoo.addons.taxcloud_connector_website_sale.controllers.main import TaxCloudDelivery

UNAVAILABLE = TaxCloudError('Service Unavailable', 503)
INVALID = TaxCloudError('validation failed', 422, [{'location': 'body.items[0].destination.zip', 'message': 'invalid zip'}])


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudWebsiteSale(TaxCloudInvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.website = cls.env['website'].search([('company_id', '=', cls.company.id)], limit=1) or \
            cls.env['website'].create({'name': 'TaxCloud Shop', 'company_id': cls.company.id})
        cls.product_service = cls.env['product.product'].create({
            'name': 'Online course', 'type': 'service', 'list_price': 100.0, 'taxcloud_tic': '30070',
            'invoice_policy': 'order', 'taxes_id': [Command.set(cls.company_data['default_tax_sale'].ids)],
        })
        cls.fpos_taxcloud.write({'auto_apply': True, 'country_id': cls.us.id, 'sequence': 1})
        # Complete billing details, so checkout validation gets as far as taxes.
        cls.partner_us.write({'email': 'customer@example.com', 'phone': '+1 206 555 0100'})

    def _cart_order(self, quantity=1.0):
        return self.env['sale.order'].create({
            'partner_id': self.partner_us.id,
            'website_id': self.website.id,
            'order_line': [Command.create({'product_id': self.product_service.id, 'product_uom_qty': quantity})],
        })

    def _blocking_messages(self, order):
        return [alert['message'] for alert in order._get_alerts() if alert.get('blocking')]

    # Fiscal position
    # ===============
    def test_fiscal_position_auto_applied_and_kept(self):
        order = self._cart_order()
        self.assertEqual(order.fiscal_position_id, self.fpos_taxcloud, "Auto-applied for a US customer")
        self.assertTrue(order.is_taxcloud_computed)
        with self._patch_carts():
            order.action_confirm()
            invoice = order._create_invoices()
            invoice.action_post()
        self.assertEqual(invoice.fiscal_position_id, self.fpos_taxcloud)
        self.assertTrue(invoice.invoice_line_ids.tax_ids.is_taxcloud)
        self.assertAlmostEqual(invoice.amount_tax, round(100.0 * self.RATE, 2))

    # Cart refresh (payment step and payment transaction)
    # ===================================================
    def test_cart_refresh_reuses_result(self):
        order = self._cart_order()
        with self._patch_carts() as create_carts:
            order._update_cart_taxes_and_prices()
            self.assertEqual(create_carts.call_count, 1, "One call, not one per computation in the refresh")
            order._clear_alerts()
            self.assertFalse(order._update_cart_taxes_and_prices(), "Unchanged cart: same total")
            self.assertEqual(create_carts.call_count, 1, "Odoo resets line taxes on each refresh; the result is reused")
            self.assertTrue(order.order_line.tax_ids.is_taxcloud)
            order.order_line.product_uom_qty = 2.0
            order._update_cart_taxes_and_prices()
            self.assertEqual(create_carts.call_count, 2, "Cart changed: computed again")
        self.assertFalse(self._blocking_messages(order))
        self.assertAlmostEqual(order.amount_tax, round(200.0 * self.RATE, 2))

    def test_unavailable_blocks_with_own_message(self):
        order = self._cart_order()
        with self._patch_carts(side_effect=UNAVAILABLE) as create_carts:
            self.assertTrue(order._update_cart_taxes_and_prices())
        messages = self._blocking_messages(order)
        self.assertEqual(len(messages), 1, messages)
        self.assertIn('try again in a few minutes', messages[0])
        self.assertNotIn('address', messages[0])
        self.assertEqual(create_carts.call_count, 1, "The failure is not retried within the request")

    def test_invalid_address_blocks(self):
        order = self._cart_order()
        with self._patch_carts(side_effect=INVALID) as create_carts:
            self.assertTrue(order._update_cart_taxes_and_prices())
        messages = self._blocking_messages(order)
        self.assertEqual(len(messages), 1, messages)
        self.assertIn('invalid zip', messages[0], "Reported as an address problem, with TaxCloud's details")
        self.assertEqual(create_carts.call_count, 1)

    def test_payment_transaction_blocked(self):
        order = self._cart_order()
        Step = self.env['website.checkout.step']
        with MockRequest(self.env, website=self.website, sale_order_id=order.id):
            with self._patch_carts(side_effect=UNAVAILABLE):
                redirect = Step.validate_checkout_progress('/shop/payment/transaction', order)
            self.assertEqual(redirect, '/shop/payment', "No payment without sales tax")
            self.assertIn('try again in a few minutes', ' '.join(self._blocking_messages(order)))
            self.env.cr.cache.pop('taxcloud_cart_failures', None)  # next request
            order._clear_alerts()
            with self._patch_carts():
                redirect = Step.validate_checkout_progress('/shop/payment/transaction', order)
                self.assertEqual(redirect, '/shop/payment', "Sales tax added: the customer reviews the new total")
                order._clear_alerts()
                self.assertFalse(Step.validate_checkout_progress('/shop/payment/transaction', order))
        self.assertTrue(order.order_line.tax_ids.is_taxcloud)

    def test_payment_transaction_tax_changed(self):
        """ The tax changed after the payment page was shown: the customer must review the new
        total instead of paying the old one. """
        order = self._cart_order()
        Step = self.env['website.checkout.step']
        with MockRequest(self.env, website=self.website, sale_order_id=order.id), self._patch_carts():
            order._update_cart_taxes_and_prices()  # payment page
            order._clear_alerts()
            shown_total = order.amount_total
            order.taxcloud_cart_hash = False  # e.g. new transaction date: TaxCloud is called again
            self.tax_overrides[f'line-{order.order_line.id}'] = {'amount': 10.0, 'rate': 0.1}
            redirect = Step.validate_checkout_progress('/shop/payment/transaction', order)
        self.assertEqual(redirect, '/shop/payment')
        self.assertNotEqual(order.amount_total, shown_total)
        self.assertIn('Prices have changed', ' '.join(alert['message'] for alert in order._get_alerts()))

    # Address and delivery
    # ====================
    def test_address_change_recomputes(self):
        order = self._cart_order()
        other_address = self.partner_us.copy({'street': '2 Other St', 'zip': '98101'})
        with self._patch_carts() as create_carts:
            order._update_cart_taxes_and_prices()
            order.partner_shipping_id = other_address
            order._update_cart_taxes_and_prices()
        self.assertEqual(create_carts.call_count, 2)
        self.assertEqual(self.carts_sent[-1]['carts'][0]['destination']['line1'], '2 Other St')

    def test_delivery_summary_reports_error(self):
        order = self._cart_order()
        with MockRequest(self.env, website=self.website, sale_order_id=order.id), \
                self._patch_carts(side_effect=UNAVAILABLE):
            values = TaxCloudDelivery()._order_summary_values(order)
        self.assertIn('Service Unavailable', values['external_tax_error'])

    def test_checkout_verification_is_silent(self):
        res_partner_module._VERIFY_CACHE.clear()
        self.addCleanup(res_partner_module._VERIFY_CACHE.clear)
        self.company.taxcloud_verify_address = True
        verified = {'line1': '1 MAIN ST', 'city': 'SEATTLE', 'state': 'WA', 'zip': '98104-1234', 'countryCode': 'US'}
        order = self._cart_order()
        with self._patch_carts(), patch.object(TaxCloudClient, 'verify_address', autospec=True, return_value=verified):
            order._update_cart_taxes_and_prices()
        self.assertFalse(self._blocking_messages(order))
        self.assertEqual(self.carts_sent[-1]['carts'][0]['destination']['zip'], '98104-1234')
        self.assertEqual(self.partner_us.zip, '98104', "The customer's address is never changed")
