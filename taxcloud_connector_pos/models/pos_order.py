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
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.taxcloud_connector.models.taxcloud_tax_mixin import TaxCloudUnavailableError


class PosOrder(models.Model):
    _name = 'pos.order'
    _inherit = ['pos.order', 'taxcloud.tax.mixin', 'taxcloud.report.mixin']

    taxcloud_report_kind = fields.Selection(
        selection=[('order', "Order"), ('refund', "Refund"), ('credit', "Standalone Credit")],
        compute='_compute_taxcloud_report_kind',
    )
    taxcloud_waiting_for_origin = fields.Boolean(compute='_compute_taxcloud_report_kind')

    @api.depends('lines.qty', 'lines.refunded_orderline_id.order_id.taxcloud_sync_state', 'taxcloud_sync_state')
    def _compute_taxcloud_report_kind(self):
        for order in self:
            if order.lines.refunded_orderline_id:
                kind = 'refund'
            elif order.is_refund_or_negative():
                kind = 'credit'  # goods returned without the original order
            else:
                kind = 'order'
            order.taxcloud_report_kind = kind
            order.taxcloud_waiting_for_origin = (
                kind == 'refund'
                and order.taxcloud_sync_state == 'to_sync'
                and order.refunded_order_id.taxcloud_sync_state != 'synced'
            )

    # Point of Sale
    # =============
    @api.model
    def taxcloud_get_order_tax_details(self, orders):
        """ Called by the POS on the payment screen: save the draft order, compute its TaxCloud
        taxes and return the records the POS must reload (lines, and taxes created for new rates). """
        res = self.sync_from_ui(orders)
        orders = self.browse([order['id'] for order in res['pos.order']]).filtered(lambda order: order.state == 'draft')
        results = {**res, 'pos.order': [], 'pos.order.line': [], 'account.tax': [], 'account.tax.group': []}
        for order in orders:
            try:
                order.action_taxcloud_compute_taxes()
            except TaxCloudUnavailableError:
                # The technical cause is in the TaxCloud logs; the cashier only needs to know what to do.
                raise UserError(self.env._(
                    "TaxCloud could not be reached, so this order cannot be paid yet. Check the connection and try again.",
                ))
            config = order.config_id
            taxes = order.lines.tax_ids
            results['account.tax'] += self.env['account.tax']._load_pos_data_read(taxes, config)
            results['account.tax.group'] += self.env['account.tax.group']._load_pos_data_read(taxes.tax_group_id, config)
            results['pos.order'] += self._load_pos_data_read(order, config)
            results['pos.order.line'] += self.env['pos.order.line']._load_pos_data_read(order.lines, config)
        return results

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        if self._taxcloud_needs_report():
            self._taxcloud_mark_to_report()
        return res

    def _taxcloud_needs_report(self):
        """ Paid orders whose taxes come from TaxCloud and whose destination is in the US. """
        self.ensure_one()
        if not self.is_taxcloud_computed:
            return False
        destination = self._taxcloud_get_destination_partner()
        if destination.country_id and destination.country_id.code != 'US':
            return False
        if self.taxcloud_report_kind == 'refund':
            return self.refunded_order_id._taxcloud_needs_report()
        return bool(self._taxcloud_get_base_lines())

    # taxcloud.tax.mixin hooks
    # ========================
    def _taxcloud_filter_eligible(self):
        return super()._taxcloud_filter_eligible().filtered(lambda order: order.state == 'draft')

    def _taxcloud_get_document_base_lines(self):
        AccountTax = self.env['account.tax']
        base_lines = self.lines._prepare_base_lines_for_taxes_computation()
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        return base_lines

    def _taxcloud_get_document_date(self):
        return fields.Datetime.context_timestamp(self, self.date_order).date()

    def _taxcloud_get_origin_partner(self):
        """ Ship-from: the shop's warehouse (Inventory installed) when its address is complete, else the company. """
        config = self.config_id
        warehouse = config.picking_type_id.warehouse_id if 'picking_type_id' in config._fields else None
        partner = warehouse.partner_id if warehouse else None
        if partner and not partner._taxcloud_get_missing_address_fields():
            return partner
        return super()._taxcloud_get_origin_partner()

    def _taxcloud_get_destination_partner(self):
        """ The customer takes the goods at the counter, so the sale happens at the shop; delivered
        or ship-later orders are taxed at the customer's delivery address. """
        if self.partner_id and self._taxcloud_is_delivered():
            return self.env['res.partner'].browse(self.partner_id.address_get(['delivery'])['delivery'])
        return self._taxcloud_get_origin_partner()

    def _taxcloud_is_delivered(self):
        is_shipped_later = 'shipping_date' in self._fields and self.shipping_date
        return bool(self.preset_id.identification == 'address' or is_shipped_later)

    def _taxcloud_get_document_name(self):
        """ Draft orders are named "/" until paid: use the receipt number. """
        return self.pos_reference or self.display_name

    def _taxcloud_refresh_amounts(self):
        """ amount_tax and amount_total are stored values set by the POS, not computed fields. """
        self._compute_prices()

    def _taxcloud_get_fixed_tax_amounts(self, base_lines):
        """ A refund returns the tax of the original lines, pro rata of the quantity, like a TaxCloud
        refund does. No new cart is created. """
        refund_lines = self.lines.filtered('refunded_orderline_id')
        origin = self.refunded_order_id
        if not refund_lines or not origin.is_taxcloud:
            return super()._taxcloud_get_fixed_tax_amounts(base_lines)
        if any(line.qty and not line.refunded_orderline_id for line in self.lines):
            raise UserError(self.env._(
                "A TaxCloud refund can only return items of %(order)s. Ring up new items in a separate order.",
                order=origin.display_name,
            ))
        amounts = {}
        for base_line in base_lines:
            line = base_line['record']
            origin_line = line.refunded_orderline_id
            origin_amounts = (origin_line.extra_tax_data or {}).get('manual_tax_amounts') or {}
            origin_taxes = origin_line.tax_ids.filtered('is_taxcloud')
            if not origin_amounts or not origin_taxes or not origin_line.qty:
                continue
            tax = origin_taxes[0]
            origin_amount = origin_amounts.get(str(tax.id), {}).get('tax_amount_currency') or 0.0
            amount = self.currency_id.round(origin_amount * abs(line.qty) / abs(origin_line.qty))
            if not self.currency_id.is_zero(amount):
                amounts[line] = (tax, amount)
        return amounts

    # taxcloud.report.mixin hooks
    # ===========================
    def _taxcloud_get_report_cron(self):
        return self.env.ref('taxcloud_connector_pos.ir_cron_taxcloud_report_pos')

    def _taxcloud_get_report_reference(self):
        return self.pos_reference or self.name

    def _taxcloud_get_report_date(self):
        return self._taxcloud_get_document_date()

    def _taxcloud_get_refund_origin(self):
        return self.refunded_order_id

    def _taxcloud_get_refund_quantities(self):
        """ Quantities by item ID: the original order's items are its cart items, so discount lines are left out. """
        cart, _line_by_index = self.refunded_order_id._taxcloud_build_posted_cart()
        sold = {item['itemId']: item['quantity'] for item in cart['lineItems']}
        returned = {}
        for line in self.lines:
            item_id = self._taxcloud_get_item_id(line.refunded_orderline_id)
            if line.qty and item_id in sold:
                returned[item_id] = returned.get(item_id, 0.0) + abs(line.qty)
        return returned, sold

    def _taxcloud_has_other_reported_refunds(self):
        return bool(self.search_count([
            ('lines.refunded_orderline_id.order_id', '=', self.refunded_order_id.id),
            ('id', '!=', self.id),
            ('taxcloud_sync_state', '=', 'synced'),
        ], limit=1))

    def _taxcloud_get_mismatch_hint(self):
        return self.env._("Check the TaxCloud configuration, then retry the report from the order.")
