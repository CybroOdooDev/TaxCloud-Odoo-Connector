# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo import models
from odoo.exceptions import UserError

from odoo.addons.taxcloud_connector.models.taxcloud_tax_mixin import TaxCloudUnavailableError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _recompute_taxes(self):
        """ Odoo resets line taxes to the products' taxes here. During a cart refresh or an express
        checkout (context key also set by website_sale), the TaxCloud taxes are set again. """
        super()._recompute_taxes()
        if self.env.context.get('recompute_external_taxes') and not self.env.context.get('taxcloud_skip_computation'):
            self._taxcloud_compute_and_set_taxes()

    def _update_cart_taxes_and_prices(self, **kwargs):
        """ Called on the payment step and before creating a payment transaction. Any TaxCloud error
        becomes a blocking alert, so the payment step and the payment transaction route refuse to
        continue: nobody pays without sales tax. """
        if not self.is_taxcloud_computed:
            return super()._update_cart_taxes_and_prices(**kwargs)
        # The total the customer saw: the computation below changes it before Odoo compares totals.
        initial_amount = self.amount_total
        try:
            # The refresh below resets line taxes and re-applies this result without a second API call.
            self._taxcloud_compute_and_set_taxes()
        except UserError as e:
            # Refresh the rest of the cart without calling TaxCloud again (on Enterprise,
            # website_sale_external_tax would turn the same error into its own alert).
            alerts = self._get_alerts()
            super(SaleOrder, self.with_context(taxcloud_skip_computation=True))._update_cart_taxes_and_prices(**kwargs)
            # The refresh drops the TaxCloud taxes, so Odoo warns that prices changed: the blocking
            # alert below is the actual reason.
            self.alerts = alerts + [alert for alert in self._get_alerts()[len(alerts):] if alert['level'] != 'warning'] or False
            self._add_blocking_alert(self._taxcloud_get_error_message(e))
            return True
        try:
            changed = super(SaleOrder, self.with_context(recompute_external_taxes=True))._update_cart_taxes_and_prices(**kwargs)
        except UserError as e:
            self._add_blocking_alert(self._taxcloud_get_error_message(e))
            return True
        if changed:
            return True
        if self.currency_id.compare_amounts(self.amount_total, initial_amount):
            self._add_warning_alert(self.env._("Prices have changed. Please review your cart."))
            return True
        return False

    def _taxcloud_get_error_message(self, error):
        if isinstance(error, TaxCloudUnavailableError):
            return self._taxcloud_unavailable_message()
        return self.env._(
            "Your address does not appear to be valid. Please make sure it has been filled in correctly."
            "\n\nError details: %(error)s",
            error=str(error),
        )

    def _taxcloud_unavailable_message(self):
        return self.env._(
            "We could not calculate sales tax right now. Please try again in a few minutes.",
        )
