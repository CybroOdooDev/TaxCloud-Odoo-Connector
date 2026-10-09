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
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import RedirectWarning, UserError
from odoo.tests import tagged

from odoo.addons.taxcloud_connector import _post_init_hook
from odoo.addons.taxcloud_connector.models import res_partner as res_partner_module
from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudClient, TaxCloudError
from .common import TaxCloudInvoiceCommon


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudInvoice(TaxCloudInvoiceCommon):

    # Eligibility
    # ===========
    def test_is_taxcloud_computed(self):
        invoice = self._invoice([self._line(self.product_book)])
        self.assertTrue(invoice.is_taxcloud)
        self.assertTrue(invoice.is_taxcloud_computed)
        bill = self._invoice([self._line(self.product_book)], move_type='in_invoice')
        self.assertFalse(bill.is_taxcloud_computed, "Vendor bills are not sent to TaxCloud")
        other = self._invoice([self._line(self.product_book)], fiscal_position_id=False)
        self.assertFalse(other.is_taxcloud_computed)

    def test_no_call_without_taxcloud_fiscal_position(self):
        with self._patch_carts() as create_carts:
            self._invoice([self._line(self.product_book)], fiscal_position_id=False, post=True)
        create_carts.assert_not_called()

    # Cart payload
    # ============
    def test_cart_payload(self):
        self.partner_us.with_company(self.company).taxcloud_exemption_id = 'CERT-123'
        invoice = self._invoice([
            self._line(self.product_shirt, quantity=1.5, price_unit=12.0, discount=10.0),
            self._line(self.product_book, quantity=2.0),
        ], invoice_date='2026-01-15')
        with self._patch_carts():
            invoice.action_post()

        self.assertEqual(len(self.carts_sent), 1)
        self.assertEqual(self.carts_sent[0]['transaction_date'], '2026-01-15T12:00:00Z')
        cart = self.carts_sent[0]['carts'][0]
        shirt_line, book_line = invoice.invoice_line_ids.sorted('sequence')
        dbuuid = self.env['ir.config_parameter'].sudo().get_str('database.uuid')
        self.assertEqual(cart['cartId'], f'odoo-{dbuuid[:8]}-account.move-{invoice.id}')
        self.assertEqual(cart['customerId'], str(self.partner_us.id))
        self.assertEqual(cart['currency'], {'currencyCode': 'USD'})
        self.assertEqual(cart['origin'], {
            'line1': '100 Origin Way', 'city': 'Seattle', 'state': 'WA', 'zip': '98101', 'countryCode': 'US',
        })
        self.assertEqual(cart['destination'], {
            'line1': '1 Main St', 'city': 'Seattle', 'state': 'WA', 'zip': '98104', 'countryCode': 'US',
        })
        self.assertEqual(cart['lineItems'], [
            {'index': 0, 'itemId': f'line-{shirt_line.id}', 'price': 12.0, 'quantity': 1.5, 'tic': 20010},
            {'index': 1, 'itemId': f'line-{book_line.id}', 'price': 100.0, 'quantity': 2.0, 'tic': 30070},
        ])
        self.assertEqual(cart['discounts'], {'lineItemDiscounts': [
            {'itemId': f'line-{shirt_line.id}', 'cartItemIndex': 0, 'type': 'percentage', 'value': 0.1},
        ]})
        self.assertEqual(cart['exemption'], {'exemptionId': 'CERT-123'})
        self.assertNotIn('productId', cart['lineItems'][0])
        self.assertEqual(shirt_line.taxcloud_item_id, f'line-{shirt_line.id}')

    def test_default_tic(self):
        product = self.env['product.product'].create({
            'name': 'Plain', 'categ_id': self.env['product.category'].create({'name': 'Plain'}).id,
        })
        self.company.taxcloud_default_tic = '00000'
        with self._patch_carts():
            self._invoice([self._line(product, price_unit=5.0)], post=True)
        self.assertEqual(self.carts_sent[0]['carts'][0]['lineItems'][0]['tic'], 0)

    def test_negative_lines_become_order_discount(self):
        invoice = self._invoice([
            self._line(self.product_book, quantity=1.0),
            {'name': 'Reward', 'quantity': 1.0, 'price_unit': -20.0},
        ])
        with self._patch_carts():
            invoice.action_post()
        cart = self.carts_sent[0]['carts'][0]
        self.assertEqual(len(cart['lineItems']), 1)
        self.assertEqual(cart['discounts'], {'orderDiscount': {'type': 'amount', 'value': 20.0}})
        _book_line, reward_line = invoice.invoice_line_ids.sorted('sequence')
        self.assertFalse(reward_line.tax_ids, "Discount lines carry no tax in Odoo")
        self.assertEqual(invoice.amount_tax, round(80.0 * self.RATE, 2))

    def test_order_discount_only_on_shipping_rejected(self):
        shipping = self.env['product.product'].create({'name': 'Shipping', 'type': 'service', 'taxcloud_tic': '11010'})
        invoice = self._invoice([
            self._line(shipping, price_unit=10.0),
            {'name': 'Coupon', 'quantity': 1.0, 'price_unit': -5.0},
        ])
        with self._patch_carts() as create_carts, self.assertRaisesRegex(UserError, 'shipping or fee'):
            invoice.action_post()
        create_carts.assert_not_called()

    def test_verified_destination_used_in_cart(self):
        res_partner_module._VERIFY_CACHE.clear()
        self.addCleanup(res_partner_module._VERIFY_CACHE.clear)
        self.company.taxcloud_verify_address = True
        verified = {'line1': '1 MAIN ST', 'city': 'SEATTLE', 'state': 'WA', 'zip': '98104-1234', 'countryCode': 'US'}
        with patch.object(TaxCloudClient, 'verify_address', autospec=True, return_value=verified), self._patch_carts():
            self._invoice([self._line(self.product_book)], post=True)
        self.assertEqual(self.carts_sent[0]['carts'][0]['destination'], verified)
        self.assertEqual(self.partner_us.street, '1 Main St', "Partner unchanged")

    # Tax mapping
    # ===========
    def test_tax_mapping_and_totals(self):
        template = self.company_data['default_tax_sale']
        with self._patch_carts():
            invoice = self._invoice([
                self._line(self.product_shirt, quantity=1.5, price_unit=10.75),
                self._line(self.product_book, quantity=3.0),
            ], post=True)
        self.assertEqual(invoice.state, 'posted')
        tax = invoice.invoice_line_ids.tax_ids
        self.assertEqual(len(tax), 1)
        self.assertRecordValues(tax, [{
            'name': 'TaxCloud 8.125%', 'amount': 8.125, 'amount_type': 'percent', 'is_taxcloud': True,
            'type_tax_use': 'sale', 'tax_group_id': template.tax_group_id.id, 'price_include': False,
        }])
        self.assertEqual(
            tax.invoice_repartition_line_ids.mapped('account_id'),
            template.invoice_repartition_line_ids.mapped('account_id'),
        )
        self.assertEqual(self.fpos_taxcloud.map_tax(tax), tax, "Not restricted to the template's fiscal positions")
        expected = round(16.125 * self.RATE, 2) + round(300.0 * self.RATE, 2)
        self.assertAlmostEqual(invoice.amount_tax, expected)
        self.assertAlmostEqual(invoice.taxcloud_tax_amount, expected)

        # Same rate on another invoice: the tax is reused, even when archived.
        tax.active = False
        with self._patch_carts():
            other = self._invoice([self._line(self.product_book)], post=True)
        self.assertEqual(other.invoice_line_ids.tax_ids, tax)
        self.assertTrue(tax.active)

    def test_odoo_total_equals_taxcloud_total(self):
        """ TaxCloud's per-line amount is used as is, even when rate x base rounds differently. """
        invoice = self._invoice([
            self._line(self.product_shirt, quantity=1.5, price_unit=10.75),
            self._line(self.product_book, quantity=1.0, price_unit=0.33),
        ])
        shirt_line, book_line = invoice.invoice_line_ids.sorted('sequence')
        self.tax_overrides = {
            f'line-{shirt_line.id}': {'amount': 1.32, 'rate': self.RATE},   # nominal 1.31
            f'line-{book_line.id}': {'amount': 0.02, 'rate': 0.1025},       # nominal 0.03
        }
        with self._patch_carts():
            invoice.action_post()
        self.assertAlmostEqual(invoice.amount_tax, 1.34)
        self.assertEqual(len(invoice.invoice_line_ids.tax_ids), 2, "One tax per rate")
        self.assertFalse(invoice.message_ids.filtered(lambda m: 'differs from TaxCloud' in (m.body or '')))

    def test_rate_names_unique(self):
        self.env['account.tax'].create({
            'name': 'TaxCloud 8.125%', 'amount': 8.125, 'type_tax_use': 'sale', 'company_id': self.company.id,
            'country_id': self.company_data['default_tax_sale'].country_id.id,
        })
        tax = self.env['account.tax']._taxcloud_get_tax(self.company, 8.125)
        self.assertEqual(tax.name, 'TaxCloud 8.125% (2)')
        self.assertEqual(self.env['account.tax']._taxcloud_get_tax(self.company, 8.12500001), tax, "Rounded to 4 decimals")

    def test_missing_template(self):
        self.company.taxcloud_tax_template_id = False
        with self._patch_carts(), self.assertRaises(RedirectWarning):
            self._invoice([self._line(self.product_book)], post=True)

    def test_zero_tax_line_has_no_tax(self):
        invoice = self._invoice([self._line(self.product_book)])
        self.tax_overrides = {f'line-{invoice.invoice_line_ids.id}': {'amount': 0.0, 'rate': 0.0}}
        with self._patch_carts():
            invoice.action_post()
        self.assertFalse(invoice.invoice_line_ids.tax_ids)
        self.assertEqual(invoice.amount_tax, 0.0)

    # Skips and errors
    # ================
    def test_non_us_destination_skipped(self):
        canada = self.env['res.partner'].create({
            'name': 'CA Customer', 'street': '1 Rue', 'city': 'Montreal', 'zip': 'H2X 1Y4',
            'country_id': self.env.ref('base.ca').id,
        })
        invoice = self._invoice([self._line(self.product_book)], partner=canada)
        with self._patch_carts() as create_carts:
            invoice.action_taxcloud_compute_taxes()
            invoice.action_taxcloud_compute_taxes()
            invoice.action_post()
        create_carts.assert_not_called()
        self.assertFalse(invoice.invoice_line_ids.tax_ids)
        notes = invoice.message_ids.filtered(lambda m: 'outside the United States' in (m.body or ''))
        self.assertEqual(len(notes), 1, "The note is not repeated on every computation")

    def test_unsupported_currency(self):
        eur = self.env.ref('base.EUR')
        eur.active = True
        invoice = self._invoice([self._line(self.product_book)], currency_id=eur.id)
        with self._patch_carts() as create_carts, self.assertRaisesRegex(UserError, 'USD or CAD'):
            invoice.action_post()
        create_carts.assert_not_called()

    def test_incomplete_address(self):
        self.partner_us.zip = False
        invoice = self._invoice([self._line(self.product_book)])
        with self._patch_carts(), self.assertRaisesRegex(UserError, 'Missing: ZIP'):
            invoice.action_post()

    def test_taxcloud_error_blocks_posting(self):
        invoice = self._invoice([self._line(self.product_book)])
        error = TaxCloudError('validation failed', 422, [{'location': 'body.items[0].destination.zip', 'message': 'bad zip'}])
        with self._patch_carts(side_effect=error), self.assertRaisesRegex(UserError, 'bad zip'):
            invoice.action_post()
        self.assertEqual(invoice.state, 'draft')

    # Cache and recomputation
    # =======================
    def test_cache_avoids_repeated_calls(self):
        invoice = self._invoice([self._line(self.product_book)])
        with self._patch_carts() as create_carts:
            invoice.action_taxcloud_compute_taxes()
            invoice.action_taxcloud_compute_taxes()
            self.assertEqual(create_carts.call_count, 1, "Unchanged cart: no second call")

            invoice.invoice_line_ids.quantity = 2.0
            invoice.action_taxcloud_compute_taxes()
            self.assertEqual(create_carts.call_count, 2, "Quantity changed")

            invoice.invoice_date = '2026-10-02'
            invoice.action_taxcloud_compute_taxes()
            self.assertEqual(create_carts.call_count, 3, "Date changed")

            # Taxes reset by Odoo (or changed by hand): the stored result is re-applied, no call.
            invoice.invoice_line_ids.tax_ids = self.company_data['default_tax_sale']
            invoice.action_taxcloud_compute_taxes()
            self.assertEqual(create_carts.call_count, 3, "Same cart: the stored result is re-applied")
            self.assertTrue(invoice.invoice_line_ids.tax_ids.is_taxcloud)

            invoice.action_post()
            self.assertEqual(create_carts.call_count, 3, "Posting reuses the valid result")
        self.assertAlmostEqual(invoice.amount_tax, round(200.0 * self.RATE, 2))

    def test_stored_result_invalid_when_tax_deleted(self):
        invoice = self._invoice([self._line(self.product_book)])
        with self._patch_carts() as create_carts:
            invoice.action_taxcloud_compute_taxes()
            tax = invoice.invoice_line_ids.tax_ids
            invoice.invoice_line_ids.tax_ids = False
            tax.unlink()
            invoice.action_taxcloud_compute_taxes()
        self.assertEqual(create_carts.call_count, 2, "Stored result refers to a deleted tax: computed again")
        self.assertTrue(invoice.invoice_line_ids.tax_ids.is_taxcloud)

    def test_post_uses_invoice_date_when_empty(self):
        invoice = self._invoice([self._line(self.product_book)], invoice_date=False)
        with self._patch_carts():
            invoice.action_post()
        today = fields.Date.context_today(invoice).isoformat()
        self.assertEqual(self.carts_sent[0]['transaction_date'], f'{today}T12:00:00Z')

    # Credit notes
    # ============
    def _posted_invoice(self):
        with self._patch_carts():
            return self._invoice([
                self._line(self.product_shirt, quantity=3.0, price_unit=10.0),
                self._line(self.product_book, quantity=2.0),
            ], post=True)

    def _reverse(self, invoice):
        return invoice._reverse_moves([{'invoice_date': '2026-10-05'}])

    def test_full_reversal_reuses_invoice_tax(self):
        invoice = self._posted_invoice()
        credit_note = self._reverse(invoice)
        self.assertEqual(credit_note.fiscal_position_id, self.fpos_taxcloud)
        with self._patch_carts() as create_carts:
            credit_note.action_post()
        create_carts.assert_not_called()
        self.assertEqual(credit_note.invoice_line_ids.mapped('taxcloud_item_id'), invoice.invoice_line_ids.mapped('taxcloud_item_id'))
        self.assertAlmostEqual(credit_note.amount_tax, invoice.amount_tax)
        self.assertAlmostEqual(credit_note.amount_total, invoice.amount_total)

    def test_partial_reversal_prorata(self):
        invoice = self._posted_invoice()
        credit_note = self._reverse(invoice)
        shirt_line = credit_note.invoice_line_ids.filtered(lambda line: line.product_id == self.product_shirt)
        book_line = credit_note.invoice_line_ids.filtered(lambda line: line.product_id == self.product_book)
        credit_note.write({'invoice_line_ids': [Command.update(shirt_line.id, {'quantity': 1.0}), Command.unlink(book_line.id)]})
        with self._patch_carts() as create_carts:
            credit_note.action_post()
        create_carts.assert_not_called()
        invoice_shirt_tax = round(30.0 * self.RATE, 2)
        self.assertAlmostEqual(credit_note.amount_tax, round(invoice_shirt_tax / 3, 2))

    def test_reversal_rejects_new_line_and_price_change(self):
        invoice = self._posted_invoice()
        credit_note = self._reverse(invoice)
        credit_note.write({'invoice_line_ids': [Command.create(self._line(self.product_book))]})
        with self.assertRaisesRegex(UserError, 'does not come from invoice'):
            credit_note.action_post()

        credit_note = self._reverse(invoice)
        credit_note.invoice_line_ids[0].price_unit = 1.0
        with self.assertRaisesRegex(UserError, 'price adjustments'):
            credit_note.action_post()

        credit_note = self._reverse(invoice)
        credit_note.invoice_line_ids[0].quantity = 10.0
        with self.assertRaisesRegex(UserError, 'returns more'):
            credit_note.action_post()

    def test_standalone_credit_note_computed_with_cart(self):
        with self._patch_carts() as create_carts:
            credit_note = self._invoice([self._line(self.product_book)], move_type='out_refund', post=True)
        create_carts.assert_called_once()
        self.assertAlmostEqual(credit_note.amount_tax, round(100.0 * self.RATE, 2))

    def test_post_init_hook_creates_fiscal_position(self):
        self.assertEqual(self.company.chart_template, 'generic_coa')
        # Module installation runs the hook as superuser.
        _post_init_hook(self.env(su=True))
        _post_init_hook(self.env(su=True))
        fpos = self.env['account.chart.template'].with_company(self.company).ref('account_fiscal_position_taxcloud_us')
        self.assertRecordValues(fpos, [{
            'is_taxcloud': True, 'auto_apply': False, 'country_id': self.us.id, 'company_id': self.company.id,
        }])
        self.assertEqual(
            self.env['account.fiscal.position'].search_count([('company_id', '=', self.company.id), ('name', '=', fpos.name)]),
            1, "Idempotent",
        )
        # Enabling auto-apply is enough: it comes before the chart's other US fiscal positions.
        self.env['account.fiscal.position'].create({
            'name': 'Domestic', 'auto_apply': True, 'country_id': self.us.id, 'company_id': self.company.id, 'sequence': 10,
        })
        fpos.auto_apply = True
        self.assertEqual(self.env['account.fiscal.position'].with_company(self.company)._get_fiscal_position(self.partner_us), fpos)
