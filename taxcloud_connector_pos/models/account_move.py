# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo import api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.depends('pos_order_ids', 'reversed_entry_id.pos_order_ids')
    def _compute_is_taxcloud_computed(self):
        # EXTENDS 'taxcloud_connector': an invoice of POS orders keeps the taxes computed for the
        # orders, which are reported to TaxCloud themselves; reporting the invoice too would count
        # the sale twice.
        super()._compute_is_taxcloud_computed()
        self.filtered(lambda move: move.pos_order_ids or move.reversed_entry_id.pos_order_ids).is_taxcloud_computed = False
