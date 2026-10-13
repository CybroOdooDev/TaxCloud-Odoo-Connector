.. |license| image:: https://img.shields.io/badge/license-LGPL--3-blue.svg
    :target: http://www.gnu.org/licenses/lgpl-3.0-standalone.html
    :alt: License: LGPL-3

.. |odoo| image:: https://img.shields.io/badge/Odoo-20.0-875A7B.svg
    :target: https://www.odoo.com
    :alt: Odoo 20.0

.. |maintainer| image:: https://img.shields.io/badge/maintainer-Cybrosys-875A7B.svg
    :target: https://cybrosys.com
    :alt: Maintainer: Cybrosys Techno Solutions

|license| |odoo| |maintainer|

TaxCloud Connector
==================

US sales tax for Odoo 20 Community and Enterprise through the TaxCloud API v3. The connector
verifies addresses, computes sales tax on customer invoices and credit notes, and reports
invoices, refunds and credits to TaxCloud. It is the base module of the TaxCloud connector:
install the Sales, eCommerce and Point of Sale bridges for the apps you use.

Key Features
------------

* Per-company TaxCloud settings: API key (administrators only), connection ID, tax template,
  default TIC, address verification, debug logging and log retention, with a Test Connection
  button. Branches use the credentials of their parent company.
* Automatic Tax Mapping (TaxCloud) fiscal position for companies on the US chart of accounts.
* Exact TaxCloud tax per invoice line, with one Odoo tax per TaxCloud rate copied from the tax
  template; no new API call while the cart, address, date and line taxes are unchanged.
* TaxCloud TIC on products and product categories, with a company default.
* Address verification from the contact form with a suggested address and a Verified badge, and
  silent verification (ZIP+4) during tax calculation.
* Exemption certificates referenced on the customer and sent in every cart.
* Reporting of posted invoices as completed TaxCloud orders, of reversals as full or partial
  refunds and of other credit notes as standalone credits, by a background job with retries,
  error banners and a Retry button.
* Reset to draft voids the TaxCloud order.
* Sales Tax by State (TaxCloud) report: taxable sales, non-taxed sales and sales tax by US state,
  ZIP and month, in pivot, graph and list views.
* TaxCloud API log of failed calls (and of every call with debug logging on).
* Works on Odoo Community and Enterprise; multi-company record rules on logs and the report.

Installation
------------
Python library ``requests`` (already an Odoo requirement). No other external dependencies.

Configuration
-------------
* In TaxCloud, create a connection, activate your nexus states and create an API key.
* In Invoicing > Configuration > Settings > Taxes > TaxCloud, enter the API key and connection
  ID, choose the tax template and default TIC, then click Test Connection.
* In Invoicing > Configuration > Fiscal Positions, tick Auto-apply (country: United States) on
  Automatic Tax Mapping (TaxCloud).
* Set a TaxCloud TIC on products or categories, and make sure the company address is complete.

Company
-------
* `Cybrosys Techno Solutions <https://cybrosys.com/>`__

License
-------
Lesser General Public License, Version 3 (LGPL v3).
(http://www.gnu.org/licenses/lgpl-3.0-standalone.html)

Contacts
--------
* Mail Contact : odoo@cybrosys.com
* Website : https://cybrosys.com

Maintainer
==========
.. image:: https://cybrosys.com/images/logo.png
   :target: https://cybrosys.com


This module is maintained by Cybrosys Technologies.

For support and more information, please visit `Our Website <https://cybrosys.com/>`__
