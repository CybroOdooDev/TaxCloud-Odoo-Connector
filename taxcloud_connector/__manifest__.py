# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
{
    'name': 'TaxCloud Connector',
    'version': '20.0.1.0.0',
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
