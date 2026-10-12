import { patch } from "@web/core/utils/patch";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

patch(OrderPaymentValidation.prototype, {
    async isOrderValid(isForceValidate) {
        // No TaxCloud order is paid without sales tax for its current content.
        if (!(await this.pos.computeTaxCloudTaxes(this.order))) {
            return false;
        }
        return super.isOrderValid(...arguments);
    },
});
