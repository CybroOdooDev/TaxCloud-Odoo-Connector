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
from odoo.tests import tagged

from .common import TaxCloudInvoiceCommon


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudSalesTaxReport(TaxCloudInvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.state_or = cls.env['res.country.state'].search([('code', '=', 'OR'), ('country_id', '=', cls.us.id)])
        cls.partner_shipped = cls.env['res.partner'].create({
            'name': 'Shipped Customer', 'street': '2 Pine St', 'city': 'Seattle', 'state_id': cls.state_wa.id,
            'zip': '98101', 'country_id': cls.us.id,
        })
        cls.shipping_or = cls.env['res.partner'].create({
            'name': 'Portland warehouse', 'type': 'delivery', 'parent_id': cls.partner_shipped.id,
            'street': '5 River St', 'city': 'Portland', 'state_id': cls.state_or.id, 'zip': '97201',
            'country_id': cls.us.id,
        })

    def _post(self, lines, **vals):
        with self._patch_carts():
            return self._invoice(lines, post=True, **vals)

    def _report(self, moves):
        """ {state code: (sales, taxable, non-taxed, tax)} of the report rows of `moves`. """
        groups = self.env['taxcloud.sales.tax.report']._read_group(
            [('move_id', 'in', moves.ids)],
            ['state_id'],
            ['sales_amount:sum', 'taxable_amount:sum', 'non_taxable_amount:sum', 'tax_amount:sum'],
        )
        return {state.code: tuple(round(amount, 2) for amount in amounts) for state, *amounts in groups}

    def test_invoice_by_destination_state(self):
        invoice = self._post([self._line(self.product_book), self._line(self.product_shirt, quantity=2)])
        self.assertRecordValues(invoice, [{
            'taxcloud_destination_state_id': self.state_wa.id, 'taxcloud_destination_zip': '98104',
        }])
        shipped = self._post([self._line(self.product_book)], partner=self.partner_shipped)
        self.assertEqual(shipped.taxcloud_destination_state_id, self.state_or, "Taxed at the delivery address")

        wa_tax = round(100.0 * self.RATE, 2) + round(21.5 * self.RATE, 2)
        self.assertEqual(self._report(invoice | shipped), {
            'WA': (121.5, 121.5, 0.0, wa_tax),
            'OR': (100.0, 100.0, 0.0, round(100.0 * self.RATE, 2)),
        })
        self.assertAlmostEqual(sum(self._report(invoice).get('WA')[3:]), invoice.amount_tax)

    def test_non_taxed_sales(self):
        invoice = self._invoice([self._line(self.product_book), self._line(self.product_shirt)])
        shirt_line = invoice.invoice_line_ids.filtered(lambda line: line.product_id == self.product_shirt)
        self.tax_overrides = {f'line-{shirt_line.id}': {'amount': 0.0, 'rate': 0.0}}
        with self._patch_carts():
            invoice.action_post()
        self.assertEqual(self._report(invoice)['WA'], (110.75, 100.0, 10.75, round(100.0 * self.RATE, 2)))

    def test_credit_note_is_negative(self):
        invoice = self._post([self._line(self.product_book)])
        credit_note = invoice._reverse_moves([{'invoice_date': '2026-10-05'}])
        with self._patch_carts():
            credit_note.action_post()
        tax = round(100.0 * self.RATE, 2)
        self.assertEqual(self._report(credit_note)['WA'], (-100.0, -100.0, 0.0, -tax))
        self.assertEqual(self._report(invoice | credit_note)['WA'], (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(
            set(self.env['taxcloud.sales.tax.report'].search([('move_id', '=', credit_note.id)]).mapped('document_type')),
            {'refund'},
        )

    def test_only_taxcloud_us_invoices(self):
        draft = self._invoice([self._line(self.product_book)])
        regular = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner_us.id, 'invoice_date': '2026-10-01',
            'invoice_line_ids': [(0, 0, self._line(self.product_book))],
        })
        regular.action_post()
        canada = self.env['res.partner'].create({
            'name': 'Canadian Customer', 'city': 'Toronto', 'country_id': self.env.ref('base.ca').id,
            'state_id': self.env['res.country.state'].search([('code', '=', 'ON')], limit=1).id,
        })
        foreign = self._post([self._line(self.product_book)], partner=canada)
        self.assertFalse(self._report(draft | regular | foreign), "Drafts, non-TaxCloud and non-US sales are left out")

    def test_legacy_invoice_falls_back_to_address(self):
        invoice = self._post([self._line(self.product_book)], partner=self.partner_shipped)
        invoice.write({'taxcloud_destination_state_id': False, 'taxcloud_destination_zip': False})
        self.assertEqual(list(self._report(invoice)), ['OR'])

    def test_open_document(self):
        invoice = self._post([self._line(self.product_book)])
        row = self.env['taxcloud.sales.tax.report'].search([('move_id', '=', invoice.id)])
        self.assertEqual(row.action_open_document()['res_id'], invoice.id)
