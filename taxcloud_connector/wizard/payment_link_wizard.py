# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
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
