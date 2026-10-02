# Bolt webhook receivers

This release provides **capture only**, not a complete order or stock integration.
Successful responses mean the payload has been retained, not that the merchant
has accepted an order. Bolt picking/acceptance must remain on the Bolt device.
No invoice, Sales Order, payment, email or stock mutation is triggered.

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
   A configured ID rejects every other provider. No automatic business processing
   is available in either state.
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
lost. Future sales processing must additionally enforce one ERP order per Bolt
provider/order ID. Store-status events lack a unique event ID/timestamp, so every
receipt is retained to preserve active/inactive/active transitions.

The Frappe POST transaction commits before HTTP 200. Storage failures propagate
as failures so Bolt can retry. Malformed payloads return 400; provider mismatch
403; oversize payloads 413; wrong content type 415; disabled/host mismatch 503.
Maximum accepted body size is 512 KiB. No background worker is needed for receipt.

Provider `CALLUS-INTEGRATION-TEST` is reserved for synthetic verification and sets
`is_test=1`. Future processing must exclude these fixtures. Retain them as deployment
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

## Work still required for full integration

Product/category/tax/price mapping; Bolt outbound credentials and request signing;
stock reservation rules; final picked-basket retrieval; order acceptance ownership;
sales and settlement mapping; cancellation/refund rules; out-of-order event handling;
processing/reconciliation queues and alerting; retention; Bolt end-to-end sandbox
approval. These are not implied by a successful webhook readiness test.
