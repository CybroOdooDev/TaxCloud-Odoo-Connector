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


class PaymentLinkWizard(models.TransientModel):
    _inherit = 'payment.link.wizard'

    @api.model
    def default_get(self, fields):
        # The customer must pay the amount with TaxCloud taxes, and an invalid address must show
        # up now rather than when the customer opens the link.
        res_model, res_id = self.env.context.get('active_model'), self.env.context.get('active_id')
        if res_model and res_id and hasattr(self.env[res_model], '_taxcloud_compute_and_set_taxes'):
            self.env[res_model].browse(res_id)._taxcloud_compute_and_set_taxes()
        return super().default_get(fields)
