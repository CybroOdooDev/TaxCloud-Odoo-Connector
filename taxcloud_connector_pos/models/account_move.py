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
