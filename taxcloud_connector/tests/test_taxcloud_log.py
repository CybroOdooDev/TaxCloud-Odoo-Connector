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
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudError
from .common import FAKE_API_KEY, FakeResponse, FakeSession, TaxCloudTestCommon


@tagged('post_install', '-at_install', 'taxcloud')
class TestTaxCloudLog(TaxCloudTestCommon):

    def _client(self, *responses, **kwargs):
        client = self.company._get_taxcloud_client(**kwargs)
        client.session = FakeSession(*responses)
        client.session.headers = {'X-API-KEY': FAKE_API_KEY}
        client._sleep = lambda delay: None
        return client

    def _call_expecting_error(self, method, *args):
        """ Odoo's assertRaises rolls back to a savepoint, which would also drop the log
        entries written on the test cursor; catch the error manually instead. """
        try:
            method(*args)
        except TaxCloudError as e:
            return e
        return self.fail("TaxCloudError not raised")

    def _logs(self):
        return self.env['taxcloud.log'].search([('company_id', '=', self.company.id)])

    def test_success_not_logged_without_debug(self):
        self.company.taxcloud_debug_logging = False
        self._client(FakeResponse(200, {'message': 'Success'})).ping()
        self.assertFalse(self._logs())

    def test_success_logged_with_debug(self):
        self.company.taxcloud_debug_logging = True
        self._client(FakeResponse(200, {'items': []}), res_model='account.move', res_id=42).create_carts([{'cartId': 'c1'}])
        log = self._logs()
        self.assertRecordValues(log, [{
            'level': 'info', 'method': 'POST', 'status_code': 200, 'attempt': 1,
            'res_model': 'account.move', 'res_id': 42, 'user_id': self.env.uid,
        }])
        self.assertIn('/carts', log.endpoint)
        self.assertIn('"cartId": "c1"', log.request_body)

    def test_errors_always_logged(self):
        self.company.taxcloud_debug_logging = False
        client = self._client(FakeResponse(503, {'title': 'down'}), FakeResponse(422, {'detail': 'bad zip'}))
        self._call_expecting_error(client.ping)
        logs = self._logs().sorted('id')
        self.assertEqual(logs.mapped('level'), ['error', 'error'])
        self.assertEqual(logs.mapped('status_code'), [503, 422])
        self.assertIn('bad zip', logs[1].error_message)

    def test_api_key_never_logged(self):
        self.company.taxcloud_debug_logging = True
        client = self._client(FakeResponse(200, {}), FakeResponse(400, {'detail': 'nope'}))
        client.ping()
        self._call_expecting_error(client.ping)
        logs = self._logs()
        self.assertEqual(len(logs), 2)
        for log in logs:
            for fname in ('endpoint', 'request_body', 'response_body', 'error_message'):
                self.assertNotIn(FAKE_API_KEY, log[fname] or '')

    def test_body_truncated(self):
        self.company.taxcloud_debug_logging = True
        self._client(FakeResponse(200, text='{"a": "%s"}' % ('x' * 200_000))).ping()
        self.assertEqual(len(self._logs().response_body), 100_000)

    def test_purge_cron(self):
        self.company.taxcloud_log_retention_days = 10
        Log = self.env['taxcloud.log'].sudo()
        old, recent = Log.create([
            {'company_id': self.company.id, 'level': 'info'},
            {'company_id': self.company.id, 'level': 'error'},
        ])
        self.env.cr.execute(
            "UPDATE taxcloud_log SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=11), old.id),
        )
        Log.invalidate_model(['create_date'])
        Log._cron_purge_logs()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_purge_keeps_forever_when_zero(self):
        self.company.taxcloud_log_retention_days = 0
        log = self.env['taxcloud.log'].sudo().create({'company_id': self.company.id, 'level': 'info'})
        self.env.cr.execute("UPDATE taxcloud_log SET create_date = %s WHERE id = %s",
                            (fields.Datetime.now() - timedelta(days=3650), log.id))
        self.env['taxcloud.log']._cron_purge_logs()
        self.assertTrue(log.exists())

    def test_cron_record(self):
        cron = self.env.ref('taxcloud_connector.ir_cron_taxcloud_purge_logs')
        self.assertEqual(cron.model_id.model, 'taxcloud.log')
