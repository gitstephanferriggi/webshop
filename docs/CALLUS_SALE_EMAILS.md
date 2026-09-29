# Sale notifications and Malta delivery

## Existing setup found

Production has two enabled Sales Invoice / Submit email Notifications:

- `New Website Order - Customer`: originally sent to both invoice `owner` and `contact_email`.
- `Website Sales Notifications Internally`: sent to the existing `Leads Email` role and existing CC/BCC recipients.

Both originally matched `customer_group == "Website"`, including return invoices. The refreshed condition requires submitted, non-return Website invoices. The customer recipient is `contact_email` only. Production business recipients are preserved by the installer. Existing invoice PDF attachments and sender settings are preserved.

The active shipping rule is `Delivery Fee - Orders Under 35 Euros`. It applies to Malta, Selling, and **Net Total** in company currency:

| Items subtotal before VAT | Delivery |
| --- | --- |
| €0.01 through €35.00 inclusive | €5.00 |
| More than €35.00 | €0.00 |

There is also an older disabled `Web Delivery Fee` rule. It is not selected. The active rule is preserved without changing its accounting account, cost centre, threshold or fee. Collection has no shipping rule and remains free. With an 18% VAT-inclusive price, €41.30 corresponds to the €35.00 net boundary and still attracts the fee; €41.31 crosses it after ERP rounding. Actual item taxes remain authoritative.

## Email changes

The reusable Jinja email template uses the official logo, forest green, cream background, accessible text and inline table layouts. Customer and business messages include the order/invoice reference, quantities, item codes, totals, separate delivery charge and the appropriate collection/delivery instructions. Buyer text is escaped. Delivery addresses are rendered from structured Address fields.

The customer message no longer assumes every payment was by credit card or promises an unconfirmed 2–3 working days. Collection customers are asked to wait until their order is ready. The team message includes contact details, a picking list, fulfilment instructions and a staff order link. It asks staff to check the payment record rather than assuming manually submitted invoices are paid.

The existing invoice-submit trigger is reused. The custom checkout only creates that invoice after verified Stripe payment. Its existing callback idempotency means replaying a callback does not create another invoice or notification. Return invoices no longer send new-order emails.

## Source and deployment

- `webshop/callus_storefront/emails/order.html`: shared message layout.
- `webshop/callus_storefront/notifications.py`: renders the two variants, updates existing Notifications explicitly, and provides a manager-only delivery selector.
- `checkout.py`: includes the actual ERP shipping charge separately in the quote summary.
- Builder page data reads the existing rule for public delivery terms; no accounting details are exposed. Until the selected rule is configured, it can display the already-existing Malta rule as informational terms, without enabling delivery checkout.

After deployment, call the manager-only POST method `webshop.callus_storefront.notifications.configure_delivery` with `rule_name` equal to the existing active rule name. It validates company, selling type, enabled state and Malta coverage, then changes only `delivery_rule`. It cannot enable checkout or change payment credentials.

For notification installation, explicitly run `bench --site <target-site> execute webshop.callus_storefront.notifications.install --kwargs '{"enable": true}'` on the intended site after backing up the existing records. This preserves the business recipients already on that site, fixes customer recipients and selects the delivery rule. Do not copy the UAT database or its test recipient settings to production. No automatic migration enables notifications or SMTP.

## UAT state and limits

Both existing UAT Notification bodies are updated and enabled, but all recipient rules are temporarily replaced with the explicitly authorized test address; no role, customer, original CC or original BCC recipient remains in UAT. Unrelated notifications remain disabled. Two clearly labelled synthetic email previews were sent only to the tester. Original records are backed up outside the repository.

UAT background mail stays paused, and outgoing Email Account flags were restored after targeted preview sends. Thus automatic email delivery is not yet enabled. A controlled mail-release plan must exclude the copied production backlog before resuming mail.

UAT checkout was found disabled with no selected delivery rule. The direct API settings update is intentionally denied by the DocType permission model. The new manager-only selector must be deployed before activating the rule. Payment setup/activation remains separate; this release does not charge cards or enable production.

## Verification

Four focused local ERP integration tests pass:

1. Manager permission required for delivery selection; disabled rules rejected; payment settings unchanged.
2. €34.99, €35.00 and €35.01 net totals; equivalent 18% VAT-inclusive boundaries; collection stays free.
3. Actual invoice submission produces exactly two emails, repeat payment callbacks do not duplicate them, and refunds do not send preparation notices.
4. Fixed delivery fees and delivery variants of both email templates render against real ERP invoice data.

Thirteen catalogue/export tests pass. Desktop and 390px mobile email previews were visually checked, with no horizontal overflow. Inbox delivery is confirmed only to the mail server's Sent state; the recipient should inspect actual rendering in their mail client. Invoice-PDF styling is unchanged and was not part of the email redesign.
