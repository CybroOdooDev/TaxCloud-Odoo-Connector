# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
{
    'name': 'TaxCloud Connector - Point of Sale',
    'version': '20.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Compute US sales tax with TaxCloud in the Point of Sale and report paid orders',
    'description': """
Computes TaxCloud taxes when the cashier opens the payment screen of an order whose fiscal
position uses TaxCloud, blocks validation without them, and reports paid orders and refunds
to TaxCloud.
    """,
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['taxcloud_connector', 'point_of_sale'],
    'data': [
        'data/ir_cron_data.xml',
        'views/pos_order_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'taxcloud_connector_pos/static/src/**/*',
        ],
    },
    'images': ['static/description/banner.jpg'],
    'license': 'LGPL-3',
    'installable': True,
}
