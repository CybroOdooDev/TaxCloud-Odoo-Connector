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
from odoo import fields, models, tools
from odoo.tools import SQL


class TaxCloudSalesTaxReport(models.Model):
    """ Sales and TaxCloud tax by US destination state, one row per document line.

    Amounts are in company currency, negative for refunds. Each source of sales (invoices
    here, POS orders in taxcloud_odoo_connector_pos) is one part of a UNION, see
    `_taxcloud_report_parts`. """
    _name = 'taxcloud.sales.tax.report'
    _description = "TaxCloud Sales Tax Report"
    _auto = False
    _rec_name = 'date'
    _order = 'date desc, id desc'
    _depends = {
        'account.move': [
            'name', 'state', 'move_type', 'invoice_date', 'company_id', 'partner_id', 'partner_shipping_id',
            'fiscal_position_id', 'taxcloud_destination_state_id', 'taxcloud_destination_zip',
        ],
        'account.move.line': ['move_id', 'display_type', 'product_id', 'balance', 'price_subtotal', 'price_total'],
        'account.fiscal.position': ['is_taxcloud'],
        'res.partner': ['state_id', 'zip'],
    }

    source = fields.Selection(selection=[('invoice', "Invoice")], readonly=True)
    document_type = fields.Selection(selection=[('sale', "Sale"), ('refund', "Refund")], readonly=True)
    document_name = fields.Char(string="Document", readonly=True)
    move_id = fields.Many2one('account.move', string="Invoice", readonly=True)
    date = fields.Date(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    state_id = fields.Many2one('res.country.state', string="State", readonly=True)
    zip = fields.Char(string="ZIP", readonly=True)
    sales_amount = fields.Monetary(string="Total Sales", readonly=True)
    taxable_amount = fields.Monetary(string="Taxable Sales", readonly=True)
    non_taxable_amount = fields.Monetary(
        string="Non-Taxed Sales",
        readonly=True,
        help="Sales TaxCloud returned no tax for: exempt customers or non-taxable products.",
    )
    tax_amount = fields.Monetary(string="Sales Tax", readonly=True)
    total_amount = fields.Monetary(string="Total incl. Tax", readonly=True)

    def _taxcloud_report_parts(self):
        """ SELECT queries of the report, one per source of sales. Each one returns the columns
        listed in `_taxcloud_report_select` (missing ones as NULL). """
        return [self._taxcloud_report_select(self._taxcloud_report_invoice_values(), SQL("""
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_fiscal_position fp ON fp.id = am.fiscal_position_id AND fp.is_taxcloud
            JOIN res_company company ON company.id = am.company_id
            LEFT JOIN res_partner shipping ON shipping.id = am.partner_shipping_id
            LEFT JOIN res_partner customer ON customer.id = am.partner_id
            WHERE am.state = 'posted'
              AND am.move_type IN ('out_invoice', 'out_refund')
              AND aml.display_type = 'product'
              AND %s
        """, self._taxcloud_report_invoice_where()))]

    def _taxcloud_report_invoice_values(self):
        # The line tax in company currency, with the sign of the balance (negative for refunds).
        tax = SQL("""COALESCE(
            (aml.price_total - aml.price_subtotal) * -aml.balance / NULLIF(aml.price_subtotal, 0), 0
        )""")
        return {
            'id': SQL("aml.id * 2"),
            'source': SQL("'invoice'"),
            'document_type': SQL("CASE WHEN am.move_type = 'out_refund' THEN 'refund' ELSE 'sale' END"),
            'document_name': SQL("am.name"),
            'move_id': SQL("am.id"),
            'date': SQL("am.invoice_date"),
            'company_id': SQL("am.company_id"),
            'currency_id': SQL("company.currency_id"),
            'partner_id': SQL("am.partner_id"),
            'product_id': SQL("aml.product_id"),
            # Documents taxed before the destination was stored fall back to their address.
            'state_id': SQL("COALESCE(am.taxcloud_destination_state_id, shipping.state_id, customer.state_id)"),
            'zip': SQL("COALESCE(am.taxcloud_destination_zip, shipping.zip, customer.zip)"),
            'sales_amount': SQL("-aml.balance"),
            'taxable_amount': SQL("CASE WHEN %s <> 0 THEN -aml.balance ELSE 0 END", tax),
            'non_taxable_amount': SQL("CASE WHEN %s = 0 THEN -aml.balance ELSE 0 END", tax),
            'tax_amount': tax,
            'total_amount': SQL("-aml.balance + %s", tax),
        }

    def _taxcloud_report_invoice_where(self):
        """ Extra condition on invoices (``am``), e.g. to leave out invoices reported through another document. """
        return SQL("TRUE")

    def _taxcloud_report_select(self, values, from_clause):
        columns = [fname for fname, field in self._fields.items() if field.store and field.column_type]
        return SQL("SELECT %s %s", SQL(", ").join(
            SQL("%s AS %s", values.get(fname, SQL("NULL")), SQL.identifier(fname)) for fname in columns
        ), from_clause)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Only US destinations: TaxCloud computes US sales tax.
        self.env.cr.execute(SQL("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT report.*
                FROM (%s) report
                JOIN res_country_state state ON state.id = report.state_id
                JOIN res_country country ON country.id = state.country_id AND country.code = 'US'
            )
        """, SQL.identifier(self._table), SQL(" UNION ALL ").join(self._taxcloud_report_parts())))

    def action_open_document(self):
        self.ensure_one()
        return self.move_id._get_records_action()
