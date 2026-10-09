# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, RedirectWarning, UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudClient, TaxCloudError
from .common import FAKE_API_KEY, FAKE_CONNECTION_ID, TaxCloudTestCommon


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudSettings(TaxCloudTestCommon):

    def test_settings_write_through_to_company(self):
        settings = self.env['res.config.settings'].create({
            'taxcloud_connection_id': 'other-connection',
            'taxcloud_default_tic': '10010',
            'taxcloud_verify_address': True,
            'taxcloud_log_retention_days': 7,
        })
        settings.execute()
        self.assertEqual(self.company.taxcloud_connection_id, 'other-connection')
        self.assertEqual(self.company.taxcloud_default_tic, '10010')
        self.assertTrue(self.company.taxcloud_verify_address)
        self.assertEqual(self.company.taxcloud_log_retention_days, 7)

    def test_test_connection_success(self):
        with patch.object(TaxCloudClient, 'ping', autospec=True, return_value={'message': 'Success'}) as ping:
            action = self.env['res.config.settings'].create({}).action_taxcloud_test_connection()
        ping.assert_called_once()
        client = ping.call_args.args[0]
        self.assertEqual(client.connection_id, FAKE_CONNECTION_ID)
        self.assertEqual(client.session.headers['X-API-KEY'], FAKE_API_KEY)
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'success')

    def test_test_connection_failure(self):
        error = TaxCloudError('Connection not found', 404)
        with patch.object(TaxCloudClient, 'ping', autospec=True, side_effect=error), \
                self.assertRaisesRegex(UserError, 'Connection not found'):
            self.env['res.config.settings'].create({}).action_taxcloud_test_connection()

    def test_missing_credentials(self):
        self.company.sudo().taxcloud_api_key = False
        with self.assertRaises(RedirectWarning):
            self.company._get_taxcloud_client()

    def test_credentials_from_parent_company(self):
        branch = self.env['res.company'].create({'name': 'Branch', 'parent_id': self.company.id})
        self.assertEqual(branch._get_taxcloud_credentials_company(), self.company)
        self.assertEqual(branch._get_taxcloud_client().connection_id, FAKE_CONNECTION_ID)

    def test_api_key_restricted_to_system_group(self):
        user = self.env['res.users'].create({
            'name': 'Accountant',
            'login': 'taxcloud_accountant',
            'group_ids': [(6, 0, [self.env.ref('account.group_account_manager').id])],
            'company_id': self.company.id,
            'company_ids': [(6, 0, self.company.ids)],
        })
        self.assertFalse(user.has_group('base.group_system'))
        with self.assertRaises(AccessError):
            self.company.with_user(user).read(['taxcloud_api_key'])
        # The connection ID is not secret and remains readable.
        self.assertEqual(self.company.with_user(user).taxcloud_connection_id, FAKE_CONNECTION_ID)

    def test_fiscal_position_flag(self):
        fpos = self.env['account.fiscal.position'].create({'name': 'TaxCloud', 'is_taxcloud': True})
        self.assertTrue(fpos.is_taxcloud)
        with Form(fpos) as fpos_form:
            fpos_form.is_taxcloud = False
        self.assertFalse(fpos.is_taxcloud)

    def test_tic_resolution_order(self):
        parent = self.env['product.category'].create({'name': 'Parent', 'taxcloud_tic': '20010'})
        child = self.env['product.category'].create({'name': 'Child', 'parent_id': parent.id})
        product = self.env['product.product'].create({'name': 'Thing', 'categ_id': child.id})
        self.company.taxcloud_default_tic = '00000'

        self.assertEqual(product._get_taxcloud_tic(self.company), 20010, "Inherited from the parent category")
        child.taxcloud_tic = '30070'
        self.assertEqual(product._get_taxcloud_tic(self.company), 30070, "Own category wins over parent")
        product.product_tmpl_id.taxcloud_tic = '11010'
        self.assertEqual(product._get_taxcloud_tic(self.company), 11010, "Template wins over category")

        other = self.env['product.product'].create({
            'name': 'Plain', 'categ_id': self.env['product.category'].create({'name': 'Empty'}).id,
        })
        self.assertEqual(other._get_taxcloud_tic(self.company), 0, "Company default (00000 = general goods)")
        self.company.taxcloud_default_tic = False
        self.assertIsNone(other._get_taxcloud_tic(self.company))

    def test_tic_format(self):
        for bad in ('ABC', '123456', '1.5'):
            with self.assertRaises(ValidationError):
                self.env['product.category'].create({'name': 'Bad', 'taxcloud_tic': bad})
        with self.assertRaises(ValidationError):
            self.company.taxcloud_default_tic = 'x'
        with self.assertRaises(ValidationError):
            self.company.taxcloud_log_retention_days = -1

    def test_tic_visible_without_full_accounting(self):
        """ Community billing users lack 'Show Accounting Features', which hides the Accounting tabs:
        the TIC must still be editable on products and categories. """
        billing_user = self.env['res.users'].create({
            'name': 'Billing', 'login': 'taxcloud_billing',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set((self.env.ref('account.group_account_manager') | self.env.ref('product.group_product_manager')).ids)],
        })
        if self.env['ir.module.module']._get('accountant').state != 'installed':
            # Enterprise's Accounting app gives billing administrators the accounting features.
            self.assertFalse(billing_user.has_group('account.group_account_readonly'))
        for model in ('product.template', 'product.category'):
            with Form(self.env[model].with_user(billing_user)) as form:
                form.name = 'TIC test'
                form.taxcloud_tic = '20010'
            self.assertEqual(form.record.taxcloud_tic, '20010', model)
