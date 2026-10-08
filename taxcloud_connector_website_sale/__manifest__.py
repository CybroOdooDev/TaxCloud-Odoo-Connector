# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
{
    'name': 'TaxCloud Connector - eCommerce',
    'version': '20.0.1.0.0',
    'category': 'Website/Website',
    'summary': 'Compute US sales tax with TaxCloud during eCommerce checkout',
    'description': """
Computes TaxCloud taxes during checkout and blocks payment when sales tax cannot be calculated.
    """,
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['taxcloud_connector_sale', 'website_sale'],
    'data': [
        'views/templates.xml',
    ],
    'images': ['static/description/banner.jpg'],
    'license': 'LGPL-3',
    'installable': True,
}
