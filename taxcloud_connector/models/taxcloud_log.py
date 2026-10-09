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
import json
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.modules import module

_logger = logging.getLogger(__name__)

MAX_BODY_LENGTH = 100_000
PURGE_BATCH_SIZE = 1000


class TaxCloudLog(models.Model):
    _name = 'taxcloud.log'
    _description = "TaxCloud API Log"
    _order = 'id desc'
    _rec_name = 'endpoint'

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', readonly=True, ondelete='set null')
    level = fields.Selection([('info', "Info"), ('error', "Error")], required=True, readonly=True, index=True)
    method = fields.Char(readonly=True)
    endpoint = fields.Char(readonly=True)
    status_code = fields.Integer(string="HTTP Status", readonly=True)
    attempt = fields.Integer(readonly=True)
    duration_ms = fields.Integer(string="Duration (ms)", readonly=True)
    request_body = fields.Text(readonly=True)
    response_body = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)
    res_model = fields.Char(string="Document Model", readonly=True, index=True)
    res_id = fields.Many2oneReference(string="Document ID", model_field='res_model', readonly=True, index=True)

    @api.model
    def _get_log_hook(self, company, res_model=None, res_id=None):
        """ Return a callable for TaxCloudClient(log_hook=...) writing entries for `company`. """
        company_id = company.id
        debug = company.sudo().taxcloud_debug_logging
        user_id = self.env.uid

        def log_hook(entry):
            is_error = bool(entry.get('error'))
            if not (is_error or debug):
                return
            self._write_log({
                'company_id': company_id,
                'user_id': user_id,
                'level': 'error' if is_error else 'info',
                'method': entry.get('method'),
                'endpoint': entry.get('endpoint'),
                'status_code': entry.get('status_code') or 0,
                'attempt': entry.get('attempt'),
                'duration_ms': entry.get('duration_ms'),
                'request_body': self._format_body(entry.get('request_body')),
                'response_body': self._format_body(entry.get('response_body')),
                'error_message': entry.get('error'),
                'res_model': res_model,
                'res_id': res_id,
            })
        return log_hook

    @api.model
    def _format_body(self, body):
        if body is None:
            return False
        if not isinstance(body, str):
            body = json.dumps(body, indent=2, default=str)
        return body[:MAX_BODY_LENGTH]

    @api.model
    def _write_log(self, vals):
        """ Write on a separate cursor so the entry survives a rollback of the current transaction.
        In tests, write on the test cursor instead (separate cursors would not see test data). """
        if module.current_test:
            self.sudo().create(vals)
            return
        try:
            with self.env.registry.cursor() as cr:
                self.with_env(self.env(cr=cr, su=True)).create(vals)
        except Exception:  # noqa: BLE001 - logging must never break a tax call
            _logger.exception("Could not write TaxCloud log entry")

    @api.model
    def _cron_purge_logs(self):
        """ Delete entries older than each company's retention period (0 = keep forever). """
        companies = self.env['res.company'].sudo().search([('taxcloud_log_retention_days', '>', 0)])
        domains = [
            [
                ('company_id', '=', company.id),
                ('create_date', '<', fields.Datetime.now() - timedelta(days=company.taxcloud_log_retention_days)),
            ]
            for company in companies
        ]
        for domain in domains:
            while logs := self.sudo().search(domain, limit=PURGE_BATCH_SIZE, order='id'):
                logs.unlink()
                if module.current_test:
                    continue
                self.env['ir.cron']._commit_progress(len(logs), remaining=self.sudo().search_count(domain))
