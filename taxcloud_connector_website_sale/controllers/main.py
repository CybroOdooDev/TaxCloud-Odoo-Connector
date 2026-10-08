# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo.exceptions import UserError

from odoo.addons.website_sale.controllers import delivery, main


class TaxCloudWebsiteSale(main.WebsiteSale):

    def _get_shop_payment_values(self, order, **kwargs):
        # Taxes and total are shown from the payment step on, once TaxCloud computed them.
        return {**super()._get_shop_payment_values(order, **kwargs), 'on_payment_step': True}


class TaxCloudDelivery(delivery.Delivery):

    def _order_summary_values(self, order, **post):
        """ The delivery method changed: compute the taxes of the new total. """
        res = super()._order_summary_values(order, **post)
        try:
            order._taxcloud_compute_and_set_taxes()
        except UserError as e:
            res['external_tax_error'] = str(e)
        return res
