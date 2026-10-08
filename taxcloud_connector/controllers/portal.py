# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
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
