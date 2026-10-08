# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from odoo import Command, api, fields, models
from odoo.exceptions import RedirectWarning
from odoo.tools import float_round


class AccountTax(models.Model):
    _inherit = 'account.tax'

    is_taxcloud = fields.Boolean(
        string="TaxCloud Tax",
        copy=False,
        readonly=True,
        help="Created by the TaxCloud connector for one TaxCloud rate.",
    )

    @api.model
    def _taxcloud_get_tax(self, company, rate_percent):
        """ Return the TaxCloud sales tax for `rate_percent` (e.g. 8.125), creating it if needed.

        An existing TaxCloud tax with the same rate (rounded to 4 decimals) is reused and
        unarchived if needed. A new one is a copy of the company's TaxCloud tax template so its
        accounts and tax group come from the configuration.
        """
        rate = float_round(rate_percent, precision_digits=4)
        tax = self.with_context(active_test=False).search([
            *self._check_company_domain(company),
            ('is_taxcloud', '=', True),
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', rate),
        ], limit=1)
        if tax:
            if not tax.active:
                tax.sudo().active = True
            if tax.fiscal_position_ids:
                tax.sudo().fiscal_position_ids = [Command.clear()]
            return tax

        template = company.taxcloud_tax_template_id or company._get_taxcloud_credentials_company().taxcloud_tax_template_id
        if not template:
            raise RedirectWarning(
                self.env._("Please set the TaxCloud tax template of %(company)s.", company=company.display_name),
                self.env.ref('account.action_account_config').id,
                self.env._("Go to the settings"),
            )
        name = self._taxcloud_get_unique_tax_name(template, rate)
        return template.sudo().copy({
            'name': name,
            'invoice_label': name,
            'amount': rate,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'price_include_override': 'tax_excluded',
            'include_base_amount': False,
            'is_taxcloud': True,
            'active': True,
            # Kept by every fiscal position: fiscal_position_ids copied from the template would make
            # map_tax() drop the tax, e.g. in the Point of Sale.
            'fiscal_position_ids': [Command.clear()],
        }).sudo(False)

    @api.model
    def _taxcloud_get_unique_tax_name(self, template, rate):
        base_name = "TaxCloud %s%%" % ('%.4f' % rate).rstrip('0').rstrip('.')
        existing = set(self.with_context(active_test=False).search([
            ('company_id', 'child_of', template.company_id.root_id.id),
            ('name', '=like', f'{base_name}%'),
        ]).mapped('name'))
        name, counter = base_name, 1
        while name in existing:
            counter += 1
            name = f"{base_name} ({counter})"
        return name

    def _prepare_base_line_tax_repartition_grouping_key(self, base_line, base_line_grouping_key, tax_data, tax_rep_data):
        """ Keep the tax line of a TaxCloud invoice even when Odoo expects it to be zero: TaxCloud
        may return an amount for it. """
        res = super()._prepare_base_line_tax_repartition_grouping_key(base_line, base_line_grouping_key, tax_data, tax_rep_data)
        record = base_line['record']
        if isinstance(record, models.Model) and record._name == 'account.move.line' and record.move_id.is_taxcloud_computed:
            res['__keep_zero_line'] = True
        return res
