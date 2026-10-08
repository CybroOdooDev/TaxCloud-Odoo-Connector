# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'taxcloud.tax.mixin']

    def action_confirm(self):
        """ Confirmed orders carry TaxCloud taxes. """
        self._taxcloud_compute_and_set_taxes()
        return super().action_confirm()

    def action_quotation_send(self):
        """ The customer receives the quotation with its taxes. """
        self._taxcloud_compute_and_set_taxes()
        return super().action_quotation_send()

    # taxcloud.tax.mixin hooks
    # ========================
    def _taxcloud_filter_eligible(self):
        return super()._taxcloud_filter_eligible().filtered(
            lambda order: order.state in ('draft', 'sent', 'sale') and not order.locked,
        )

    def _taxcloud_get_document_base_lines(self):
        AccountTax = self.env['account.tax']
        order_lines = self.order_line.filtered(lambda line: not line.display_type and not line.is_downpayment)
        base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        return base_lines

    def _taxcloud_get_document_date(self):
        if not self.date_order:
            return super()._taxcloud_get_document_date()
        return fields.Datetime.context_timestamp(self, self.date_order).date()

    def _taxcloud_get_origin_partner(self):
        """ Ship-from: the order's warehouse (Inventory installed) when its address is complete, else the company. """
        warehouse = self['warehouse_id'] if 'warehouse_id' in self._fields else None
        partner = warehouse.partner_id if warehouse else None
        if partner and not partner._taxcloud_get_missing_address_fields():
            return partner
        return super()._taxcloud_get_origin_partner()
