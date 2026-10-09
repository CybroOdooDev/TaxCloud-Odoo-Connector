# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#############################################################################
from unittest import SkipTest

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudError
from odoo.addons.taxcloud_connector.tests.common import TaxCloudInvoiceCommon


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudSale(TaxCloudInvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = cls.env.ref('sales_team.group_sale_manager')
        if stock_manager := cls.env.ref('stock.group_stock_manager', raise_if_not_found=False):
            groups |= stock_manager
        cls.env.user.group_ids |= groups
        (cls.product_shirt | cls.product_book).write({'invoice_policy': 'order'})
        cls.delivery_address = cls.env['res.partner'].create({
            'name': 'US Customer Warehouse', 'type': 'delivery', 'parent_id': cls.partner_us.id,
            'street': '900 Dock St', 'city': 'Tacoma', 'state_id': cls.state_wa.id, 'zip': '98402',
            'country_id': cls.us.id,
        })

    def _order(self, lines, **vals):
        return self.env['sale.order'].create({
            'partner_id': self.partner_us.id,
            'partner_shipping_id': self.delivery_address.id,
            'fiscal_position_id': self.fpos_taxcloud.id,
            'date_order': '2026-09-15 10:00:00',
            'order_line': [Command.create(line) for line in lines],
            **vals,
        })

    def _so_line(self, product, quantity=1.0, **vals):
        return {'product_id': product.id, 'product_uom_qty': quantity, **vals}

    def _cart(self, index=-1):
        return self.carts_sent[index]['carts'][0]

    def test_confirm_computes_taxes(self):
        order = self._order([
            self._so_line(self.product_shirt, quantity=1.5, price_unit=10.75),
            self._so_line(self.product_book, quantity=3.0),
        ])
        self.assertTrue(order.is_taxcloud)
        with self._patch_carts() as create_carts:
            order.action_confirm()
        create_carts.assert_called_once()
        self.assertEqual(order.state, 'sale')

        cart = self._cart()
        dbuuid = self.env['ir.config_parameter'].sudo().get_str('database.uuid')
        self.assertEqual(cart['cartId'], f'odoo-{dbuuid[:8]}-sale.order-{order.id}')
        self.assertEqual(cart['customerId'], str(self.partner_us.id))
        self.assertEqual(cart['destination']['line1'], '900 Dock St', "Shipping address is the destination")
        self.assertEqual(self.carts_sent[-1]['transaction_date'], '2026-09-15T12:00:00Z')
        shirt_line, book_line = order.order_line.sorted('sequence')
        self.assertEqual([item['itemId'] for item in cart['lineItems']], [f'line-{shirt_line.id}', f'line-{book_line.id}'])

        expected = round(16.125 * self.RATE, 2) + round(300.0 * self.RATE, 2)
        self.assertTrue(order.order_line.tax_ids.is_taxcloud)
        self.assertAlmostEqual(order.amount_tax, expected)
        self.assertAlmostEqual(order.taxcloud_tax_amount, expected)

    def test_compute_button_and_cache(self):
        order = self._order([self._so_line(self.product_book)])
        with self._patch_carts() as create_carts:
            order.action_taxcloud_compute_taxes()
            order.action_taxcloud_compute_taxes()
            self.assertEqual(create_carts.call_count, 1)
            order.order_line.product_uom_qty = 2.0
            order.action_taxcloud_compute_taxes()
            self.assertEqual(create_carts.call_count, 2)
            order.action_confirm()
            self.assertEqual(create_carts.call_count, 2, "Confirmation reuses the valid result")
        self.assertAlmostEqual(order.amount_tax, round(200.0 * self.RATE, 2))

    def test_odoo_tax_reset_reuses_result(self):
        """ Odoo recomputes line taxes from the products on many occasions (fiscal position or
        address change, every eCommerce cart refresh): that alone must not call TaxCloud again. """
        order = self._order([self._so_line(self.product_book)])
        with self._patch_carts() as create_carts:
            order.action_taxcloud_compute_taxes()
            order.order_line._compute_tax_ids()  # what sale.order._recompute_taxes() does
            self.assertFalse(order.order_line.tax_ids.is_taxcloud)
            order.action_taxcloud_compute_taxes()
        self.assertEqual(create_carts.call_count, 1)
        self.assertTrue(order.order_line.tax_ids.is_taxcloud)
        self.assertAlmostEqual(order.amount_tax, round(100.0 * self.RATE, 2))

    def test_zero_tax_result_is_cached(self):
        """ A cart TaxCloud taxes at 0 (e.g. no nexus in the destination state) is not sent again. """
        order = self._order([self._so_line(self.product_book)])
        self.tax_overrides[f'line-{order.order_line.id}'] = {'amount': 0.0, 'rate': 0.0}
        with self._patch_carts() as create_carts:
            order.action_taxcloud_compute_taxes()
            order.invalidate_recordset(['taxcloud_cart_result'])  # read back what was stored
            order.action_taxcloud_compute_taxes()
            order.action_confirm()
        self.assertEqual(create_carts.call_count, 1)
        self.assertTrue(order.taxcloud_cart_hash)
        self.assertFalse(order.order_line.tax_ids)
        self.assertFalse(order.amount_tax)

    def test_discounts(self):
        order = self._order([
            self._so_line(self.product_book, quantity=2.0, discount=25.0),
            {'name': 'Loyalty reward', 'product_uom_qty': 1.0, 'price_unit': -10.0,
             'product_id': self.env['product.product'].create({'name': 'Reward', 'type': 'service'}).id},
        ])
        with self._patch_carts():
            order.action_confirm()
        cart = self._cart()
        book_line, reward_line = order.order_line.sorted('sequence')
        self.assertEqual(cart['discounts'], {
            'lineItemDiscounts': [{'itemId': f'line-{book_line.id}', 'cartItemIndex': 0, 'type': 'percentage', 'value': 0.25}],
            'orderDiscount': {'type': 'amount', 'value': 10.0},
        })
        self.assertEqual(cart['lineItems'][0]['price'], 100.0, "Pre-discount unit price")
        self.assertFalse(reward_line.tax_ids)
        self.assertAlmostEqual(order.amount_tax, round((150.0 - 10.0) * self.RATE, 2))

    def test_error_blocks_confirmation(self):
        order = self._order([self._so_line(self.product_book)])
        with self._patch_carts(side_effect=TaxCloudError('Invalid address', 422)), \
                self.assertRaisesRegex(UserError, 'Invalid address'):
            order.action_confirm()
        self.assertEqual(order.state, 'draft')

    def test_not_computed(self):
        plain = self._order([self._so_line(self.product_book)], fiscal_position_id=False)
        cancelled = self._order([self._so_line(self.product_book)])
        cancelled.action_cancel()
        with self._patch_carts() as create_carts:
            plain.action_confirm()
            cancelled.action_taxcloud_compute_taxes()
        create_carts.assert_not_called()

    def test_invoice_from_order(self):
        order = self._order([self._so_line(self.product_book, quantity=2.0)])
        with self._patch_carts():
            order.action_confirm()
            invoice = order._create_invoices()
            self.assertEqual(invoice.fiscal_position_id, self.fpos_taxcloud)
            self.assertEqual(invoice.partner_shipping_id, self.delivery_address)
            invoice.invoice_date = '2026-10-01'
            invoice.action_post()
        cart = self._cart()
        self.assertEqual(cart['cartId'], invoice._taxcloud_get_cart_id(), "The invoice has its own cart")
        self.assertEqual(self.carts_sent[-1]['transaction_date'], '2026-10-01T12:00:00Z', "Rates as of the invoice date")
        self.assertEqual(cart['destination']['line1'], '900 Dock St')
        self.assertAlmostEqual(invoice.amount_tax, order.amount_tax)
        self.assertEqual(invoice.taxcloud_sync_state, 'to_sync')

    def test_origin_is_company_without_warehouse(self):
        order = self._order([self._so_line(self.product_book)])
        with self._patch_carts():
            order.action_taxcloud_compute_taxes()
        self.assertEqual(self._cart()['origin']['line1'], '100 Origin Way')

    def test_origin_is_warehouse(self):
        if 'warehouse_id' not in self.env['sale.order']._fields:
            raise SkipTest("Inventory (sale_stock) is not installed")
        state_or = self.env['res.country.state'].search([('code', '=', 'OR'), ('country_id', '=', self.us.id)])
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        warehouse.partner_id = self.env['res.partner'].create({
            'name': 'Portland DC', 'street': '1 Depot Rd', 'city': 'Portland', 'state_id': state_or.id,
            'zip': '97201', 'country_id': self.us.id,
        })
        self.product_book.is_storable = True
        order = self._order([self._so_line(self.product_book)], warehouse_id=warehouse.id)
        with self._patch_carts():
            order.action_confirm()
            self.assertEqual(self._cart()['origin']['state'], 'OR', "Order ships from its warehouse")
            invoice = order._create_invoices()
            invoice.action_post()
        self.assertEqual(invoice._taxcloud_get_source_warehouses(), warehouse)
        self.assertEqual(self._cart()['origin']['line1'], '1 Depot Rd', "Invoice ships from the stock moves' warehouse")

        warehouse.partner_id.zip = False
        other = self._order([self._so_line(self.product_book)], warehouse_id=warehouse.id)
        with self._patch_carts():
            other.action_taxcloud_compute_taxes()
        self.assertEqual(self._cart()['origin']['line1'], '100 Origin Way', "Incomplete warehouse address: company")
