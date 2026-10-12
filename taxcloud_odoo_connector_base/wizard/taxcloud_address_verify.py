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


class TaxCloudAddressVerify(models.TransientModel):
    _name = 'taxcloud.address.verify'
    _description = "Compare a contact address with TaxCloud's suggestion"

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade')

    street = fields.Char(related='partner_id.street')
    street2 = fields.Char(related='partner_id.street2')
    city = fields.Char(related='partner_id.city')
    state_id = fields.Many2one(related='partner_id.state_id')
    zip = fields.Char(related='partner_id.zip')
    country_id = fields.Many2one(related='partner_id.country_id')

    suggested_street = fields.Char(string="Suggested Street", readonly=True)
    suggested_street2 = fields.Char(string="Suggested Street 2", readonly=True)
    suggested_city = fields.Char(string="Suggested City", readonly=True)
    suggested_state_id = fields.Many2one('res.country.state', string="Suggested State", readonly=True)
    suggested_zip = fields.Char(string="Suggested ZIP", readonly=True)
    suggested_country_id = fields.Many2one('res.country', string="Suggested Country", readonly=True)

    is_already_valid = fields.Boolean(compute='_compute_is_already_valid')

    @api.depends('suggested_street', 'suggested_street2', 'suggested_city', 'suggested_state_id',
                 'suggested_zip', 'suggested_country_id', 'partner_id')
    def _compute_is_already_valid(self):
        for wizard in self:
            wizard.is_already_valid = all(
                (wizard[fname] or False) == (wizard[f'suggested_{fname}'] or False)
                for fname in ('street', 'street2', 'city', 'state_id', 'zip', 'country_id')
            )

    @api.model
    def _prepare_values_from_taxcloud(self, partner, verified):
        """ Map a TaxCloud verify-address response to wizard values. """
        country = self.env['res.country'].search([('code', '=', verified.get('countryCode') or 'US')], limit=1)
        state = self.env['res.country.state'].search([
            ('code', '=', verified.get('state')),
            ('country_id', '=', country.id),
        ], limit=1) if verified.get('state') else self.env['res.country.state']
        return {
            'partner_id': partner.id,
            'suggested_street': verified.get('line1'),
            'suggested_street2': verified.get('line2') or False,
            'suggested_city': verified.get('city'),
            'suggested_state_id': state.id,
            'suggested_zip': verified.get('zip'),
            'suggested_country_id': country.id,
        }

    def action_apply_suggestion(self):
        """ Replace the contact address with the suggestion and mark it as verified. """
        for wizard in self:
            wizard.partner_id.with_context(taxcloud_address_verification=True).write({
                'street': wizard.suggested_street,
                'street2': wizard.suggested_street2,
                'city': wizard.suggested_city,
                'state_id': wizard.suggested_state_id.id,
                'zip': wizard.suggested_zip,
                'country_id': wizard.suggested_country_id.id,
                'taxcloud_address_verified': True,
                'taxcloud_verified_date': fields.Datetime.now(),
            })
        return {'type': 'ir.actions.act_window_close'}
