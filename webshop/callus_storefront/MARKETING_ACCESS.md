# Restricted marketing account

Account: marketing@callusgardencentre.com (Marcella).

The `Callus Marketing Editor` role permits existing Item reads/edits, Website Item
reads/edits/publication, Sales Order reads and Item Group selection. No standard
Item Manager, Website Manager or Sales User role should be assigned.

`marketing_site_rules.json` is the reproducible site configuration: server-side
field guards, immutable publication names, rename denial, website order filtering,
order-specific User Permissions and client form controls. Install these rules and
the role before enabling the account. Item.description is used for the requested
Item description; Website Item has separate short_description/web_long_description.
Only Item image, description and item_group are editable. Only Website Item image,
short description and long description are editable; publication may go from off
to on. New Website Items copy protected names and other values from the real Item.

The wildcard permission hooks in marketing_access.py additionally deny unrelated
records inherited through All/Guest permissions, both in lists and direct reads.
This is essential: UAT testing found inherited Sales Invoice access. The hooks
return None for all other users; existing staff permissions are unchanged.

The production account must remain disabled until these code hooks are deployed
and negative tests pass under Marcella's actual session. Test Item/Website Item
images, descriptions and categories, publication, names, price/stock fields, direct
nonwebsite order URLs, invoices, contacts, email templates, Builder and exports.
Use disposable UAT products; do not test forbidden edits on real production data.
Native User Permissions provide an additional Sales Order allowlist. Bootstrap it
from existing Callus Checkout.sales_order links before activation; the checkout
After Save script grants access for subsequent orders. Non-website orders must
remain inaccessible even when they belong to a website customer.

Local tests: `python3 -m unittest discover -s tests -p test_marketing_access.py`.
UAT field/access test records and deployment backups are in the project workspace
under outputs/marketing-access. Do not treat local hook tests as deployed checks.

Rollback: disable the user before removing any guard or restoring permissions.
Never enable the account with only the marketing role and client-side controls.
