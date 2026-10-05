# Bolt webhook receivers

Webhook capture is the default. Optional catalogue and ERP sales processing are
disabled until explicitly configured and enabled.
Successful responses mean the payload has been retained, not that the merchant
has accepted an order. Bolt picking/acceptance must remain on the Bolt device.
With both automation switches off, no business documents are created. Enabling
order processing creates one Sales Order per Bolt provider/order ID. The separate
Submit Sales switch also submits the order and creates/submits its invoice.
Payment entries, stock posting and settlement remain outside this automation.

## Addresses

Use `https://callusuat.f.frappe.cloud` for staging and
`https://callusgardencentre.frappe.cloud` for production, with these paths:

| Event | Path |
| --- | --- |
| New order | `/api/method/webshop.bolt_integration.webhooks.new_order` |
| Cancel order | `/api/method/webshop.bolt_integration.webhooks.cancel_order` |
| Order update | `/api/method/webshop.bolt_integration.webhooks.order_update` |
| Provider status | `/api/method/webshop.bolt_integration.webhooks.provider_status` |
| Courier details | `/api/method/webshop.bolt_integration.webhooks.courier_details` |

All five require POST and `Content-Type: application/json`. GET `health` at the
same prefix provides authenticated readiness information, without secrets.
Frappe wraps the JSON result under `message`; successful receipt returns HTTP 200.

## Authentication and installation

1. Deploy this Webshop release and migrate each site. Both sites currently share
   a bench. Keep every unrelated app pinned to its existing release.
2. Create the dedicated Website User `bolt-webhook@callusgardencentre.com`, with
   no business roles, no welcome email, and no known interactive password.
3. Generate independent Frappe API key/secret pairs on each site. For HTTP Basic,
   the username is the API key and the password is the API secret. **Do not send
   the administrator's existing API credentials to Bolt.**
4. The `auth_hooks` restriction blocks this dedicated identity from every route
   except the five POST receivers and GET health. Basic auth is mandatory; cookie
   or token authentication cannot be used to broaden that identity's access.
5. In **Callus Bolt Settings**, set the environment and exact site hostname,
   then enable receipt. Enabled defaults to false. The hostname binding prevents
   a database restored onto a differently named site from receiving events.
6. Set the exact `provider_id` when Bolt supplies it. During onboarding, an empty
   provider ID allows authenticated capture only, marking receipts unverified.
   A configured ID rejects every other provider. Business processing remains off
   unless separately configured and enabled (see ERP processing controls).
7. Hand credentials to Bolt through an agreed secure channel, separately from
   the questionnaire. Ask Bolt to enable retries and confirm their test stores.

## Persistence and response behaviour

`Callus Bolt Event` retains each payload, its hash, provider, order reference,
site environment and verification status. Only System Managers may read it;
there is no create/write/delete/export permission through the ordinary UI.
Customer/courier data is kept in this restricted document, not public files or
request-response bodies. Agree retention requirements before live order volume.

Order-scoped messages deduplicate by event type, provider, order and canonical
payload hash. Changed payloads are retained as separate receipts, never silently
lost. Optional sales processing enforces one ERP order per Bolt
provider/order ID. Store-status events lack a unique event ID/timestamp, so every
receipt is retained to preserve active/inactive/active transitions.

The Frappe POST transaction commits before HTTP 200. Storage failures propagate
as failures so Bolt can retry. Malformed payloads return 400; provider mismatch
403; oversize payloads 413; wrong content type 415; disabled/host mismatch 503.
Maximum accepted body size is 512 KiB. No background worker is needed for receipt.

Provider `CALLUS-INTEGRATION-TEST` is reserved for synthetic verification and sets
`is_test=1`. Sales processing excludes these fixtures. Retain them as deployment
proof rather than silently turning them into sales.

## Verification and rollback

Run `python3 -m unittest discover -s tests -p test_bolt_webhooks.py`.
Then test each site's real HTTP stack: Basic authentication, all five payloads,
repeat delivery, malformed content, unauthorized access, cross-site credentials,
service-user REST denial, provider filter and enabled switch. Verify receipts
with administrator read access and verify no Sales Orders/Invoices were created.

To stop receipt, clear Enabled in Callus Bolt Settings; to revoke access, disable
the dedicated User. Existing events remain available. Prefer disabling first to
rolling back schema; never drop the event table or delete captured customer orders.

## Remaining integration validation

The optional catalogue and sales code below still needs deployment and UAT lifecycle
validation. Confirm category and VAT mapping, stock reservation policy, final
picked-basket handling, order acceptance ownership, settlement and refund handling,
alerting and retention before enabling production automation. Bolt end-to-end
approval is not implied by a successful webhook readiness test.

## Independent product selection and synchronisation

Website Item → Publish on Bolt Food (`custom_bolt_enabled`) is independent of
`published`. It defaults to off. UAT and production selections are separate.
The field is recreated idempotently on migration. Marcella’s live form/server
allowlists permit this field, while protected item/display names stay locked.

Configure the provider, region, integrator, encrypted signing secret, gross EUR
price list and default VAT tag before enabling catalogue sync. Selected products
with missing/ambiguous prices or unsupported units require review. Stock uses
Garden Center - BGL actual quantity less reserved quantity, floored and clamped
to 0–10,000 pieces. Product and menu stages resume on five-minute scheduler ticks.
An unchanged catalogue refreshes prices/stock without rebuilding the menu.
Unchecking first sends zero stock, then removes provider assignment and republishes.
The external provider/region must belong exclusively to the intended integration;
category updates replace that region’s tree. Test credentials belong only in UAT.

## ERP processing controls

Set an explicit company, Bolt customer and inclusive tax template. Processing
requires verified matching-provider events and an exact site-hostname match.
CALLUS-INTEGRATION-TEST receipts remain excluded from financial processing.
Use the supplied test provider on UAT for sales lifecycle fixtures.

The order identity is provider + Bolt order ID, independent of receipt hashes.
Duplicate baskets reuse the sale; changed baskets require review. A cancellation
received first creates a tombstone and later order delivery cannot resurrect it.
Cancellation of unpaid, unfulfilled, non-stock-posted invoices/orders is supported.
Paid, delivered, measured, option-bearing and unreconciled baskets require review.
No automatic refund, payment settlement, picking or order acceptance is implemented.

Before enabling production: validate a full UAT order/cancellation lifecycle,
confirm VAT mapping for every selected product (including item tax overrides),
confirm fulfilment and settlement ownership, and have Bolt register the callbacks.

### Bolt pilot observations

Partial `products/import/edit` requests containing only `provider_ids` cleared
category assignment in the test store. Restoration therefore uses the complete
product payload through `products/import/create`, followed by prices and stock,
before publishing. A successful publish response only queues publication; verify
a new publication ID reaches `published` and compare `getMenu` with the selected
SKUs before treating a synchronisation as complete.
