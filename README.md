# TaxCloud Connector for Odoo 20

US sales tax for Odoo 20 Community and Enterprise through the [TaxCloud API v3](https://docs.taxcloud.com):
address verification, tax calculation on invoices, sales orders, eCommerce and
Point of Sale orders, and reporting of invoices, POS orders, refunds and credits to TaxCloud.

Author: Cybrosys Techno Solutions · Licence: LGPL-3 (all modules)

The connector has its own tax layer (`taxcloud.tax.mixin`) and needs no Enterprise module. It
calls TaxCloud at the same moments Odoo Enterprise calls Avatax: when posting, confirming,
sending a quotation, at checkout, on the delivery step, when creating a payment link, and on the
portal and payment-link pages.

## Modules

| Module | Depends on | Installs | Content |
|---|---|---|---|
| `taxcloud_odoo_connector` | `account`, `payment` | manually | API client, settings, API log, address verification, invoice taxes, reporting, refunds, credits |
| `taxcloud_connector_sale` | `taxcloud_odoo_connector`, `sale_management` (Sales app) | manually | quotations and sales orders, warehouse ship-from |
| `taxcloud_connector_website_sale` | `taxcloud_connector_sale`, `website_sale` | manually | eCommerce checkout, payment guard |
| `taxcloud_connector_pos` | `taxcloud_odoo_connector`, `point_of_sale` | manually | POS taxes at payment, POS order and refund reporting |

All modules run on Odoo Community and Enterprise. On Enterprise they can be installed next to
Avatax: each document uses the provider of its fiscal position.

Only `requests` is needed in Python (already an Odoo requirement).

## Setup

### 1. In TaxCloud

1. Create a **connection** for this Odoo database (one for testing and one for production; both
   use the same API host).
2. Activate your **nexus states**. With no nexus state active, TaxCloud returns zero tax for
   every request.
3. Copy the **connection ID** and create an **API key**.
4. Exemption certificates are created in TaxCloud. Odoo only references their IDs (see below).

### 2. In Odoo

1. Add the folder containing the modules to the addons path, e.g.
   `--addons-path=...,/home/cybrosys/odoo20/custom/taxcloud_connector`, update the app list and
   install **TaxCloud Connector**. Then install the bridge of each app you use: **TaxCloud
   Connector - Sales**, **- eCommerce**, **- Point of Sale**. They are not
   installed automatically; without the bridge, that app's documents get no TaxCloud tax.
2. **Invoicing > Configuration > Settings > Taxes > TaxCloud** (US companies only):
   - **API Key** (visible to administrators only) and **Connection ID**, then **Test Connection**.
   - **Tax Template**: a sales tax (percentage, tax excluded) whose accounts and tax group are
     copied for each TaxCloud rate. Usually the default sales tax.
   - **Default TIC**: TaxCloud Taxability Information Code used when a product and its category
     define none (`00000` = general tangible goods).
   - **Verify Addresses**: verify unverified customer addresses before each calculation (only the
     tax request uses the result; the customer is never changed).
   - **Debug Logging** and **Log Retention (Days)** (0 = keep forever).
3. **Fiscal position.** Companies on the US chart get **Automatic Tax Mapping (TaxCloud)** with
   *Use TaxCloud API* ticked. Documents with this fiscal position use TaxCloud.
   - The fiscal position is **not auto-applied** on install. Tick *Auto-apply* (country: United
     States) so new US orders, website orders and invoices get it automatically. eCommerce needs
     this.
   - Upgrading an existing database does not create the fiscal position. Create one yourself and
     tick *Use TaxCloud API*.
4. **TICs.** Set a *TaxCloud TIC* on product templates or categories. Lookup order: product, then
   the category and its parents, then the company default.
   - Give the **shipping/delivery product** a shipping TIC (e.g. `11010`) so TaxCloud treats it as
     shipping (and never applies order discounts to it).
5. **Exemptions.** Enter the TaxCloud certificate ID in *TaxCloud Exemption Certificate* on the
   customer (company-specific; *Sales & Purchase* tab, *Fiscal Information*). It is sent in every cart of
   that customer.
6. **Ship-from.** The company address, or with Inventory the order's warehouse address (see
   Flows). Make sure those addresses are complete (street, city, state, ZIP).

### Upgrading

These modules add stored fields to central models (contacts, invoices, orders). After updating
the code, **upgrade from the command line** (`-u taxcloud_connector,...`), not with the
*Upgrade* button in Apps. The Apps button reads contacts before the new columns exist and fails
with `column ... does not exist`.

## Flows

### Address verification

- **On the contact:** the *Verify* button (US addresses) opens a comparison of the current and
  suggested address. *Apply Suggestion* writes it and marks the contact **Verified** with a date.
- **Changes clear the flag:** any later address change clears it, including addresses synced
  from a parent company.
- **During tax calculation** (setting on): unverified complete US addresses are verified and the
  result (ZIP+4) is used **in the cart only**.
  - If verification fails, the address as entered is used. Nothing is blocked.
  - Results are cached per Odoo process for 24 hours. A temporary error is retried next time.

### Tax calculation

**When.** Taxes are computed when an invoice is posted, a quotation is sent or confirmed, the
*Compute Taxes* button is used, a customer opens the portal or payment link, and at checkout.
- No new API call is made while the cart, address, date and line taxes are unchanged.
- In web requests the client times out after 10 s with 1 retry; crons use 20 s and 2 retries.

**What is sent.**
- One cart per document: `odoo-<db>-<model>-<id>`. The customer ID is the commercial partner's ID.
- The destination is the delivery address.
- Each line goes with its pre-discount unit price, quantity and TIC.
- Line discounts are sent as percentage discounts.
- Negative lines (rewards, global discounts) are summed into one order discount and get no tax in
  Odoo.
- Tax date: the invoice date or the order date. It is sent as noon UTC so the calendar day
  is the same in every US time zone.

**Result.**
- Each line gets TaxCloud's **exact** tax amount, so Odoo's total equals TaxCloud's.
- The tax is a sales tax named like `TaxCloud 8.125%`, one per rate (4 decimals), copied from the
  template. Existing ones are reused and unarchived.

**Skips.**
- Customer outside the US: no TaxCloud call, no tax, one chatter note.
- Currency other than USD or CAD: blocked.

### Ship-from

- **Without Inventory:** the company address.
- **With Inventory, on orders:** the order's warehouse address, if complete.
- **With Inventory, on invoices:** the single warehouse the goods left from (stock moves), else the
  order's warehouse.
- **Several warehouses, or an incomplete address:** the company address. A TaxCloud cart has one
  origin.

### Reporting (accrual: on posting)

1. **Queued on posting.** Posted customer invoices and credit notes computed by TaxCloud, for US
   customers, become *To Report* and the TaxCloud cron is triggered. It also runs every 15 minutes.
2. **Invoices.**
   - The cart is re-sent from the posted invoice.
   - If TaxCloud's tax still equals the posted tax, the cart becomes a **completed order**. The
     order ID is the invoice number with characters other than letters, digits, `.`, `_` and `-`
     replaced by `-`. The completed date is the invoice date (or "now" for today's invoices).
3. **Credit notes from a reversal** are reported as **refunds** of the original order.
   - They wait until that order is reported.
   - **Full** (empty body) when they return everything and are the first refund.
   - Otherwise by item and quantity. Item IDs come from the invoice lines and are copied by the
     reversal.
   - Each refund has an idempotency key and its credit note's date as return date.
4. **Other credit notes** are reported as **standalone credits** (`kind: credit`) with their posted
   taxes.
5. **Processing.**
   - Oldest first; each document is locked, has its own savepoint, and progress is committed after
     each one.
   - Failures are stored on the document (see below).
   - Filters *TaxCloud Errors* / *TaxCloud Pending* in the invoice list; status, order ID and date
     in *Other Info*.

### Reset to draft

- **Reported invoice:** after Odoo's own checks, the TaxCloud order is **voided**. Posting again
  reports it again under the same order ID.
- **Blocked when:**
  - TaxCloud refuses the void (after the 10th of the month following completion), or
  - refunds of the invoice were already reported, or
  - the document is itself a reported refund.

  Use a credit note instead.
- **Not reported yet:** it simply leaves the queue.

### Sales orders

Quotations and orders compute taxes as above (cancelled and locked orders excluded). Invoices
created from an order keep its TaxCloud fiscal position and delivery address. They are recomputed
**at the invoice date** with their own cart, then reported. Sales orders are never reported.

### eCommerce

- **When taxes are computed:** Odoo 20 refreshes cart taxes and prices on the payment step and
  again before creating a payment transaction (`_update_cart_taxes_and_prices`), and when the
  delivery method changes or at express checkout. Tax and total are shown from the payment step
  on. Address steps no longer call TaxCloud.
- **One call per cart:** each refresh first resets line taxes; the stored TaxCloud result is
  re-applied while the cart, address and date are unchanged.
- **Address verification** at checkout is silent (tax only).
- **No payment without tax.** If TaxCloud is unreachable, the cart gets a **blocking alert**
  *We could not calculate sales tax right now. Please try again in a few minutes.* Blocking alerts
  stop the checkout, and the payment transaction route validates the cart again, so an old
  payment page cannot pay without tax.
- **Invalid addresses** get Odoo's blocking address alert with TaxCloud's details.

### Point of Sale

- **Which orders:** only orders whose fiscal position has **Use TaxCloud** (set it as the shop's
  default fiscal position, or on a preset). Other orders keep Odoo's POS taxes.
- **When taxes are computed:** when the payment screen opens, and again at validation if the
  customer, preset or lines changed since. An unchanged order is not sent again.
- **No payment without tax:** if TaxCloud cannot be reached (or the POS is offline), an error
  dialog is shown and the order cannot be validated.
- **Addresses:** ship-from is the shop's warehouse (Inventory installed, complete address) or the
  company. Ship-to is the shop for counter sales, and the customer's delivery address for presets
  that ask for an address or orders shipped later.
- **Customer:** walk-in sales use the customer ID `<company id>-anonymous`; a customer's exemption
  certificate is used when a customer is set.
- **Reporting:** paid orders become *To Report* and are reported by their own cron (every 15
  minutes, triggered on payment), with the same retries, banners and *Retry* button as invoices.
  The TaxCloud order ID is the receipt number made URL-safe.
- **Refunds:** a refund order returns the original lines' tax pro rata and is reported as a full
  or partial refund of the original order, after it. Refund orders cannot also sell new items.
- **Invoices of POS orders** keep the order's taxes and are not reported themselves, so the sale
  is not counted twice.

## Errors and what happens

| Situation | Where | Behaviour |
|---|---|---|
| No API key / connection ID / tax template | any calculation | Blocked, with a link to the settings |
| Invalid address or content (400, 422) | posting, confirming, *Compute Taxes* | Blocked with TaxCloud's message (field and reason) |
| TaxCloud unreachable (timeout, 429, 5xx) | backend | Retried in the call (exponential backoff, `Retry-After`), then blocked with the message |
| TaxCloud unreachable | checkout | Blocking cart alert *try again in a few minutes*; payment refused; same cart not resent within the request |
| Invalid address | checkout | Blocking cart alert with TaxCloud's details; payment refused |
| Address verification fails | tax calculation | Address used as entered, never blocks |
| Customer outside the US | tax calculation | No call, no US tax, one chatter note |
| Currency not USD/CAD, incomplete customer or ship-from address | tax calculation | Blocked with the reason |
| Order discount but only shipping/fee items | tax calculation | Blocked (TaxCloud would reject it) |
| Reversal credit note with new lines, other prices, or more than invoiced | posting the credit note | Blocked: refunds are by item and quantity |
| Reporting: 429 / 5xx / network | cron | *To Report* kept, yellow banner, retried up to **5** attempts, then *Error* |
| Reporting: 400 / 422 | cron | Get Order: already there for this customer → *Reported*; otherwise *Error* at once |
| Reporting: TaxCloud's tax ≠ posted tax | cron | *Error*: reset to draft, recompute, post again |
| Reporting error | invoice | Red banner with the error and a **Retry** button (resets attempts, retries now) |
| Refund before its invoice is reported | cron | Waits (blue banner), no attempt used |
| Refund exceeds the refundable amount (422) | cron | *Error* |
| TaxCloud refund tax ≠ Odoo credit-note tax | cron | Reported; chatter note with both amounts |
| Void refused (after cutoff) / refunds reported | reset to draft | Blocked, invoice stays posted |
| Any API call | API log | Errors always logged; successful calls only with debug logging (Accounting > Configuration > TaxCloud Logs) |

The API log never contains the API key. With debug logging on, request bodies contain customer
addresses; the log is readable by accounting managers only. Entries are written on a separate
database cursor so they survive a rollback, and are purged daily after the retention period.

## Known limits

- **Down payments:** down-payment invoices are excluded, so their tax is neither
  computed by TaxCloud nor reported. The final invoice reports the full order.
- **One ship-from per cart:** goods shipped from several warehouses use the company address.
- **Refunds are by item and quantity:** price adjustments on reversal credit notes are blocked.
  Issue a standalone credit note instead (reported as a TaxCloud credit).
- **Order IDs are document numbers:** they must be unique per TaxCloud connection. Companies
  sharing a connection need distinct numbering (a clash is reported as an error, never filed).
- **Void window:** TaxCloud allows voids only until the 10th of the month after completion.
  - The void runs after Odoo's checks in the same transaction. If that transaction later failed,
    TaxCloud would have voided an invoice that stays posted; no later step is known to fail.
- **Payment then confirmation:** if TaxCloud fails while a paid website order is being confirmed
  (it normally reuses the result computed before payment), Odoo's payment post-processing handles
  the error.
- **Exemptions:** certificates are referenced by ID only; create and manage them in TaxCloud.
- **Excluded lines:** early payment discount and cash rounding lines are not sent to TaxCloud.
- **Not sent:** TaxCloud's `productId` (it must match TaxCloud's catalog).
- **Behaviour TaxCloud doesn't document,** handled conservatively:
  - how an unverifiable address is reported (any 4xx = "not verified");
  - whether 429/502–504 are retryable (treated as retryable);
  - the status of a duplicate order ID (any 4xx, then Get Order);
  - `orderId` character rules (restricted to letters, digits, `.`, `_` and `-`).
- **Address verification** is US only (TaxCloud accepts only `US` there).
- **POS:** a credit note made in Accounting from the invoice of a POS order is not reported;
  return the goods with a POS refund instead.
- **POS returns without the original order** (return mode) are taxed through a cart and reported
  as a TaxCloud standalone credit.
- **Rates can change after posting:** if TaxCloud computes a different tax for a posted invoice
  when reporting, it is not reported until reset, recomputed and posted again.

## Development

- **Tests** are tagged `taxcloud` and mock every HTTP call; no TaxCloud account is needed:

  ```
  python odoo-bin -c odoo.conf \
    --addons-path=<odoo>/addons,/home/cybrosys/odoo20/custom/taxcloud_connector \
    -d <new_db> -i taxcloud_connector,sale_stock,website_sale,point_of_sale \
    --test-enable --test-tags=taxcloud --stop-after-init
  ```

  Installing `sale_stock` exercises the warehouse ship-from tests.
- **The client** (`taxcloud_connector/services/taxcloud_client.py`) has no ORM dependency and is
  tested with a fake HTTP session. Errors raise `TaxCloudError(message, status_code, errors)` with
  `is_retryable`.
- **Per-document hooks** on `taxcloud.tax.mixin` (implemented by invoices, sales orders and POS
  orders). Required: `_taxcloud_get_document_base_lines`, `_taxcloud_filter_eligible`. Optional:
  - `_taxcloud_get_document_date`
  - `_taxcloud_get_destination_partner`
  - `_taxcloud_get_origin_partner`
  - `_taxcloud_get_item_id`
  - `_taxcloud_get_fixed_tax_amounts`

## Decisions

| Question | Decision |
|---|---|
| Licence | LGPL-3 for all modules |
| Odoo edition | Community and Enterprise |
| eCommerce, TaxCloud unreachable | Block payment |
| eCommerce address verification | Silent, tax only |
| When to report | On posting (accrual) |
| Reset reported invoice to draft | Void the order; block if TaxCloud refuses or refunds exist |
| Credit notes not from a reversal | Standalone TaxCloud credits |
| Ship-from | Warehouse, else company |
| Exemptions | Reference existing certificate IDs only |
