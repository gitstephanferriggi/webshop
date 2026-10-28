# Public Hospice checkout

The public `/hospice` campaign is disabled by default. It uses the existing Stripe gateway and VAT-inclusive ERP price list. Normal website checkout and the authenticated customer ordering portal remain separate.

## Behaviour

- Generic approved wording: “Your purchase supports Hospice Malta through a donation from Callus Garden Centre.”
- Customers choose delivery or pickup. Pickup requires contact details only; no Address is created or inherited from the shared customer. Pickup is free and customers wait for the ready email before visiting. Delivery is within 3–5 working days. The sales-order planning date is five weekdays ahead, excluding holidays configured on the company.
- Product prices include VAT. Inclusive flags are set on the Hospice order's own tax rows; shared tax templates and ordinary website/POS pricing are not changed. Item tax templates still supply the actual VAT rates.
- Delivery below €35 of products **including VAT** adds one non-stock service line, `ITE-2025-016885` (configurable in **Hospice Delivery Item**). Its price is taken from the same price list, including its own item VAT. Delivery is free at or above **Hospice Free Delivery From** (default €35). The campaign does not apply the general Shipping Rule as well. Delivery is omitted from the product list and physical delivery quantities.
- Dedicated Customer `Cash Sales - Hospice Malta`. Each checkout creates its own Contact and, for delivery, its own Address; buyer/company/instructions remain attached to that order, not the shared customer identity.
- Server-controlled product allowlist and warehouse, copied initially from the existing Hospice ordering settings. This copy is independent after setup.
- Customer and preparation-team messages are queued only after verified Stripe payment and ERP reconciliation. The existing business Notification supplies the internal recipients. Sales is the sender.
- The five-minute scheduler queues confirmation emails; reconciliation errors and email errors are separate. Both emails and the notified marker are committed together. SMTP delivery still needs live-environment verification.
- Tracking uses a separate 256-bit token in a URL fragment, submitted by POST. Only its SHA-256 hash is saved on checkout. The email queue necessarily holds the outgoing link. Links expire after 180 days and can be revoked by a System Manager.
- Tracking exposes products and progress only: no address, email, phone, customer document, invoice, driver details or POD. A forwarded link grants access to this limited view.
- The Sales Order displays **Hospice Fulfilment** (Pickup/Delivery) and **Hospice Order Progress**. Draft picking/partial dispatch starts preparation; fully submitted picking or dispatch makes the goods ready. Delivery trips/executions then supply scheduled, en-route, partial delivery and confirmed POD states. A submitted Delivery Note alone never proves receipt. Cancellation recomputes progress from the remaining records.
- Staff can use **Hospice → Ready for pickup** to declare a paid pickup ready. One customer email is queued, atomically with its checkout marker; retries cannot create another ready email. **Confirm collection** replaces the unsigned **Mark collected** action. The optional **Manual Preparation Step** is distinct from the automatically calculated progress.
- Document hooks refresh progress immediately; the existing five-minute Hospice job reconciles older orders and retries email failures. Public tracking computes from the same facts on each refresh. Existing paid totals, invoices and payments are preserved.

## Release to UAT first

1. Commit/push only with explicit approval. Deploy code and migrate the site; ensure the scheduler is running. Migration adds fields, but does not create a customer or enable the campaign.
2. Confirm the existing `Blooming Garden Customer Ordering Settings` belongs to Hospice, with the intended products and warehouse. Confirm the Webshop price list contains VAT-inclusive product and delivery-service prices; check the service item's sales VAT template and the free-delivery threshold.
3. With a System Manager call `webshop.callus_storefront.hospice.configure` using POST with `enable=1` and `test_email=stephanferriggi@icloud.com`. This creates/reuses the cash customer and copies the product selection once. It does not alter Stripe credentials or enable live payments.
4. Use Stripe **test** credentials and the existing signed-webhook setup in UAT. Confirm the public catalogue, delivery threshold, actual product images, complete Stripe redirect and webhook, accounting, email delivery and tracking from a second browser/device.
5. Test a second buyer and prove each link exposes only its own order. Test pickup without an address, ready-email delivery, collection, exactly €35 of products, partial dispatch, cancellation/refund and actual delivery execution statuses with the installed Bloominggarden app. Confirm both desk and public tracking agree on the existing paid order after the scheduler reconciliation.
6. Production launch is separate. Clear the test-email override; verify actual internal recipients, gateway mode and site URL before enabling. Do not announce the public link before UAT passes.

The settings retain restricted write permissions. A future catalogue change can be made through controlled site administration; rerunning configure does not overwrite an existing campaign selection.

## Plan delivery from the Sales Order

Paid Hospice delivery orders at **Ready for dispatch** have **Hospice → New delivery trip** and **Hospice → Add to delivery trip** actions. Select an existing submitted Delivery Note; the new-trip dialog also requires a driver, vehicle and departure time. Existing trips must be normal drafts in the same company. Both actions save a draft and open it for review; staff submit the trip separately to release it. No Delivery Note or stock movement is created by these actions.

The stop uses the order/Delivery Note's own delivery address and contact, never a default on the shared cash customer. Document permissions are checked server-side. A note already on another draft or submitted trip is rejected; adding it again to the same draft returns that trip without another stop. Combined-order notes must be planned from Delivery Trip for deliberate review.

## Signed collection and delivery receipts

- **Pickup:** a paid, ready order displays **Hospice → Confirm collection**. The screen shows the fixed product quantities, requires the actual collector's name and signature, and asks them to acknowledge receipt. Blank, malformed and oversized signature images are rejected server-side.
- Confirmation records the signature, collector, date/time/time zone and staff member in a submitted **Callus Handover**. The stock posting and signed record are one transaction. A valid submitted Delivery Note is reused; a matching draft is submitted; otherwise only the remaining goods are posted on a new note. Ambiguous drafts, returns and inconsistent quantities require review. Retries return the existing handover instead of posting stock twice.
- Only after successful confirmation does pickup become **Collected**. Direct unsigned API or manual-field changes to Collected are blocked. Historical orders already recorded Collected remain unchanged; no signature is fabricated for them. Signed evidence cannot be deleted/cancelled through the workflow, and a supporting pickup Delivery Note must use the returns workflow instead of cancellation.
- **Delivery:** the existing driver flow still collects recipient name/signature and submits Delivery Execution. Submitted successful evidence creates one receipt per execution and Hospice order. Partial deliveries list only the quantities received on that attempt. Failed/unsigned/cancelled/unsubmitted evidence does not produce a customer receipt. A combined Delivery Note produces separate PDFs and recipients for its individual orders; the shared cash customer's default email is never the campaign recipient.
- PDFs are private attachments on the Sales Order. Neither signature nor receipt URL is added to capability-based public tracking. Staff with access to the Sales Order can use **Hospice → Signed receipts** to open the PDF, retry processing, or explicitly resend to the original buyer. Other users and Guest cannot use these APIs.
- PDF/email processing happens after the signed handover commits. A PDF or email-queue failure cannot undo collection. One Email Queue entry and its Queued marker commit together; the five-minute job retries Pending/Failed receipts. Frappe's normal SMTP retry handles mail transport failures. Explicit resends reuse the same evidence/PDF and are counted. Queued means accepted by Email Queue, not confirmed inbox delivery.
- Cancelling a delivery execution marks its receipts Superseded and blocks their unsent/error queue entries. An already sent email cannot be recalled. The original evidence remains available for audit, and amended valid evidence gets its own receipt.

### Deployment dependencies and acceptance

Deploy **both** the Webshop changes and the small Bloominggarden customer-POD-handler adapter, then migrate. New Hospice successful delivery submissions are guarded until the delivery app supports per-order email handlers; this prevents a mixed-version rollout from falling back to the shared customer contact. Ordinary delivery emails continue through the existing module.

Migration adds the handover/item doctypes and records **Signed Delivery Receipts From** once. The scheduler can recover missed delivery jobs after this cutoff; it does not automatically email historical deliveries. Existing payments, invoices, shared tax templates and Stripe settings are not changed.

In UAT, verify the actual Desk signature control on a tablet, one complete signed pickup with a new Delivery Note, another reusing an existing note, duplicate confirmation, a PDF/mail retry, resend, and an actual driver signature/submit. Check both recipients on a combined-order delivery. Confirm the generated PDF and SMTP delivery using the deployed PDF engine before production rollout.

## Validation performed locally

- 23 campaign integration tests with real ERP orders, invoices, payments, Pick Lists, Delivery Notes and stock movements; Stripe and email delivery are intercepted. These include item-template VAT extraction, the gross delivery threshold, contact-only pickup, shared-address isolation, readiness email deduplication, partial/cancelled picking and dispatch, and rejection of unsigned collection.
- 18 existing checkout integration tests, including refunds, accounting, stock checks and webhook signature validation.
- 19 checkout-validation, Hospice configuration and fulfilment calculation tests.
- Real local Frappe HTTP checks: both pages return 200 with private/no-store headers; Guest address/order access, unknown tracking tokens and Guest configuration return 403.
- Chrome desktop/mobile tests: catalogue, delivery/pickup selection, address visibility/validation, review, edit/cancel and tracking display; no JavaScript errors or mobile horizontal overflow.
- 19 signed-handover integration tests use actual local stock postings, immutable handover records, private File attachments and receipt queue markers. They cover duplicates, draft/submitted note reuse, rollback, invalid signatures, cancelled payments, shared-note isolation, email retry/resend and PDF attachment integrity. Payment, SMTP and PDF conversion are intercepted. Desk-script tests cover the signature dialog, acknowledgement, permission checks, escaped product text and retry behaviour. Synthetic pickup/delivery PDFs are rendered for visual review. The 22 Hospice unit tests cover existing configuration/progress, signature validation, cutoff initialization and the delivery-email adapter.

The isolated bench has no Delivery Execution tables, so the absence of a POD is simulated for dispatch tests and submitted driver evidence is supplied at that boundary for receipt tests. Existing Bloominggarden POD logic is reused. Receipt layout previews use Chromium; production uses the site's existing Frappe/wkhtmltopdf engine. The actual driver workflow, Desk signature control, production PDF engine and SMTP delivery still require deployed-site acceptance. No external Stripe or SMTP calls are performed by these tests.

## Revocation / rollback

Disable `hospice_enabled` to stop new campaign checkouts. Do not disable existing Stripe reconciliation for customers who already started payment. A System Manager can POST `webshop.callus_storefront.hospice.revoke_tracking` with `checkout_name` to revoke an individual tracking link. Preserve accounting records and the dedicated customer.
