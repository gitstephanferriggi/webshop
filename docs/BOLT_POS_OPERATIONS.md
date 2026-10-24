# Bolt operations in POS Awesome — development release

This release is disabled by default. No production configuration is changed by migration.
Deploy Webshop and POS Awesome together to UAT before enabling it. Do not enable
until Bolt has activated two-way order acceptance/ready permissions for the test provider.

## Configuration

1. Migrate Webshop so the new fields and unassigned Bolt Order Operator / Bolt Order Manager roles exist.
2. In Callus Bolt Settings, retain the exact UAT hostname binding and staging credentials.
3. Select the dedicated Bolt customer, inclusive VAT template, selling price list and company.
4. Select a POS Profile and its warehouse (Garden Center - BGL). Both company and warehouse must match.
5. Assign staff explicitly to that POS Profile's applicable users and the Bolt role.
   Managers may reject orders and take over picking. System Managers may operate the profile.
6. Turn off Submit Sales Orders and Invoices, then turn on Process incoming orders and Enable POS Bolt operations.
7. Start POS using this profile. Choose Bolt Orders from Quick Actions, enable sound,
   test volume on the physical terminal and keep it awake with the application open.

Each cashier terminal needs an initial click to unlock browser audio. The application
cannot guarantee sound with the computer asleep, the tab closed or system audio muted.
The shared acknowledgement stops all terminals at their next refresh (normally five seconds).
Acknowledgement is not acceptance. Orders are scoped by provider, environment, site and profile.

## Flow

New order -> acknowledge -> accept -> pick/scan -> save quantities -> ready -> courier handover.
Acceptance submits the ERP Sales Order and requires the cashier's own open shift on the configured profile.
Handover records exactly one fully paid invoice using the dedicated Bolt Food tender and that cashier's
current open shift. It follows the profile's invoice type: POS Invoice is included in standard closing
and consolidated to a Sales Invoice there (including stock/GL posting); Sales Invoice mode posts immediately.
The payment debits a dedicated EUR asset clearing account for later reconciliation of Bolt settlements.
It is not physical cash, does not trigger a new charge, and does not automatically book commissions or refunds.
A posted cancellation requires manager return/refund review; it never silently cancels a paid POS invoice.
Closing is serialized with handover on the opening-shift record. If invoices have changed since the closing
screen was opened, submission requires a refresh rather than silently omitting the sale.

### Configuration before testing

Create an enabled **Bolt Food** Mode of Payment of type **General**, mapped to a dedicated EUR asset
clearing ledger for Blooming Garden Ltd. Add it to Siggiewi Shop's payment methods without making it the
default or the cash mode. Select it in **Callus Bolt Settings → Bolt payment method**. Both backend schema
changes must be migrated before testing. Do not enable production automatically.
Cashiers must open their own Siggiewi Shop shift. An order remains assigned to its picker; a manager can
use the existing takeover flow if another cashier must hand it over. The completing cashier's active shift
receives the tender, not the webhook account or an arbitrary open shift.

The initial release supports whole-piece EUR baskets, online card payment and Bolt-courier
delivery. Cash, customer pickup, own delivery and unsupported discounts/fees need review.
Managers can reduce quantities/remove products or choose published Bolt replacements at
an equal or lower unit price. The preview shows the expected total/reduction and requires
an explicit confirmation before calling markOrderWithItemsAsReadyForPickUp. Manual price
changes and higher-price replacements are blocked; the v2 price-adjustment API is not used. It never calls markOrderAsPickedUp or markOrderAsDelivered for Bolt delivery.
Collected means staff recorded handover; it is not a claim of customer delivery confirmation.
The available order_update contract only specifies order_preparing. Courier-picked-up callbacks record Bolt confirmation separately from internal handover,
without creating a second invoice. Final customer-delivery confirmation is not inferred.

Remote calls are durably marked Sending before dispatch. Duplicate clicks, stale versions,
wrong pickers and retries of uncertain outcomes are blocked. After three minutes an interrupted
request becomes Needs attention. Errors do not cause blind remote retries. Managers must
reconcile uncertain remote states with Bolt; uncertain acceptance/ready outcomes are not inferred from a basket read.
For a confirmed adjusted-ready request, Check final basket again retries only the read and
ERP reconciliation, never the refund-triggering action. A mismatched basket blocks handover. Report a problem holds the order for manager intervention. Resume after resolving problem
restores only a staff-reported hold, never an unknown remote result or cancelled order. Use the
ERP/Bolt support workflow for accepted-order cancellations and stock-posted returns.

Existing imported orders are not automatically enrolled. Verified new callbacks are processed
by an after-commit job, with a one-minute durable inbox fallback. Invalid imports stay visible
as a review-event count in the workspace and detailed errors in the restricted event log.

## Validation and release gate

Local: 94 Bolt unit tests; POS queue/alarm tests; TypeScript check and Vite build.
The local ERP integration test verifies amendment, inclusive VAT, final invoice, stock
deduction exactly once after closing consolidation, a separate Bolt tender, cashier attribution and repeat handover idempotency. All database writes
are rolled back. Imported customer Server Scripts (disabled on the local bench) are excluded
from that process; standard ERP hooks run. Those scripts still require UAT validation.
Still required before operational use: migrate UAT; real role/profile access tests; two-terminal
alarm/acknowledgement and scanner checks; real Bolt accept/ready calls; controlled inventory and
accounting test covering positive/negative stock, valuation, inclusive taxes, duplicate handover,
concurrent cancellation, interrupted dispatch and permissions revoked mid-session. Verify existing
POS invoice/return/closing and website notifications are unaffected. No live end-to-end claim
is made by the unit tests. Do not enable production based on the local build alone.

## Store controls and adjusted accounting

Manager-only Accept new orders and Pause new orders require on-screen confirmation.
Pause omits resume_at, so it lasts until manually reopened. The display distinguishes the
last API request outcome from the last status received by webhook. Sending/Review store
requests are not blindly repeated; HTTP 304 is an acknowledged no-change response.

After Bolt confirms an adjusted-ready request, the integration retrieves getOrderBasket.
Order ID, quantities, SKU set, unit prices, selling units, line totals and final total must
match the approved adjustment. Only then is the original submitted Sales Order cancelled
and amended. The amended order and final amount are saved together. The original receipt
hash remains unchanged for duplicate detection. Invoice/stock posting uses the amended
order at handover. Failed reconciliation leaves a visible hold and permits read-only retry.
No direct Stripe/refund call is made by ERP; Bolt owns the customer refund.

## Webhooks to register after UAT deployment

Base: `https://callusuat.f.frappe.cloud/api/method/webshop.bolt_integration.webhooks.`
POST suffixes: `new_order`, `cancel_order`, `order_update`, `provider_status`,
`courier_details`, `courier_picked_up`. HTTP Basic uses the dedicated webhook credentials,
not an administrator's API token. `health` is GET. Existing route confinement, provider/
host checks and durable duplicate handling apply to the new pickup callback as well.

Suggested Webshop commit: `feat(bolt): add POS operations, adjusted picking and courier webhooks`

### Bolt selling price markup

`Callus Bolt Settings → Bolt Price Markup (%)` defaults to 20. Catalogue snapshots
apply this once to the configured gross EUR Item Price and round half-up to two
decimal places. The source Item Price, website and normal POS prices are unchanged.
Zero explicitly disables the markup; negative or non-finite values are rejected.
Replacement choices use the same catalogue snapshot and therefore the same markup.
Incoming orders, adjustments and invoices retain Bolt's verified charged prices;
never apply the percentage again when importing a sale.

After migration, verify the percentage in UAT and run a fresh catalogue/price sync.
An already-running sync retains its saved snapshot until the next sync cycle.
Existing orders retain their original price. Production integration remains disabled
until separately enabled; deploying code alone does not publish new prices there.

### Manager review resolution

System Managers can open a **Callus Bolt Event** or **Callus Bolt Order** in Desk
and use **Resolve review**, supplying a reason. No general write permission is
added. The server checks the configured hostname/provider and records the user,
reason and verified return references in a Comment.

Historical synthetic Staging events may be ignored; linked orders must already
be cancelled. Unlinked live events and events for unresolved sales are blocked.
The original event payload/error is retained, and no event is replayed.

Cancelled orders require a verified cancellation webhook. Posted sales require
submitted full returns matching customer, company, currency, amount, item stock
quantities and warehouses. POS returns must reverse the original tender/account
and be consolidated into submitted credit notes against the original consolidated
invoice. **Close the return shift first.** Unfulfilled, unbilled Sales Orders with verified returns are closed through
the standard permission-checked controller, preserving invoice links. Orders
without posted sales are cancelled normally. No external Bolt
refund request is made. The action then marks the order Cancelled, removing it
from the active queue while retaining its history.
