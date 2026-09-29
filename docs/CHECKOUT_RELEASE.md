# Callus checkout candidate 2

## Status

Source implementation is complete for guest collection and configured Malta delivery, Stripe-hosted card payment, invoice/payment reconciliation and a full refund of an undelivered order. This candidate has **not yet been deployed or enabled on UAT**. The existing UAT checkout must not be described as ready for customer payment until the deployment checks below pass.

Local verification: 21 catalogue/validation tests, 15 ERPNext integration tests, and 9 checks through Frappe's real HTTP application. The ERP tests use actual Sales Orders, stock reservations, invoices, Payment Entries, credit notes and general ledger entries in an isolated local database. Stripe responses are simulated; no remote payment calls occur. Desktop/mobile browser checks use a separate synthetic UI fixture. These checks do not substitute for the UAT acceptance pass.

## What changed

- New `Callus Checkout` records retain each attempt, its order, invoice, payment and refund links. Read access is restricted to System Managers. Guest order access requires an unguessable browser-held capability; only its SHA-256 hash is stored.
- New `Callus Checkout Settings` gates activation for an exact site URL, matching Stripe credential mode, EUR clearing account and configured webhook. All sites default to disabled, including production.
- Only product codes, integer quantities and bounded contact/address fields cross the customer boundary. Client prices, discounts, totals, customer IDs, account IDs, URLs and paid flags are ignored.
- Each attempt creates its own guest Customer/contact, never granting access to an existing account based on an unverified email address.
- ERPNext calculates the order. Unpublished/disabled/non-sale products and insufficient stock are rejected. Stock is checked again under database locks before submitting the order. A submitted order reserves stock while payment is pending.
- The customer reviews the ERPNext total, then Stripe hosts card entry and any card authentication. Browser redirects do not mark payments paid. The server retrieves and matches the Stripe session, amount, currency, mode and order reference.
- Session creation and refunds use stable Stripe idempotency keys. The remote request is persisted before transmission so a lost response can be retried consistently.
- Payment confirmation creates one Sales Invoice and one Payment Entry. It does not ship goods or change physical stock. Repeated callbacks do not create duplicate entries.
- Cancellation expires the Stripe session before cancelling its unpaid order. Expired Stripe sessions release order reservations. Failed/declined payments remain unpaid and may be retried on the same hosted session.
- Full refunds are available to System Managers from the checkout record. Stripe success creates a credit note and an outward Payment Entry, then closes the undelivered order. Original records remain for audit. Fulfilled orders require the normal returns workflow. Partial refunds and complex/manual reconciliation remain staff workflows.
- Signed webhooks use Stripe's documented timestamp/HMAC check with a five-minute tolerance. Authenticated Stripe retrieval is still authoritative. A five-minute scheduled reconciliation job provides recovery where the site scheduler is enabled. Do not enable all UAT scheduling just for this job without reviewing other jobs.
- Shop / Shop Pay identity, customer account history for anonymous orders, promotional coupons, non-EUR currencies and automatic fulfilment are outside this candidate.

## UAT deployment and activation

1. Back up UAT. Publish the reviewed source only after explicit commit/push approval. Deploy that exact revision to **UAT only**, leaving production unselected. Frappe migration creates the two new DocTypes; it does not enable payment.
2. Reapply the UAT Builder records as necessary using the existing backup-first process. Confirm the shared checkout script matches the new source. Keep UAT pages unindexed and email sending disabled.
3. Keep the existing Webshop Settings `enable_checkout` unchanged. The new flow has a separate explicit activation switch. Verify company, selling price list, customer group, VAT rules and the selected Stripe EUR payment account.
4. Verify the Stripe Settings protected secret is decryptable and belongs to the intended account. Prefer Stripe's sandbox for integration verification. Never store credentials in source, reports or browser code.
5. Invoke the authenticated System Manager method `webshop.callus_storefront.checkout.configure_stripe` with the **exact current site URL** and explicit `allow_live_payments` value (0 for test; 1 for live). This reads the site's existing protected Stripe credentials, verifies the account, creates a dedicated webhook for this URL if absent, stores its signing secret privately and enables only this site's new checkout. It does not edit any existing production webhook. No payment is initiated by configuration.
6. The endpoint is `/api/method/webshop.callus_storefront.checkout.webhook`. Subscribe to `checkout.session.completed`, `checkout.session.expired`, `charge.refunded` and `refund.updated`. Verify delivery in Stripe's dashboard. A copied webhook setting with a different URL/mode fails validation; do not reuse another site's signing secret.
7. Set `delivery_rule` only after confirming the intended ERPNext Shipping Rule. Without it, the UI offers collection and directs delivery enquiries to staff. Review `maximum_order_total` (default EUR 1,000) before activation.
8. Confirm `/api/method/webshop.callus_storefront.checkout.options` returns the intended mode. If any configuration check fails, the public checkout remains unavailable.

## Customer acceptance sequence

- Open a fresh browser session; add an in-stock product; enter guest details and a Malta billing address; choose collection or configured delivery.
- Review the ERPNext total and check VAT and delivery charges. Compare the order against the actual current catalogue and stock.
- Open Stripe Checkout. Confirm the merchant, currency and amount. The customer enters their own card/authentication details; the assistant does not collect card details.
- Verify provider-confirmed payment on the website and in Stripe. In UAT, check exactly one submitted Sales Order, Sales Invoice and Payment Entry, and zero outstanding invoice balance. A success redirect alone is insufficient.
- Confirm signed callbacks arrive even if the browser closes. Check decline, cancellation, retry, duplicate callback and expired-session recovery in sandbox.
- For a full refund before fulfilment, open its **Callus Checkout** record and use **Refund full payment**. Confirm provider status and one submitted credit note/refund Payment Entry. Verify the customer and clearing-account ledger balances reverse the original amount. Stripe settlement fees are reconciled separately; they are not assumed refundable.
- Record the source revision and order/payment/refund references. Do not fulfil UAT orders or copy their transactions into production.

Stripe documents sandbox testing and explicitly says not to test with real payment details in live mode: https://docs.stripe.com/testing. A live purchase is a real transaction, not a simulated validation result.

## Recovery and limitations

Disable `Callus Checkout Settings.enabled` to stop new attempts. Keep webhooks and reconciliation available for payments already in flight. Do not delete checkout records, invoices or payments to reset a test. Refunding is a financial action and must be deliberately initiated by an authorised manager.

If a session-creation request times out, retain its token/attempt and retry; do not create a new payment by hand. A saved but unrecoverable request requires staff review at Stripe before releasing its reserved order. If stock, invoice totals or accounting configuration change after payment, reconciliation fails visibly and requires review; it must not fabricate success. Automatic refunds support a full, undelivered order; shipped/invoiced-outside-this-flow or partially refunded cases need normal accounting review.

The browser keeps the current checkout capability in session storage so it survives the Stripe redirect. Clearing site data or using another device requires assistance with the order reference. Customer email delivery remains disabled on UAT. Final merchant policies and production release rehearsal are still required before public launch.

## Reproduce tests

Pure tests: `python -m unittest discover -s tests -p 'test_callus*.py' -v`.

On an isolated Frappe bench with ERPNext, Payments and Webshop installed, from its `sites` directory:

```
../env/bin/python ../apps/webshop/tests/run_checkout_integration.py test_site
../env/bin/python ../apps/webshop/tests/checkout_http.py test_site
```

The runners reject arbitrary site names. They create synthetic fixture data and must never target production. The local run used the existing local v15 Frappe/ERPNext runtime and a new MariaDB/Redis container pair; UAT's exact versions still require the acceptance pass. Builder rendering was checked separately rather than installed in that local accounting bench.
