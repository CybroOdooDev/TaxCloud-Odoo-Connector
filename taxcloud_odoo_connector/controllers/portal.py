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
from odoo.http import route

from odoo.addons.account.controllers.portal import CustomerPortal


class TaxCloudCustomerPortal(CustomerPortal):

    @route()
    def portal_my_invoice_detail(self, *args, **kwargs):
        """ Draft invoices shown to the customer carry up-to-date TaxCloud taxes. """
        response = super().portal_my_invoice_detail(*args, **kwargs)
        invoice = getattr(response, 'qcontext', {}).get('invoice')
        if invoice:
            invoice.with_company(invoice.company_id)._taxcloud_compute_and_set_taxes()
        return response
