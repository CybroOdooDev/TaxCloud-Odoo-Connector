# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from . import services
from . import models
from . import controllers
from . import wizard


def _post_init_hook(env):
    """ Add the TaxCloud fiscal position to companies that already loaded the US chart.
    Companies loading it later get it from account.chart.template. """
    for company in env['res.company'].search([('chart_template', '=', 'generic_coa')], order='parent_path'):
        Template = env['account.chart.template'].with_company(company)
        Template._load_data({'account.fiscal.position': Template._get_taxcloud_fiscal_position()})
