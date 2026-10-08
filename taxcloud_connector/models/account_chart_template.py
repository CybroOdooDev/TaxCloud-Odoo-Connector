# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo import models

from odoo.addons.account.models.chart_template import template


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('generic_coa', 'account.fiscal.position')
    def _get_taxcloud_fiscal_position(self):
        """ Added to every company loading the US chart. Never auto-applied: enabling it
        sends all matching documents to TaxCloud, so it is the user's decision. """
        return {
            'account_fiscal_position_taxcloud_us': {
                'name': 'Automatic Tax Mapping (TaxCloud)',
                'is_taxcloud': True,
                'auto_apply': False,
                'country_id': self.env.ref('base.us').id,
                'sequence': 100,
            },
        }
