    # Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
{
    'name': 'TaxCloud Connector - Sales',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Compute US sales tax with TaxCloud on quotations and sales orders',
    'description': """
Computes TaxCloud taxes on quotations and sales orders (when sent, confirmed, shown on the portal
or on demand).
Ship-from is the order's warehouse when Inventory is installed, otherwise the company.
    """,
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['taxcloud_connector', 'sale_management'],
    'data': [
        'views/sale_order_views.xml',
    ],
    'images': ['static/description/banner.jpg'],
    'license': 'LGPL-3',
    'installable': True,
}
