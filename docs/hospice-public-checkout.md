# Public Hospice checkout

The public `/hospice` campaign is disabled by default. It uses the existing Stripe gateway, ERP prices and delivery rule. Normal website checkout and the authenticated customer ordering portal remain separate.

## Behaviour

- Generic approved wording: “Your purchase supports Hospice Malta through a donation from Callus Garden Centre.”
- Delivery within 3–5 working days. The sales-order planning date is five weekdays ahead, excluding holidays configured on the company.
- Dedicated Customer `Cash Sales - Hospice Malta`. Each checkout creates its own Address and Contact; buyer/company/instructions remain attached to that order, not the shared customer identity.
- Server-controlled product allowlist and warehouse, copied initially from the existing Hospice ordering settings. This copy is independent after setup.
- Customer and preparation-team messages are queued only after verified Stripe payment and ERP reconciliation. The existing business Notification supplies the internal recipients. Sales is the sender.
- The five-minute scheduler queues confirmation emails; reconciliation errors and email errors are separate. Both emails and the notified marker are committed together. SMTP delivery still needs live-environment verification.
- Tracking uses a separate 256-bit token in a URL fragment, submitted by POST. Only its SHA-256 hash is saved on checkout. The email queue necessarily holds the outgoing link. Links expire after 180 days and can be revoked by a System Manager.
- Tracking exposes products and progress only: no address, email, phone, customer document, invoice, driver details or POD. A forwarded link grants access to this limited view.
- Staff update `Hospice Preparation` on the Sales Order. Once delivery execution starts, the existing delivery progress takes precedence.

## Release to UAT first

1. Commit/push only with explicit approval. Deploy code and migrate the site; ensure the scheduler is running. Migration adds fields, but does not create a customer or enable the campaign.
2. Confirm the existing `Blooming Garden Customer Ordering Settings` belongs to Hospice, with the intended products and warehouse. Confirm the existing Webshop price list and delivery rule are appropriate.
3. With a System Manager call `webshop.callus_storefront.hospice.configure` using POST with `enable=1` and `test_email=stephanferriggi@icloud.com`. This creates/reuses the cash customer and copies the product selection once. It does not alter Stripe credentials or enable live payments.
4. Use Stripe **test** credentials and the existing signed-webhook setup in UAT. Confirm the public catalogue, delivery threshold, actual product images, complete Stripe redirect and webhook, accounting, email delivery and tracking from a second browser/device.
5. Test a second buyer and prove each link exposes only its own order. Test partial delivery, cancellation/refund and the actual delivery execution statuses with the installed Bloominggarden app.
6. Production launch is separate. Clear the test-email override; verify actual internal recipients, gateway mode and site URL before enabling. Do not announce the public link before UAT passes.

The settings retain restricted write permissions. A future catalogue change can be made through controlled site administration; rerunning configure does not overwrite an existing campaign selection.

## Validation performed locally

- 10 campaign integration tests with real ERP documents and simulated Stripe/email delivery.
- 18 existing checkout integration tests, including refunds, accounting, stock checks and webhook signature validation.
- 10 notification-origin tests and 8 pure checkout-validation tests.
- Real local Frappe HTTP checks: both pages return 200 with private/no-store headers; Guest address/order access, unknown tracking tokens and Guest configuration return 403.
- Chrome desktop/mobile tests: catalogue, form, review, edit/cancel and tracking display; no JavaScript errors or mobile horizontal overflow.

The campaign tests mock delivery-progress calculation; existing production delivery logic is reused, but actual delivery-stage integration still needs UAT testing. Stripe network calls and SMTP delivery were not performed. This is not a penetration-test certification or a guarantee of zero vulnerabilities.

## Revocation / rollback

Disable `hospice_enabled` to stop new campaign checkouts. Do not disable existing Stripe reconciliation for customers who already started payment. A System Manager can POST `webshop.callus_storefront.hospice.revoke_tracking` with `checkout_name` to revoke an individual tracking link. Preserve accounting records and the dedicated customer.
