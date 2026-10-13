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
from odoo import models

from odoo.addons.account.models.chart_template import template


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('generic_coa', 'account.fiscal.position')
    def _get_taxcloud_fiscal_position(self):
        """ Added to every company loading the US chart, before the other US fiscal positions so that
        it wins once auto-applied. Never auto-applied by default: enabling it
        sends all matching documents to TaxCloud, so it is the user's decision. """
        return {
            'account_fiscal_position_taxcloud_us': {
                'name': 'Automatic Tax Mapping (TaxCloud)',
                'is_taxcloud': True,
                'auto_apply': False,
                'country_id': self.env.ref('base.us').id,
                'sequence': 1,
            },
        }
