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
import logging
import time

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudError

_logger = logging.getLogger(__name__)

TAXCLOUD_ADDRESS_FIELDS = ('street', 'street2', 'city', 'state_id', 'zip', 'country_id')

# In-process cache of verify-address results used during tax computation, so an
# unverified partner does not cost one extra API call per computation.
# {(connection_id, address tuple): (expiry timestamp, verified address dict or None)}
_VERIFY_CACHE = {}
_VERIFY_CACHE_TTL = 24 * 3600
_VERIFY_CACHE_MAX_SIZE = 1024


class ResPartner(models.Model):
    _inherit = 'res.partner'

    taxcloud_address_verified = fields.Boolean(
        string="Address Verified by TaxCloud",
        copy=False,
        help="Set when the TaxCloud suggested address was applied. Cleared on any address change.",
    )
    taxcloud_verified_date = fields.Datetime(string="TaxCloud Verification Date", copy=False, readonly=True)
    taxcloud_show_address_verification = fields.Boolean(compute='_compute_taxcloud_show_address_verification')
    taxcloud_exemption_id = fields.Char(
        string="TaxCloud Exemption Certificate",
        company_dependent=True,
        help="ID of an exemption certificate created in TaxCloud for this customer. "
             "It is referenced in every cart of this customer.",
    )

    @api.depends('street', 'country_id')
    def _compute_taxcloud_show_address_verification(self):
        for partner in self:
            partner.taxcloud_show_address_verification = bool(partner.street) and partner.country_id.code in ('US', False)

    def write(self, vals):
        return self._taxcloud_write_and_reset_verification(vals, super().write)

    def _update_address(self, vals):
        # The base implementation writes child contacts with BaseModel.write, bypassing write() above.
        return self._taxcloud_write_and_reset_verification(vals, super()._update_address)

    def _taxcloud_write_and_reset_verification(self, vals, write_method):
        """ Call `write_method(vals)` and clear the verified flag of partners whose address really changed. """
        if self.env.context.get('taxcloud_address_verification') or not any(f in vals for f in TAXCLOUD_ADDRESS_FIELDS):
            return write_method(vals)
        before = {partner.id: partner._taxcloud_address_key() for partner in self}
        res = write_method(vals)
        changed = self.filtered(lambda p: p.taxcloud_address_verified and p._taxcloud_address_key() != before[p.id])
        if changed:
            changed.with_context(taxcloud_address_verification=True).write({
                'taxcloud_address_verified': False,
                'taxcloud_verified_date': False,
            })
        return res

    def _taxcloud_address_key(self):
        self.ensure_one()
        return tuple(self[fname].id if fname.endswith('_id') else (self[fname] or '') for fname in TAXCLOUD_ADDRESS_FIELDS)

    # TaxCloud payloads
    # =================
    def _taxcloud_get_address_payload(self):
        """ Return the TaxCloud Address dict ``{line1, line2?, city, state, zip, countryCode}``. """
        self.ensure_one()
        payload = {
            'line1': self.street or '',
            'city': self.city or '',
            'state': self.state_id.code or '',
            'zip': (self.zip or '').strip(),
            'countryCode': self.country_id.code or 'US',
        }
        if self.street2:
            payload['line2'] = self.street2
        return payload

    def _taxcloud_get_missing_address_fields(self):
        self.ensure_one()
        labels = {'street': self.env._("Street"), 'city': self.env._("City"), 'state_id': self.env._("State"), 'zip': self.env._("ZIP")}
        return [label for fname, label in labels.items() if not self[fname]]

    def _taxcloud_verify_address(self, company=None):
        """ Call TaxCloud's verify-address for this partner (US only).

        :returns: the verified TaxCloud address dict.
        :raises UserError: for non-US or incomplete addresses.
        :raises TaxCloudError: when TaxCloud cannot verify the address or is unreachable.
        """
        self.ensure_one()
        if self.country_id and self.country_id.code != 'US':
            raise UserError(self.env._("TaxCloud only verifies addresses in the United States."))
        if missing := self._taxcloud_get_missing_address_fields():
            raise UserError(self.env._(
                "The address of %(partner)s is incomplete. Missing: %(fields)s",
                partner=self.display_name, fields=", ".join(missing),
            ))
        company = company or self.company_id or self.env.company
        client = company._get_taxcloud_client(res_model=self._name, res_id=self.id)
        return client.verify_address(self._taxcloud_get_address_payload())

    def _taxcloud_get_cart_address(self, company):
        """ Address to send in a cart. Never modifies the partner and never raises for
        verification problems: if verification fails, the address as entered is used.

        Verification is attempted only when the company enables it, the partner is not
        already verified and the address is a complete US address.
        """
        self.ensure_one()
        payload = self._taxcloud_get_address_payload()
        credentials_company = company._get_taxcloud_credentials_company()
        if (
            not company.taxcloud_verify_address
            or not credentials_company
            or self.taxcloud_address_verified
            or payload['countryCode'] != 'US'
            or self._taxcloud_get_missing_address_fields()
        ):
            return payload

        cache_key = (credentials_company.sudo().taxcloud_connection_id, tuple(sorted(payload.items())))
        now = time.monotonic()
        cached = _VERIFY_CACHE.get(cache_key)
        if cached and cached[0] > now:
            verified = cached[1]
        else:
            try:
                verified = self._taxcloud_verify_address(company)
            except (TaxCloudError, UserError) as e:
                _logger.info("TaxCloud could not verify the address of partner %s, using it as entered: %s", self.id, e)
                if isinstance(e, TaxCloudError) and e.is_retryable:
                    return payload  # transient: try again next time
                verified = None
            if len(_VERIFY_CACHE) >= _VERIFY_CACHE_MAX_SIZE:
                _VERIFY_CACHE.clear()
            _VERIFY_CACHE[cache_key] = (now + _VERIFY_CACHE_TTL, verified)

        if not verified:
            return payload
        result = {key: verified.get(key) or payload.get(key) for key in ('line1', 'city', 'state', 'zip', 'countryCode')}
        if verified.get('line2'):
            result['line2'] = verified['line2']
        return result

    # Actions
    # =======
    def action_taxcloud_verify_address(self):
        """ Open the comparison wizard with TaxCloud's suggested address. """
        self.ensure_one()
        try:
            verified = self._taxcloud_verify_address()
        except TaxCloudError as e:
            raise UserError(self.env._(
                "TaxCloud could not verify the address of %(partner)s: %(error)s",
                partner=self.display_name, error=str(e),
            )) from e
        wizard = self.env['taxcloud.address.verify'].create(
            self.env['taxcloud.address.verify']._prepare_values_from_taxcloud(self, verified),
        )
        return {
            'name': self.env._("Verify Address of %(partner)s", partner=self.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'taxcloud.address.verify',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }
