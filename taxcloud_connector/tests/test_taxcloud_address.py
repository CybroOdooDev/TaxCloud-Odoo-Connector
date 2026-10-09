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
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.taxcloud_connector.models import res_partner as res_partner_module
from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudClient, TaxCloudError
from .common import TaxCloudTestCommon

VERIFIED = {
    'line1': '1600 Pennsylvania Ave NW',
    'city': 'Washington',
    'state': 'DC',
    'zip': '20500-0003',
    'countryCode': 'US',
}


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudAddress(TaxCloudTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.us = cls.env.ref('base.us')
        cls.dc = cls.env['res.country.state'].search([('code', '=', 'DC'), ('country_id', '=', cls.us.id)])
        cls.partner = cls.env['res.partner'].create({
            'name': 'White House',
            'street': '1600 pennsylvania avenue',
            'city': 'washington',
            'state_id': cls.dc.id,
            'zip': '20500',
            'country_id': cls.us.id,
        })

    def setUp(self):
        super().setUp()
        res_partner_module._VERIFY_CACHE.clear()
        self.addCleanup(res_partner_module._VERIFY_CACHE.clear)

    def _patch_verify(self, **kwargs):
        return patch.object(TaxCloudClient, 'verify_address', autospec=True, **kwargs)

    # Payload
    # =======
    def test_address_payload(self):
        self.partner.street2 = 'Suite 1'
        self.assertEqual(self.partner._taxcloud_get_address_payload(), {
            'line1': '1600 pennsylvania avenue',
            'line2': 'Suite 1',
            'city': 'washington',
            'state': 'DC',
            'zip': '20500',
            'countryCode': 'US',
        })

    # Wizard
    # ======
    def test_wizard_compares_and_applies(self):
        with self._patch_verify(return_value=VERIFIED) as verify:
            action = self.partner.action_taxcloud_verify_address()
        payload = verify.call_args.args[1]
        self.assertEqual(payload['line1'], '1600 pennsylvania avenue')
        self.assertNotIn('line2', payload)

        wizard = self.env['taxcloud.address.verify'].browse(action['res_id'])
        self.assertEqual(action['target'], 'new')
        self.assertFalse(wizard.is_already_valid)
        self.assertRecordValues(wizard, [{
            'street': '1600 pennsylvania avenue',
            'suggested_street': '1600 Pennsylvania Ave NW',
            'suggested_city': 'Washington',
            'suggested_state_id': self.dc.id,
            'suggested_zip': '20500-0003',
            'suggested_country_id': self.us.id,
        }])

        wizard.action_apply_suggestion()
        self.assertRecordValues(self.partner, [{
            'street': '1600 Pennsylvania Ave NW',
            'city': 'Washington',
            'zip': '20500-0003',
            'taxcloud_address_verified': True,
        }])
        self.assertTrue(self.partner.taxcloud_verified_date)

    def test_wizard_already_valid(self):
        self.partner.write({'street': VERIFIED['line1'], 'city': VERIFIED['city'], 'zip': VERIFIED['zip']})
        with self._patch_verify(return_value=VERIFIED):
            action = self.partner.action_taxcloud_verify_address()
        wizard = self.env['taxcloud.address.verify'].browse(action['res_id'])
        self.assertTrue(wizard.is_already_valid)
        wizard.action_apply_suggestion()
        self.assertTrue(self.partner.taxcloud_address_verified)

    def test_wizard_error_is_shown(self):
        with self._patch_verify(side_effect=TaxCloudError('Address not found', 422)), \
                self.assertRaisesRegex(UserError, 'Address not found'):
            self.partner.action_taxcloud_verify_address()

    def test_wizard_rejects_non_us_and_incomplete(self):
        canada = self.partner.copy({'country_id': self.env.ref('base.ca').id, 'state_id': False})
        with self._patch_verify() as verify:
            with self.assertRaisesRegex(UserError, 'United States'):
                canada.action_taxcloud_verify_address()
            with self.assertRaisesRegex(UserError, 'ZIP'):
                self.partner.copy({'zip': False}).action_taxcloud_verify_address()
        verify.assert_not_called()

    # Flag reset
    # ==========
    def test_address_edit_clears_flag(self):
        self.partner.with_context(taxcloud_address_verification=True).write({
            'taxcloud_address_verified': True, 'taxcloud_verified_date': '2026-10-01 10:00:00',
        })
        self.partner.write({'phone': '123', 'zip': '20500'})  # same address value: still verified
        self.assertTrue(self.partner.taxcloud_address_verified)
        self.partner.street2 = 'Room 2'
        self.assertFalse(self.partner.taxcloud_address_verified)
        self.assertFalse(self.partner.taxcloud_verified_date)

    def test_parent_address_sync_clears_child_flag(self):
        company = self.env['res.partner'].create({
            'name': 'ACME', 'is_company': True, 'street': '1 Main St', 'city': 'Washington',
            'state_id': self.dc.id, 'zip': '20001', 'country_id': self.us.id,
        })
        contact = self.env['res.partner'].create({'name': 'Joe', 'parent_id': company.id, 'type': 'contact'})
        (company | contact).with_context(taxcloud_address_verification=True).write({'taxcloud_address_verified': True})
        company.street = '2 Main St'
        self.assertEqual(contact.street, '2 Main St')
        self.assertFalse(contact.taxcloud_address_verified)

    def test_copy_not_verified(self):
        self.partner.with_context(taxcloud_address_verification=True).write({'taxcloud_address_verified': True})
        self.assertFalse(self.partner.copy().taxcloud_address_verified)

    # Address used during tax computation
    # ===================================
    def test_cart_address_setting_off(self):
        self.company.taxcloud_verify_address = False
        with self._patch_verify() as verify:
            address = self.partner._taxcloud_get_cart_address(self.company)
        verify.assert_not_called()
        self.assertEqual(address['line1'], '1600 pennsylvania avenue')

    def test_cart_address_verified_partner_not_reverified(self):
        self.company.taxcloud_verify_address = True
        self.partner.with_context(taxcloud_address_verification=True).write({'taxcloud_address_verified': True})
        with self._patch_verify() as verify:
            self.partner._taxcloud_get_cart_address(self.company)
        verify.assert_not_called()

    def test_cart_address_uses_verification_without_changing_partner(self):
        self.company.taxcloud_verify_address = True
        with self._patch_verify(return_value=VERIFIED) as verify:
            address = self.partner._taxcloud_get_cart_address(self.company)
            self.partner._taxcloud_get_cart_address(self.company)
        self.assertEqual(verify.call_count, 1, "Second call served from the cache")
        self.assertEqual(address, VERIFIED)
        self.assertEqual(self.partner.street, '1600 pennsylvania avenue', "Partner never changed silently")
        self.assertFalse(self.partner.taxcloud_address_verified)

    def test_cart_address_fallback_on_unverifiable(self):
        self.company.taxcloud_verify_address = True
        with self._patch_verify(side_effect=TaxCloudError('Address not found', 422)) as verify:
            address = self.partner._taxcloud_get_cart_address(self.company)
            self.partner._taxcloud_get_cart_address(self.company)
        self.assertEqual(address, self.partner._taxcloud_get_address_payload())
        self.assertEqual(verify.call_count, 1, "Permanent failures are cached")

    def test_cart_address_fallback_on_transient_error(self):
        self.company.taxcloud_verify_address = True
        with self._patch_verify(side_effect=TaxCloudError('Service Unavailable', 503)) as verify:
            address = self.partner._taxcloud_get_cart_address(self.company)
            self.partner._taxcloud_get_cart_address(self.company)
        self.assertEqual(address, self.partner._taxcloud_get_address_payload())
        self.assertEqual(verify.call_count, 2, "Transient failures are retried next time")

    def test_cart_address_incomplete_or_foreign_skips_verification(self):
        self.company.taxcloud_verify_address = True
        incomplete = self.partner.copy({'zip': False})
        foreign = self.partner.copy({'country_id': self.env.ref('base.ca').id, 'state_id': False})
        with self._patch_verify() as verify:
            self.assertEqual(incomplete._taxcloud_get_cart_address(self.company)['zip'], '')
            self.assertEqual(foreign._taxcloud_get_cart_address(self.company)['countryCode'], 'CA')
        verify.assert_not_called()

    def test_cart_address_without_credentials_falls_back(self):
        self.company.taxcloud_verify_address = True
        self.company.sudo().taxcloud_api_key = False
        with self._patch_verify() as verify:
            address = self.partner._taxcloud_get_cart_address(self.company)
        verify.assert_not_called()
        self.assertEqual(address['line1'], '1600 pennsylvania avenue')
