# Part of Cybrosys Technologies Pvt. Ltd. See LICENSE file for full copyright and licensing details.
import hashlib
import json
import logging

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.taxcloud_connector.services.taxcloud_client import TaxCloudError

_logger = logging.getLogger(__name__)

TAXCLOUD_CURRENCIES = ('USD', 'CAD')

# TICs TaxCloud never applies an order-level discount to (shipping, excise and fees).
# https://docs.taxcloud.com/guides/workflows/real-time-api/handling-discounts
ORDER_DISCOUNT_EXCLUDED_TICS = frozenset({
    10061, 10062, 10063, 10064, 10065, 10080, 10085, 10090,
    11010, 11011, 11012, 11013, 11014, 11015,
    11097, 11098, 11110, 11120, 91020,
})


class TaxCloudUnavailableError(UserError):
    """ TaxCloud could not be reached or failed transiently (timeout, 429, 5xx): the request
    itself may be fine, so callers can tell this apart from an invalid address or content. """


class TaxCloudTaxMixin(models.AbstractModel):
    """ TaxCloud sales tax on a document (invoice, sales order, POS order).

    TaxCloud's amounts are set on the document lines as manual tax amounts of ordinary Odoo
    taxes. A document model inherits this mixin and implements
    `_taxcloud_get_document_base_lines` and `_taxcloud_filter_eligible`. """
    _name = 'taxcloud.tax.mixin'
    _description = "TaxCloud Tax Computation"

    is_taxcloud = fields.Boolean(compute='_compute_is_taxcloud')
    is_taxcloud_computed = fields.Boolean(
        compute='_compute_is_taxcloud_computed',
        help="Technical: the taxes of this document are computed by TaxCloud.",
    )
    taxcloud_cart_hash = fields.Char(copy=False, readonly=True)
    taxcloud_cart_result = fields.Json(
        copy=False,
        readonly=True,
        help="Technical: TaxCloud result for the cart in taxcloud_cart_hash, as {line id: [tax id, amount]}.",
    )
    taxcloud_tax_amount = fields.Float(
        string="TaxCloud Tax Amount",
        copy=False,
        readonly=True,
        help="Total tax returned by TaxCloud at the last computation.",
    )

    @api.depends('fiscal_position_id')
    def _compute_is_taxcloud(self):
        for record in self:
            record.is_taxcloud = record.fiscal_position_id.is_taxcloud

    @api.depends('fiscal_position_id')
    def _compute_is_taxcloud_computed(self):
        for record in self:
            record.is_taxcloud_computed = record.is_taxcloud

    # Hooks to implement per document (account.move, sale.order, pos.order)
    # =====================================================================
    def _taxcloud_get_document_base_lines(self):
        """ Base lines of the document with their tax details, as for Odoo's own tax computation. """
        raise NotImplementedError()

    def _taxcloud_filter_eligible(self):
        """ Documents whose taxes can be computed now (e.g. not posted, not locked). """
        return self.filtered('is_taxcloud_computed')

    def _taxcloud_get_document_date(self):
        """ Date used as TaxCloud transactionDate (rates as of that date). """
        return fields.Date.context_today(self)

    def _taxcloud_get_destination_partner(self):
        return self.partner_shipping_id or self.partner_id

    def _taxcloud_get_origin_partner(self):
        return self.company_id.partner_id

    def _taxcloud_get_item_id(self, line):
        """ Stable itemId of a document line, unique within the cart. """
        return f'line-{line.id}'

    def _taxcloud_get_fixed_tax_amounts(self, base_lines):
        """ Return ``{line: (account.tax, amount)}`` to skip the TaxCloud call (e.g. reversals), or None. """
        return

    # Entry points
    # ============
    def action_taxcloud_compute_taxes(self):
        self._taxcloud_compute_and_set_taxes()
        return True

    def _taxcloud_compute_and_set_taxes(self):
        """ Compute the TaxCloud taxes of the eligible documents and set them on their lines. """
        eligible = self._taxcloud_filter_eligible()
        if not eligible:
            return True
        eligible._taxcloud_set_taxes(eligible._taxcloud_get_taxes())
        for record in eligible.filtered('taxcloud_cart_hash'):
            if record.currency_id.compare_amounts(record.amount_tax, record.taxcloud_tax_amount):
                record._taxcloud_post_note(self.env._(
                    "Odoo's tax total (%(odoo)s) differs from TaxCloud's (%(taxcloud)s) after rounding.",
                    odoo=record.amount_tax, taxcloud=record.taxcloud_tax_amount,
                ))
        return True

    def _taxcloud_get_taxes(self):
        """ ``{line: base line with manual_tax_amounts}`` for all documents. Errors of all documents
        are raised together, as TaxCloudUnavailableError when one of them is transient. """
        res = {}
        errors, unavailable = [], False
        for record in self.filtered('is_taxcloud_computed'):
            record = record.with_company(record.company_id)
            try:
                res.update(record._taxcloud_compute_taxes())
            except (TaxCloudError, UserError) as e:
                unavailable |= isinstance(e, TaxCloudError) and e.is_retryable
                errors.append(self.env._(
                    "TaxCloud could not compute the taxes of %(document)s:\n%(error)s",
                    document=record.display_name, error=str(e),
                ))
        if errors:
            raise (TaxCloudUnavailableError if unavailable else UserError)('\n\n'.join(errors))
        return res

    @api.model
    def _taxcloud_set_taxes(self, mapped_taxes):
        """ Write the taxes and their manual amounts on the lines of ``{line: base line}``. """
        AccountTax = self.env['account.tax']
        for line, base_line in mapped_taxes.items():
            extra_tax_data = AccountTax._export_base_line_extra_tax_data(base_line)
            line.write({
                'extra_tax_data': extra_tax_data,
                'tax_ids': [Command.set([int(tax_id) for tax_id in extra_tax_data.get('manual_tax_amounts', {})])],
            })

    # Computation
    # ===========
    def _taxcloud_get_base_lines(self):
        """ Base lines of real document lines (skips early payment discount and rounding lines). """
        return [
            base_line
            for base_line in self._taxcloud_get_document_base_lines()
            if isinstance(base_line['record'], models.BaseModel) and base_line['record']
        ]

    def _taxcloud_compute_taxes(self):
        """ Compute taxes for one document.

        :returns: ``{line record: base_line}`` with ``manual_tax_amounts`` set, for
            `_taxcloud_set_taxes`.
        """
        self.ensure_one()
        base_lines = self._taxcloud_get_base_lines()
        if not base_lines:
            return {}

        fixed_amounts = self._taxcloud_get_fixed_tax_amounts(base_lines)
        if fixed_amounts is not None:
            return self._taxcloud_apply_tax_amounts(base_lines, fixed_amounts)

        destination = self._taxcloud_get_destination_partner()
        if destination.country_id and destination.country_id.code != 'US':
            self._taxcloud_post_note(self.env._(
                "TaxCloud was skipped: the destination %(partner)s is outside the United States. No US sales tax applied.",
                partner=destination.display_name,
            ))
            self.write({'taxcloud_cart_hash': False, 'taxcloud_cart_result': False})
            return self._taxcloud_apply_tax_amounts(base_lines, {})

        if self.currency_id.name not in TAXCLOUD_CURRENCIES:
            raise UserError(self.env._(
                "TaxCloud only supports documents in USD or CAD, not %(currency)s.", currency=self.currency_id.name,
            ))
        for partner, role in ((destination, self.env._("customer")), (self._taxcloud_get_origin_partner(), self.env._("ship-from"))):
            if missing := partner._taxcloud_get_missing_address_fields():
                raise UserError(self.env._(
                    "The %(role)s address %(partner)s is incomplete. Missing: %(fields)s",
                    role=role, partner=partner.display_name, fields=", ".join(missing),
                ))

        cart, line_by_index = self._taxcloud_prepare_cart(base_lines)
        transaction_date = self._taxcloud_format_date(self._taxcloud_get_document_date())

        # Same cart and date as the last successful call: re-apply that result without calling
        # TaxCloud. Odoo resets line taxes on many occasions (e.g. every checkout refresh).
        cart_hash = self._taxcloud_get_cart_hash(cart, transaction_date)
        if cart_hash == self.taxcloud_cart_hash and (amounts := self._taxcloud_get_cached_amounts(line_by_index)) is not None:
            return self._taxcloud_apply_tax_amounts(base_lines, amounts)

        # Within one transaction, a cart that just failed is not sent again (checkout pages compute
        # taxes several times per request). cr.now() changes with each transaction, e.g. after a commit.
        failures = self.env.cr.cache.setdefault('taxcloud_cart_failures', {})
        failure_key = (self.env.cr.now(), self._name, self.id, cart_hash)
        if failure_key in failures:
            raise failures[failure_key]
        client = self.company_id._get_taxcloud_client(res_model=self._name, res_id=self.id)
        try:
            response = client.create_carts([cart], transaction_date=transaction_date)
        except TaxCloudError as e:
            failures[failure_key] = e
            raise
        tax_by_index = self._taxcloud_parse_cart_response(response, cart['cartId'])

        amounts = {}
        for index, line in line_by_index.items():
            tax = tax_by_index.get(index) or {}
            amount = self.currency_id.round(tax.get('amount') or 0.0)
            if self.currency_id.is_zero(amount):
                continue
            rate = tax.get('rate') or 0.0
            if not rate:
                base = next(bl for bl in base_lines if bl['record'] == line)['tax_details']['total_excluded_currency']
                rate = amount / base if base else 0.0
            amounts[line] = (self.env['account.tax']._taxcloud_get_tax(self.company_id, rate * 100), amount)

        self.write({
            'taxcloud_cart_hash': cart_hash,
            'taxcloud_cart_result': {str(line.id): [tax.id, amount] for line, (tax, amount) in amounts.items()},
            'taxcloud_tax_amount': sum(amount for _tax, amount in amounts.values()),
        })
        return self._taxcloud_apply_tax_amounts(base_lines, amounts)

    def _taxcloud_apply_tax_amounts(self, base_lines, amounts):
        """ Set ``manual_tax_amounts`` on every base line; lines missing from `amounts` get no tax. """
        mapped = {}
        for base_line in base_lines:
            line = base_line['record']
            tax_amount = amounts.get(line)
            base_line['manual_total_excluded_currency'] = None
            base_line['manual_tax_amounts'] = (
                {str(tax_amount[0].id): {'tax_amount_currency': tax_amount[1]}} if tax_amount else {}
            )
            mapped[line] = base_line
        return mapped

    def _taxcloud_prepare_cart(self, base_lines):
        """ Build the TaxCloud Cart for this document.

        - prices are unit prices before discount; line discounts are sent as percentage
          ``lineItemDiscounts``;
        - lines with a negative subtotal (rewards, global discounts) are summed into one
          ``orderDiscount`` of type amount and get no tax in Odoo.

        :returns: (cart dict, {cart index: line record})
        """
        company = self.company_id
        line_items, line_discounts, line_by_index = [], [], {}
        order_discount = 0.0
        has_discountable_item = False
        for base_line in base_lines:
            line = base_line['record']
            quantity = base_line['quantity']
            subtotal = base_line['tax_details']['total_excluded_currency']
            if self.currency_id.compare_amounts(subtotal, 0) < 0:
                order_discount -= subtotal
                continue
            if not quantity:
                continue
            index = len(line_items)
            item_id = self._taxcloud_get_item_id(line)
            tic = base_line['product_id']._get_taxcloud_tic(company) if base_line['product_id'] else (
                int(company.taxcloud_default_tic) if company.taxcloud_default_tic else None
            )
            item = {
                'index': index,
                'itemId': item_id,
                'price': self._taxcloud_get_unit_price(base_line),
                'quantity': quantity,
            }
            if tic is not None:
                item['tic'] = tic
                has_discountable_item |= tic not in ORDER_DISCOUNT_EXCLUDED_TICS
            else:
                has_discountable_item = True
            line_items.append(item)
            line_by_index[index] = line
            if base_line['discount']:
                line_discounts.append({
                    'itemId': item_id,
                    'cartItemIndex': index,
                    'type': 'percentage',
                    'value': round(base_line['discount'] / 100.0, 6),
                })

        customer = self.partner_id.commercial_partner_id
        cart = {
            'cartId': self._taxcloud_get_cart_id(),
            'customerId': str(customer.id) if customer else self._taxcloud_get_anonymous_customer_id(),
            'currency': {'currencyCode': self.currency_id.name},
            'origin': self._taxcloud_get_origin_partner()._taxcloud_get_address_payload(),
            'destination': self._taxcloud_get_destination_partner()._taxcloud_get_cart_address(company),
            'lineItems': line_items,
        }
        discounts = {}
        if line_discounts:
            discounts['lineItemDiscounts'] = line_discounts
        if not self.currency_id.is_zero(order_discount):
            if not has_discountable_item:
                raise UserError(self.env._(
                    "TaxCloud cannot apply a discount of %(amount)s: all products are shipping or fee items.",
                    amount=order_discount,
                ))
            discounts['orderDiscount'] = {'type': 'amount', 'value': self.currency_id.round(order_discount)}
        if discounts:
            cart['discounts'] = discounts
        if customer and (exemption_id := customer.with_company(company).taxcloud_exemption_id):
            cart['exemption'] = {'exemptionId': exemption_id}
        return cart, line_by_index

    def _taxcloud_get_unit_price(self, base_line):
        """ Unit price before discount, excluding any price-included tax still on the line. """
        price_unit = base_line['price_unit']
        if not any(base_line['tax_ids'].mapped('price_include')):
            return price_unit
        quantity, discount = base_line['quantity'], base_line['discount']
        if not quantity or discount >= 100:
            return price_unit
        return round(base_line['tax_details']['total_excluded_currency'] / quantity / (1 - discount / 100.0), 6)

    def _taxcloud_get_anonymous_customer_id(self):
        """ TaxCloud customerId of a sale without customer (e.g. a walk-in POS sale). """
        return f"{self.company_id.id}-anonymous"

    def _taxcloud_get_cart_id(self):
        self.ensure_one()
        dbuuid = self.env['ir.config_parameter'].sudo().get_str('database.uuid')
        return f"odoo-{dbuuid[:8]}-{self._name}-{self.id}"

    @api.model
    def _taxcloud_format_date(self, date):
        """ RFC 3339; noon UTC keeps the same calendar day in every US time zone. """
        return f"{fields.Date.to_date(date).isoformat()}T12:00:00Z"

    def _taxcloud_parse_cart_response(self, response, cart_id):
        carts = response.get('items') or []
        cart = next((item for item in carts if item.get('cartId') == cart_id), carts[0] if len(carts) == 1 else None)
        if not cart:
            raise UserError(self.env._("TaxCloud returned no result for cart %(cart)s.", cart=cart_id))
        return {item.get('index'): item.get('tax') for item in cart.get('lineItems') or []}

    # Cache
    # =====
    @api.model
    def _taxcloud_get_cart_hash(self, cart, transaction_date):
        payload = json.dumps({'cart': cart, 'date': transaction_date}, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _taxcloud_get_cached_amounts(self, line_by_index):
        """ The stored result as {line: (tax, amount)}, or None when it can no longer be used. """
        result = self.taxcloud_cart_result
        if not isinstance(result, dict):
            return None
        lines = {str(line.id): line for line in line_by_index.values()}
        if not set(result) <= set(lines):
            return None
        taxes = self.env['account.tax'].browse({tax_id for tax_id, _amount in result.values()}).exists()
        if len(taxes) != len({tax_id for tax_id, _amount in result.values()}):
            return None  # a TaxCloud tax was deleted
        return {lines[line_id]: (taxes.browse(tax_id), amount) for line_id, (tax_id, amount) in result.items()}

    # Messages
    # ========
    def _taxcloud_post_note(self, message):
        """ Post `message` in the chatter unless it is already the last message (avoids spam on recomputes). """
        self.ensure_one()
        if not hasattr(self, 'message_post'):
            return
        last_message = self.message_ids.sorted('id', reverse=True)[:1]
        if last_message and html2plaintext(last_message.body or '').strip() == message.strip():
            return
        self.message_post(body=Markup('<p>%s</p>') % message)
