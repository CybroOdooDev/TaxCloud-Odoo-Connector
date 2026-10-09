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
from odoo.exceptions import RedirectWarning, ValidationError
from odoo.http import request

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudClient


class ResCompany(models.Model):
    _inherit = 'res.company'

    taxcloud_api_key = fields.Char(string="TaxCloud API Key", groups='base.group_system', copy=False)
    taxcloud_connection_id = fields.Char(string="TaxCloud Connection ID", copy=False)
    taxcloud_tax_template_id = fields.Many2one(
        comodel_name='account.tax',
        string="TaxCloud Tax Template",
        domain=[('type_tax_use', '=', 'sale'), ('amount_type', '=', 'percent')],
        check_company=True,
        help="Sales tax copied for each new TaxCloud rate, so accounts and tax group come from this tax.",
    )
    taxcloud_default_tic = fields.Char(
        string="Default TIC",
        default='00000',
        help="Taxability Information Code used when neither the product nor its category defines one.",
    )
    taxcloud_verify_address = fields.Boolean(
        string="Verify Addresses During Tax Computation",
        help="Verify unverified destination addresses with TaxCloud before computing taxes. "
             "The verified address is only used for the tax request; the contact is never modified.",
    )
    taxcloud_debug_logging = fields.Boolean(
        string="TaxCloud Debug Logging",
        help="Also log successful TaxCloud calls. Errors are always logged.",
    )
    taxcloud_log_retention_days = fields.Integer(string="TaxCloud Log Retention (Days)", default=30)

    @api.constrains('taxcloud_default_tic')
    def _check_taxcloud_default_tic(self):
        for company in self:
            self.env['product.template']._taxcloud_check_tic_format(company.taxcloud_default_tic)

    @api.constrains('taxcloud_log_retention_days')
    def _check_taxcloud_log_retention_days(self):
        if any(company.taxcloud_log_retention_days < 0 for company in self):
            raise ValidationError(self.env._("The TaxCloud log retention cannot be negative."))

    def _get_taxcloud_credentials_company(self):
        """ Return the company (self or a parent) holding TaxCloud credentials, or an empty recordset. """
        self.ensure_one()
        company = self.sudo()
        while company and not (company.taxcloud_api_key and company.taxcloud_connection_id):
            company = company.parent_id
        return self.browse(company.id)

    def _get_taxcloud_client(self, res_model=None, res_id=None):
        """ Build a TaxCloudClient for this company, logging into taxcloud.log. """
        self.ensure_one()
        credentials_company = self._get_taxcloud_credentials_company()
        if not credentials_company:
            raise RedirectWarning(
                self.env._("Please configure your TaxCloud API key and connection ID for %(company)s.",
                           company=self.display_name),
                self.env.ref('account.action_account_config').id,
                self.env._("Go to the settings"),
            )
        credentials_company = credentials_company.sudo()
        # Someone is waiting on an HTTP request (checkout, form button): fail fast. Crons keep the
        # default, more patient settings.
        interactive = {'timeout': 10, 'max_retries': 1} if request else {}
        return TaxCloudClient(
            credentials_company.taxcloud_api_key,
            credentials_company.taxcloud_connection_id,
            log_hook=self.env['taxcloud.log']._get_log_hook(self, res_model=res_model, res_id=res_id),
            **interactive,
        )
