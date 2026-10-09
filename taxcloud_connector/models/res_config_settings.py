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
from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    taxcloud_api_key = fields.Char(related='company_id.taxcloud_api_key', readonly=False, groups='base.group_system')
    taxcloud_connection_id = fields.Char(related='company_id.taxcloud_connection_id', readonly=False)
    taxcloud_tax_template_id = fields.Many2one(
        related='company_id.taxcloud_tax_template_id',
        readonly=False,
        domain="[('type_tax_use', '=', 'sale'), ('amount_type', '=', 'percent'), ('company_id', 'parent_of', company_id)]",
    )
    taxcloud_default_tic = fields.Char(related='company_id.taxcloud_default_tic', readonly=False)
    taxcloud_verify_address = fields.Boolean(related='company_id.taxcloud_verify_address', readonly=False)
    taxcloud_debug_logging = fields.Boolean(related='company_id.taxcloud_debug_logging', readonly=False)
    taxcloud_log_retention_days = fields.Integer(related='company_id.taxcloud_log_retention_days', readonly=False)

    def action_taxcloud_test_connection(self):
        """ Call TaxCloud's ping endpoint with the saved credentials. """
        self.ensure_one()
        client = self.company_id._get_taxcloud_client()
        try:
            client.ping()
        except TaxCloudError as e:
            raise UserError(self.env._("TaxCloud connection failed: %(error)s", error=str(e))) from e
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': self.env._("TaxCloud"),
                'message': self.env._("Connection successful."),
                'sticky': False,
            },
        }
