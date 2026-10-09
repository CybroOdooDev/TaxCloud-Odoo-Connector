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
from unittest.mock import patch

from odoo import Command

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudClient

FAKE_API_KEY = 'fake-api-key-for-tests'
FAKE_CONNECTION_ID = 'fake-connection-id'


class FakeResponse:
    """ Minimal stand-in for requests.Response. """

    def __init__(self, status_code=200, body=None, headers=None, text=None):
        self.status_code = status_code
        self.headers = headers or {}
        if text is None:
            text = '' if body is None else json.dumps(body)
        self.text = text
        self.content = text.encode()
        self.reason = 'Reason'

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """ Returns queued responses (or raises queued exceptions) and records every call. """

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, json=None, params=None, timeout=None):
        self.calls.append({'method': method, 'url': url, 'json': json, 'params': params, 'timeout': timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TaxCloudTestCommon(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data['company']
        # generic_coa is the US chart; no need to depend on l10n_us_account.
        cls.company.country_id = cls.env.ref('base.us')
        cls.company.sudo().write({
            'taxcloud_api_key': FAKE_API_KEY,
            'taxcloud_connection_id': FAKE_CONNECTION_ID,
            'taxcloud_tax_template_id': cls.company_data['default_tax_sale'].id,
        })


class TaxCloudCartCommon(TaxCloudTestCommon):
    """ Adds a TaxCloud fiscal position, US addresses and a fake cart endpoint. """

    RATE = 0.08125

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.us = cls.env.ref('base.us')
        cls.state_wa = cls.env['res.country.state'].search([('code', '=', 'WA'), ('country_id', '=', cls.us.id)])
        cls.company.partner_id.write({
            'street': '100 Origin Way', 'city': 'Seattle', 'state_id': cls.state_wa.id,
            'zip': '98101', 'country_id': cls.us.id,
        })
        cls.fpos_taxcloud = cls.env['account.fiscal.position'].create({
            'name': 'TaxCloud', 'is_taxcloud': True, 'company_id': cls.company.id,
        })
        cls.partner_us = cls.env['res.partner'].create({
            'name': 'US Customer', 'street': '1 Main St', 'city': 'Seattle', 'state_id': cls.state_wa.id,
            'zip': '98104', 'country_id': cls.us.id,
        })
        cls.carts_sent = []

    def setUp(self):
        super().setUp()
        self.carts_sent = []
        self.tax_overrides = {}  # {itemId: {'amount': x, 'rate': y}} to force TaxCloud answers

    def _fake_create_carts(self, client, carts, transaction_date=None):
        """ Mimic TaxCloud: tax = rate * price * quantity after line and order discounts, rounded per line. """
        self.carts_sent.append({'carts': carts, 'transaction_date': transaction_date})
        items = []
        for cart in carts:
            discounts = cart.get('discounts') or {}
            pct = {d['itemId']: d['value'] for d in discounts.get('lineItemDiscounts', [])}
            amounts = {
                line['index']: line['price'] * line['quantity'] * (1 - pct.get(line['itemId'], 0.0))
                for line in cart['lineItems']
            }
            order_discount = (discounts.get('orderDiscount') or {}).get('value', 0.0)
            total = sum(amounts.values())
            line_items = []
            for line in cart['lineItems']:
                amount = amounts[line['index']]
                if order_discount and total:
                    amount -= order_discount * amounts[line['index']] / total
                tax = self.tax_overrides.get(line['itemId']) or {'amount': round(amount * self.RATE, 2), 'rate': self.RATE}
                line_items.append({**line, 'tax': tax})
            items.append({**cart, 'lineItems': line_items})
        return {'connectionId': client.connection_id, 'transactionDate': transaction_date, 'items': items}

    def _patch_carts(self, **kwargs):
        kwargs.setdefault('side_effect', self._fake_create_carts)
        return patch.object(TaxCloudClient, 'create_carts', autospec=True, **kwargs)


class TaxCloudInvoiceCommon(TaxCloudCartCommon):
    """ Products with TICs and helpers to create TaxCloud invoices. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.categ_parent = cls.env['product.category'].create({'name': 'Clothing', 'taxcloud_tic': '20010'})
        cls.categ_child = cls.env['product.category'].create({'name': 'Shirts', 'parent_id': cls.categ_parent.id})
        cls.product_shirt = cls.env['product.product'].create({
            'name': 'Shirt', 'lst_price': 10.75, 'categ_id': cls.categ_child.id,
            'taxes_id': [Command.set(cls.company_data['default_tax_sale'].ids)],
        })
        cls.product_book = cls.env['product.product'].create({
            'name': 'Book', 'lst_price': 100.0, 'taxcloud_tic': '30070',
            'taxes_id': [Command.set(cls.company_data['default_tax_sale'].ids)],
        })

    def _invoice(self, lines, partner=None, move_type='out_invoice', post=False, **vals):
        invoice = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': (partner or self.partner_us).id,
            'invoice_date': '2026-10-01',
            'fiscal_position_id': self.fpos_taxcloud.id,
            'invoice_line_ids': [Command.create(line) for line in lines],
            **vals,
        })
        if post:
            invoice.action_post()
        return invoice

    def _line(self, product, quantity=1.0, **vals):
        return {'product_id': product.id, 'quantity': quantity, **vals}
