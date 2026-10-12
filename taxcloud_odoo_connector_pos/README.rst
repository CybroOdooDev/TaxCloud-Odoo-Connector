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

TaxCloud Connector - Point of Sale
==================================

Computes US sales tax with TaxCloud in the Point of Sale and reports paid orders and refunds to
TaxCloud.

Key Features
------------

* TaxCloud taxes when the cashier opens the payment screen, and again at validation if the
  order changed.
* No payment without tax: if TaxCloud cannot be reached or the POS is offline, an error is shown
  and the order cannot be validated.
* Ship-from is the shop's warehouse (Inventory installed, complete address) or the company;
  ship-to is the shop for counter sales and the customer's delivery address for shipped orders.
* Paid orders are reported by their own background job, with retries, error banners and a Retry
  button.
* Refund orders return the original lines' tax pro rata and are reported as full or partial
  refunds; goods returned without the original order are reported as standalone credits.
* POS orders are included in the Sales Tax by State (TaxCloud) report.
* Invoices of POS orders keep the order's taxes and are not reported twice.

Installation
------------
Requires the TaxCloud Connector module and the Point of Sale app. No external dependencies.

Configuration
-------------
Set Automatic Tax Mapping (TaxCloud) as the default fiscal position of the shop, or on a preset,
in Point of Sale > Configuration > Settings. Only orders with this fiscal position use TaxCloud.

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
