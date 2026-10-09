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
{
    'name': 'TaxCloud Connector',
    'version': '20.0.1.0.1',
    'category': 'Accounting/Accounting',
    'summary': 'US sales tax calculation, address verification and reporting with TaxCloud',
    'description': """
TaxCloud Connector
==================
Computes US sales tax with the TaxCloud API v3, verifies addresses and reports invoices
and refunds to TaxCloud. Works on Odoo Community and Enterprise.
    """,
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['account', 'payment'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.access.csv',
        'data/ir_cron_data.xml',
        'views/taxcloud_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/account_fiscal_position_views.xml',
        'views/product_views.xml',
        'views/res_partner_views.xml',
        'views/account_move_views.xml',
        'wizard/taxcloud_address_verify_views.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'images': ['static/description/banner.jpg'],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
