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

TaxCloud Connector - eCommerce
==============================

Computes US sales tax with TaxCloud during the eCommerce checkout and blocks payment when sales
tax cannot be calculated.

Key Features
------------

* Cart taxes are computed on the payment step, before the payment transaction is created, when
  the delivery method changes and at express checkout; tax and total are shown from the payment
  step on.
* One TaxCloud call per cart while the cart, address and date are unchanged.
* No payment without tax: if TaxCloud cannot be reached, a blocking alert asks the customer to
  try again and the payment route validates the cart again.
* Invalid addresses get a blocking address alert with TaxCloud's details.
* Silent address verification at checkout (used for tax only).

Installation
------------
Requires the TaxCloud Connector - Sales module and the eCommerce app. No external dependencies.

Configuration
-------------
Tick Auto-apply (country: United States) on the Automatic Tax Mapping (TaxCloud) fiscal
position so website orders use TaxCloud.

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
