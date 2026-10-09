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
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudError


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'taxcloud.report.mixin']

    taxcloud_report_kind = fields.Selection(
        selection=[('order', "Order"), ('refund', "Refund"), ('credit', "Standalone Credit")],
        compute='_compute_taxcloud_report_kind',
    )
    taxcloud_waiting_for_origin = fields.Boolean(compute='_compute_taxcloud_report_kind')

    @api.depends('move_type', 'taxcloud_sync_state', 'reversed_entry_id.fiscal_position_id', 'reversed_entry_id.taxcloud_sync_state')
    def _compute_taxcloud_report_kind(self):
        for move in self:
            kind = False
            if move.move_type == 'out_invoice':
                kind = 'order'
            elif move.move_type == 'out_refund':
                kind = 'refund' if move.reversed_entry_id.is_taxcloud else 'credit'
            move.taxcloud_report_kind = kind
            move.taxcloud_waiting_for_origin = (
                kind == 'refund'
                and move.taxcloud_sync_state == 'to_sync'
                and move.reversed_entry_id.taxcloud_sync_state != 'synced'
            )

    # Posting / reset to draft
    # ========================
    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        to_report = posted.filtered(lambda move: move._taxcloud_needs_report())
        if to_report:
            to_report._taxcloud_mark_to_report()
        return posted

    def _taxcloud_needs_report(self):
        """ Posted customer documents whose taxes come from TaxCloud and whose destination is in the US. """
        self.ensure_one()
        if not self.is_taxcloud_computed or self._is_downpayment():
            return False
        destination = self._taxcloud_get_destination_partner()
        if destination.country_id and destination.country_id.code != 'US':
            return False
        if self.taxcloud_report_kind == 'refund':
            return self.reversed_entry_id._taxcloud_needs_report()
        return bool(self._taxcloud_get_base_lines())

    def button_draft(self):
        reported = self.filtered(lambda move: move.taxcloud_sync_state == 'synced')
        reported._taxcloud_check_can_void()
        res = super().button_draft()
        # Void after the standard checks passed, so a refused reset does not void the order.
        reported._taxcloud_void()
        self.filtered('taxcloud_sync_state').write({
            'taxcloud_sync_state': False,
            'taxcloud_sync_attempts': 0,
            'taxcloud_sync_error': False,
            'taxcloud_order_id': False,
            'taxcloud_synced_date': False,
        })
        return res

    def _taxcloud_check_can_void(self):
        for move in self:
            if move.taxcloud_report_kind == 'refund':
                raise UserError(self.env._(
                    "%(move)s was reported to TaxCloud as a refund, which cannot be undone. "
                    "Create a new invoice for the returned items instead.",
                    move=move.display_name,
                ))
            refunds = self.search([('reversed_entry_id', '=', move.id), ('taxcloud_sync_state', '=', 'synced')])
            if refunds:
                raise UserError(self.env._(
                    "%(move)s cannot be reset to draft: refunds %(refunds)s were already reported to TaxCloud. "
                    "Use a credit note instead.",
                    move=move.display_name, refunds=", ".join(refunds.mapped('display_name')),
                ))

    def _taxcloud_void(self):
        for move in self:
            client = move.company_id._get_taxcloud_client(res_model=move._name, res_id=move.id)
            try:
                client.void_order(move.taxcloud_order_id)
            except TaxCloudError as e:
                if e.status_code == 404:
                    continue  # nothing to void
                if e.status_code == 422:
                    raise UserError(self.env._(
                        "TaxCloud no longer allows voiding order %(order)s (orders can only be voided until the "
                        "10th of the month after completion). Use a credit note instead.\n\n%(error)s",
                        order=move.taxcloud_order_id, error=str(e),
                    )) from e
                raise UserError(self.env._(
                    "TaxCloud could not void order %(order)s, so %(move)s stays posted: %(error)s",
                    order=move.taxcloud_order_id, move=move.display_name, error=str(e),
                )) from e
            move.message_post(body=self.env._("TaxCloud order %(order)s voided.", order=move.taxcloud_order_id))

    # taxcloud.report.mixin hooks
    # ===========================
    def _taxcloud_get_report_cron(self):
        return self.env.ref('taxcloud_connector.ir_cron_taxcloud_report')

    def _taxcloud_get_report_date(self):
        return self.invoice_date or self.date

    def _taxcloud_get_refund_origin(self):
        return self.reversed_entry_id

    def _taxcloud_get_refund_quantities(self):
        returned = {}
        for base_line in self._taxcloud_get_base_lines():
            line = base_line['record']
            if line.quantity:
                returned[line.taxcloud_item_id] = returned.get(line.taxcloud_item_id, 0.0) + line.quantity
        origin_lines = self.reversed_entry_id.invoice_line_ids
        sold = {line.taxcloud_item_id: line.quantity for line in origin_lines if line.taxcloud_item_id and line.quantity}
        return returned, sold

    def _taxcloud_has_other_reported_refunds(self):
        return bool(self.search_count([
            ('reversed_entry_id', '=', self.reversed_entry_id.id), ('id', '!=', self.id), ('taxcloud_sync_state', '=', 'synced'),
        ], limit=1))

    def _taxcloud_get_refund_idempotency_key(self):
        return f"odoo-{self._taxcloud_get_dbuuid()[:8]}-refund-{self.id}"

    def _taxcloud_get_mismatch_hint(self):
        return self.env._("Reset the invoice to draft, recompute the taxes and post it again.")
