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

TaxCloud Connector - Sales
==========================

Computes US sales tax with TaxCloud on quotations and sales orders. Invoices created from an
order keep its TaxCloud fiscal position and delivery address and are reported by the TaxCloud
Connector.

Key Features
------------

* TaxCloud taxes when a quotation is sent or confirmed, when the customer opens it on the portal
  or a payment link, and on demand with the Compute Taxes button.
* Cancelled and locked orders are not recomputed.
* Ship-from is the order's warehouse when Inventory is installed and its address is complete,
  otherwise the company.
* Invoices created from an order are recomputed at the invoice date and reported to TaxCloud;
  sales orders themselves are never reported.

Installation
------------
Requires the TaxCloud Connector module and the Sales app. No external dependencies.

Configuration
-------------
Configure the TaxCloud Connector first. Orders use TaxCloud when their fiscal position is
Automatic Tax Mapping (TaxCloud).

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
