# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo.http import route

from odoo.addons.sale.controllers.portal import CustomerPortal


class TaxCloudCustomerPortal(CustomerPortal):

    @route()
    def portal_order_page(self, *args, **kwargs):
        """ The customer sees the quotation with TaxCloud taxes, and an invalid address shows up
        now rather than when the customer accepts it. """
        response = super().portal_order_page(*args, **kwargs)
        order = getattr(response, 'qcontext', {}).get('sale_order')
        if order:
            order.with_company(order.company_id)._taxcloud_compute_and_set_taxes()
        return response
