# VAT-inclusive website and POS orders

Callus Checkout Settings → Website Prices Include VAT controls standard guest
checkout and the website shopping cart, including customer price lists. The
upgrade enables it only when the setting has never been saved; an explicit zero
is preserved. Disabled Callus checkout and other companies are unaffected.

The shared website VAT helper marks percentage tax rows as included in the item
rate. ERPNext and Item Tax Templates still determine rates/accounts, including
zero/reduced VAT. Fixed shipping charges remain separate. Hospice continues to
use inclusive product and delivery-service prices and its gross delivery threshold.

Website cart quotations, Sales Orders, payment amounts and mapped invoices must
agree on the final gross total. A draft prepared under obsolete VAT flags cannot
start a new payment: the customer must start a fresh checkout. Existing Stripe
sessions/payment reconciliation retain their original amounts.

POS Awesome separately persists the POS Profile on Quotations, Sales Orders and
Delivery Notes. It applies that profile's tax policy at creation and conversion,
including offline quotation retries, and guards the gross quotation/order total.

Deploy **Webshop** and **POS Awesome**, including database migration. The website
setting lives in Callus Checkout Settings; the POS policy remains on POS Profile.

This release changes future creation/conversion. Historical submitted invoices,
payments and refunds are not automatically repriced. Review paid historical
orders before issuing any credit or refund. Unpaid drafts with old VAT flags are
blocked from starting a new payment until the customer creates a fresh basket.
