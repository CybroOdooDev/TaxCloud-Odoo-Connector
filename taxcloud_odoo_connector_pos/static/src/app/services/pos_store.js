import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(PosStore.prototype, {
    isTaxCloudOrder(order) {
        return Boolean(order?.fiscal_position_id?.is_taxcloud);
    },

    /**
     * What the TaxCloud taxes of an order depend on: when it changes, they are computed again.
     */
    getTaxCloudSignature(order) {
        return JSON.stringify([
            order.partner_id?.id,
            order.preset_id?.id,
            order.fiscal_position_id?.id,
            order.lines.map((line) => [
                line.product_id?.id,
                line.qty,
                line.price_unit,
                line.discount,
                line.refunded_orderline_id?.id,
            ]),
        ]);
    },

    /**
     * Compute the TaxCloud taxes of the order unless they are up to date for its content.
     *
     * @returns {Promise<boolean>} whether the order carries TaxCloud taxes and can be paid
     */
    async computeTaxCloudTaxes(order = this.getOrder()) {
        if (!this.isTaxCloudOrder(order)) {
            return true;
        }
        if (order.uiState.taxcloudSignature === this.getTaxCloudSignature(order)) {
            return true;
        }
        const ui = this.env.services.ui;
        const blockedHere = !ui.isBlocked;
        if (blockedHere) {
            ui.block({ message: _t("Computing sales tax with TaxCloud...") });
        }
        try {
            const data = await this.data.call(
                "pos.order",
                "taxcloud_get_order_tax_details",
                [[order.serializeForORM()]],
                { context: this.getSyncAllOrdersContext([order]) }
            );
            const missingRecords = await this.data.missingRecursive(data);
            this.models.loadConnectedData(missingRecords);
            const syncedOrder = this.models["pos.order"].getBy("uuid", order.uuid) || order;
            syncedOrder.uiState.taxcloudSignature = this.getTaxCloudSignature(syncedOrder);
            return true;
        } catch (error) {
            order.uiState.taxcloudSignature = false;
            this.dialog.add(AlertDialog, {
                title: _t("Sales tax unavailable"),
                body:
                    error?.data?.message ||
                    _t(
                        "TaxCloud could not be reached, so this order cannot be paid yet. Check the connection and try again."
                    ),
            });
            console.error(error);
            return false;
        } finally {
            if (blockedHere) {
                ui.unblock();
            }
        }
    },
});
