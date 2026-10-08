# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _taxcloud_get_origin_partner(self):
        """ Ship-from of an invoice coming from sales orders: the single warehouse the goods left
        from (or the orders' warehouse), when its address is complete; otherwise the company. """
        warehouses = self._taxcloud_get_source_warehouses()
        if warehouses and len(warehouses) == 1:
            partner = warehouses.partner_id
            if partner and not partner._taxcloud_get_missing_address_fields():
                return partner
        return super()._taxcloud_get_origin_partner()

    def _taxcloud_get_source_warehouses(self):
        """ Warehouses of the invoiced sale lines; None when Inventory is not installed. """
        sale_lines = self.invoice_line_ids.sale_line_ids
        if not sale_lines or 'move_ids' not in sale_lines._fields:
            return None
        warehouses = sale_lines.move_ids.filtered(lambda move: move.state != 'cancel').location_id.warehouse_id
        return warehouses or sale_lines.order_id.warehouse_id
