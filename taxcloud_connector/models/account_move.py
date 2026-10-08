# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'taxcloud.tax.mixin']

    @api.depends('fiscal_position_id', 'move_type')
    def _compute_is_taxcloud_computed(self):
        # EXTENDS 'taxcloud.tax.mixin': TaxCloud only applies to customer invoices and credit notes.
        super()._compute_is_taxcloud_computed()
        for move in self.filtered('is_taxcloud_computed'):
            move.is_taxcloud_computed = move.move_type in ('out_invoice', 'out_refund')

    def _post(self, soft=True):
        """ Taxes are always computed again before posting, as of the invoice date. """
        self._taxcloud_compute_and_set_taxes()
        return super()._post(soft=soft)

    # taxcloud.tax.mixin hooks
    # ========================
    def _taxcloud_filter_eligible(self):
        return super()._taxcloud_filter_eligible().filtered(
            lambda move: move.state != 'posted' and not move._is_downpayment(),
        )

    def _taxcloud_get_document_base_lines(self):
        base_lines = self._get_rounded_base_and_tax_lines()[0]
        return [base_line for base_line in base_lines if not base_line['record']._get_downpayment_lines()]

    def _taxcloud_get_document_date(self):
        return self.invoice_date or fields.Date.context_today(self)

    def _taxcloud_get_item_id(self, line):
        """ Invoices own their item IDs; credit notes keep the ones copied from the reversed
        invoice so that refunds can reference the original TaxCloud items. """
        if self.move_type == 'out_refund' and line.taxcloud_item_id:
            return line.taxcloud_item_id
        item_id = f'line-{line.id}'
        if line.taxcloud_item_id != item_id:
            line.taxcloud_item_id = item_id
        return item_id

    def _taxcloud_get_fixed_tax_amounts(self, base_lines):
        """ Credit notes reversing a TaxCloud invoice take their tax from the original lines,
        pro rata of the quantity, like a TaxCloud refund does. No new cart is created. """
        origin = self.reversed_entry_id
        if self.move_type != 'out_refund' or not origin.is_taxcloud:
            return super()._taxcloud_get_fixed_tax_amounts(base_lines)

        origin_lines = {line.taxcloud_item_id: line for line in origin.invoice_line_ids if line.taxcloud_item_id}
        amounts = {}
        for base_line in base_lines:
            line = base_line['record']
            origin_line = origin_lines.get(line.taxcloud_item_id)
            if not origin_line:
                raise UserError(self.env._(
                    "The line '%(line)s' does not come from invoice %(invoice)s. TaxCloud refunds can only "
                    "return items of the original invoice; create a separate document for new items.",
                    line=line.label, invoice=origin.display_name,
                ))
            if (
                self.currency_id.compare_amounts(line.price_unit, origin_line.price_unit)
                or line.discount != origin_line.discount
            ):
                raise UserError(self.env._(
                    "The line '%(line)s' changes the price or discount of invoice %(invoice)s. TaxCloud refunds "
                    "items by quantity only; price adjustments are not supported.",
                    line=line.label, invoice=origin.display_name,
                ))
            if line.quantity > origin_line.quantity:
                raise UserError(self.env._(
                    "The line '%(line)s' returns more than was invoiced on %(invoice)s.",
                    line=line.label, invoice=origin.display_name,
                ))
            origin_amounts = (origin_line.extra_tax_data or {}).get('manual_tax_amounts') or {}
            origin_taxes = origin_line.tax_ids.filtered('is_taxcloud')
            if not origin_amounts or not origin_taxes or not origin_line.quantity:
                continue
            tax = origin_taxes[0]
            origin_amount = origin_amounts.get(str(tax.id), {}).get('tax_amount_currency') or 0.0
            amount = self.currency_id.round(origin_amount * line.quantity / origin_line.quantity)
            if not self.currency_id.is_zero(amount):
                amounts[line] = (tax, amount)
        return amounts


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    taxcloud_item_id = fields.Char(
        string="TaxCloud Item ID",
        copy=True,  # reversal copies it to the credit note line, which is needed for refunds
        readonly=True,
    )
