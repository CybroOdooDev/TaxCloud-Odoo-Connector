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
