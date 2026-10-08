# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class AccountFiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'

    is_taxcloud = fields.Boolean(
        string="Use TaxCloud API",
        help="Documents using this fiscal position get their sales tax computed by TaxCloud.",
    )
