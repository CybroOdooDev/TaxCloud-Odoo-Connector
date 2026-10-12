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
from odoo import fields, models
from odoo.tools import SQL


class TaxCloudSalesTaxReport(models.Model):
    _inherit = 'taxcloud.sales.tax.report'
    _depends = {
        'pos.order': [
            'name', 'pos_reference', 'state', 'date_order', 'company_id', 'partner_id', 'fiscal_position_id',
            'currency_rate', 'amount_total', 'account_move', 'taxcloud_destination_state_id',
            'taxcloud_destination_zip',
        ],
        'pos.order.line': ['order_id', 'product_id', 'qty', 'price_subtotal', 'price_subtotal_incl'],
    }

    source = fields.Selection(selection_add=[('pos', "Point of Sale")])
    pos_order_id = fields.Many2one('pos.order', string="POS Order", readonly=True)

    def _taxcloud_report_parts(self):
        return super()._taxcloud_report_parts() + [self._taxcloud_report_select(self._taxcloud_report_pos_values(), SQL("""
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN account_fiscal_position fp ON fp.id = po.fiscal_position_id AND fp.is_taxcloud
            JOIN res_company company ON company.id = po.company_id
            JOIN res_partner company_partner ON company_partner.id = company.partner_id
            WHERE po.state IN ('paid', 'done', 'invoiced')
        """))]

    def _taxcloud_report_pos_values(self):
        rate = SQL("CASE COALESCE(po.currency_rate, 0) WHEN 0 THEN 1.0 ELSE po.currency_rate END")
        # POS line prices are always positive: returned quantities are negative.
        sign = SQL("CASE WHEN pol.qty < 0 THEN -1 ELSE 1 END")
        sales = SQL("%s * ABS(pol.price_subtotal) / %s", sign, rate)
        tax = SQL("%s * (ABS(pol.price_subtotal_incl) - ABS(pol.price_subtotal)) / %s", sign, rate)
        return {
            'id': SQL("pol.id * 2 + 1"),
            'source': SQL("'pos'"),
            'document_type': SQL("CASE WHEN po.amount_total < 0 THEN 'refund' ELSE 'sale' END"),
            'document_name': SQL("COALESCE(po.pos_reference, po.name)"),
            'pos_order_id': SQL("po.id"),
            'date': SQL("(po.date_order AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(company_partner.tz, 'UTC'))::date"),
            'company_id': SQL("po.company_id"),
            'currency_id': SQL("company.currency_id"),
            'partner_id': SQL("po.partner_id"),
            'product_id': SQL("pol.product_id"),
            # Orders taxed before the destination was stored fall back to the company address.
            'state_id': SQL("COALESCE(po.taxcloud_destination_state_id, company_partner.state_id)"),
            'zip': SQL("COALESCE(po.taxcloud_destination_zip, company_partner.zip)"),
            'sales_amount': sales,
            'taxable_amount': SQL("CASE WHEN %s <> 0 THEN %s ELSE 0 END", tax, sales),
            'non_taxable_amount': SQL("CASE WHEN %s = 0 THEN %s ELSE 0 END", tax, sales),
            'tax_amount': tax,
            'total_amount': SQL("%s + %s", sales, tax),
        }

    def _taxcloud_report_invoice_where(self):
        # EXTENDS 'taxcloud_odoo_connector_base': an invoice of POS orders is counted with the orders.
        return SQL("%s AND NOT EXISTS (%s)", super()._taxcloud_report_invoice_where(), SQL("""
            SELECT 1 FROM pos_order
            WHERE pos_order.account_move IN (am.id, am.reversed_entry_id)
        """))

    def action_open_document(self):
        self.ensure_one()
        if self.pos_order_id:
            return self.pos_order_id._get_records_action()
        return super().action_open_document()
