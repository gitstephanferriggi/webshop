# Callus storefront — checkout candidate 2

This release adds a server-backed guest checkout to the Callus storefront. **The new backend is locally verified, but must be deployed, configured and verified on UAT before customer use.** See [CHECKOUT_RELEASE.md](CHECKOUT_RELEASE.md) for the activation and acceptance procedure.

## Delivered

- Fifteen Builder pages: homepage, catalogue (including the legacy `/all-products` entry), categories, category detail, collections, collection detail, product detail, basket, guest checkout preview, saved favourites, account entry, contact, delivery help and privacy preview.
- Editable Builder homepage text and sections, shared CSS and JavaScript records, and an original garden-inspired hero asset. Dynamic catalogue grids use the shared storefront script.
- A live, read-only catalogue containing published, active Website Items. Public retail prices come from the configured price list, excluding customer-, supplier- and batch-specific prices and prices outside their validity period. Stock uses the item's website warehouse and deducts reservations. A missing price is never presented as zero.
- Customer favourites ranked by positive quantities on submitted, non-return Sales Invoices over the previous 90 days. POS Invoice quantities are not added separately, avoiding double counting consolidated sales. These are gross sales rankings, not net returns-adjusted sales or margin rankings. Volumes and revenue are not published.
- Available products promoted on the homepage, with a separate curated selection of statement plants. No invented reviews, discounts, delivery promises or sales counts.
- Responsive navigation, text search, category filtering, availability and price filters, sorting, pagination, saved products and a browser-local basket.

## Important boundaries

The checkout creates a separate guest Customer, contact, billing address and draft Sales Order from validated product codes and quantities. ERPNext calculates prices, taxes and delivery. The customer reviews the result before opening Stripe Checkout. Verified payment creates a Sales Invoice and Payment Entry; a full refund of an undelivered order creates a credit note and outward Payment Entry. The shop handles physical fulfilment separately.

Checkout is disabled by default through the new **Callus Checkout Settings**. Credentials, mode, webhook secret, exact site URL and enablement are site settings and are never committed or automatically enabled by a migration. Existing legacy checkout settings remain unchanged. Browser basket totals are estimates only. The server quote is valid for 30 minutes; its total is fixed during that quote. Changing prices afterward does not silently increase the payment.

Shop / Shop Pay identity integration is not implemented. Existing Frappe sign-in is linked from the account entry page; that existing sign-in form has not been redesigned. Production privacy/terms, delivery charges, fulfilment promises and returns policy need merchant approval before launch. The current help pages make no unverified delivery or refund commitments.

The browsing price model does not claim to implement quantity-dependent/customer-specific pricing rules. ERPNext must be authoritative during transaction creation. Existing legacy product URLs retain their existing ERPNext handling; an SEO redirect plan is still required before production rollout.

## Source and deterministic build

Source files:

- `webshop/callus_storefront/build.py`: generates Builder records.
- `webshop/callus_storefront/data_script.py`: restricted, read-only page-data script.
- `webshop/callus_storefront/release.json`: fixed release identity, timestamp and verified versions.
- `webshop/public/callus/storefront.css` and `storefront.js`: shared styling and interactions.
- `webshop/public/callus/garden-hero.webp`: generated editorial hero.
- `webshop/builder_files/`: generated page and script records consumed by Builder.

Regenerate with `python3 webshop/callus_storefront/build.py`. Change the release timestamp deliberately for a new release, not on every build. The fixed timestamp prevents a routine migration from treating unchanged files as newly modified and overwriting more recent Builder edits. Preserve and review any UAT Builder edits before regeneration.

Builder's standard importer reads the page and script records; the page data script is embedded in JSON as well as stored next to it for review. Record names are stable. Before importing onto an existing preview, align any previously generated page IDs with the source names rather than creating duplicate routes. UAT IDs were aligned as part of this release.

## Deployment

1. Take a site backup and export the existing Builder pages, scripts and relevant homepage settings.
2. Deploy the reviewed fork revision to **UAT only** in Frappe Cloud. Its update workflow supports selecting which sites receive a release. A common bench group does not itself require production to be selected. Do not use a shared in-place update that would update production unintentionally.
3. Verify app revisions against `release.json`; version labels alone are not exact commit locks. Record the actual Frappe Cloud app commit IDs before production approval.
4. Import the records using Builder's standard-page sync during migration. Verify all 15 routes and shared scripts. On UAT, apply `disable_indexing = 1` to the pages and keep checkout, outgoing email and scheduled activity disabled.
5. Set Builder Settings `home_page = shop`, `disable_auto_dark_mode = 1`; set Website Settings `home_page = shop`. These are explicit site settings, not automatic shared bench modifications.
6. Reapply on a fresh isolated copy of production before approving a production release. Verify there are exactly 15 distinct storefront routes, with no duplicate pages or scripts. The API-based UAT apply was repeated without duplication; a fresh-copy app deployment rehearsal is still outstanding.
7. Never restore the UAT database over production. Keep environment credentials, payment mode, mail settings and live business data out of the portable release.

The UAT API deployment uses `/files/callus-garden-hero.webp` because the app asset is not deployed yet; the portable source uses `/assets/webshop/callus/garden-hero.webp`. No UAT hostname or credential is embedded in the source.

## Recovery

Revert homepage settings to their recorded prior values and restore only the backed-up Builder pages/scripts. Unpublish newly introduced preview pages rather than deleting business records. Keep the older storefront available until acceptance. Rolling back app code may also require restoring the corresponding page records because Builder can preserve newer database modifications. Do not restore an old database over newer orders.

## Verification completed

- 13 catalogue/export regression tests cover published/active filtering, warehouse scope, reservations, price validity, private prices, hidden guest pricing, login-required catalogues, disabled shops, missing prices, private sales volumes, correct Builder script types and the disabled transaction boundary.
- JavaScript syntax validation and Git whitespace checks pass.
- Thirty UAT routes returned HTTP 200 with the new storefront and no traceback. All checked UAT pages had noindex.
- Desktop browser checks: search, stock filter, ascending price sort, product detail, saving a favourite, quantity two in basket with correct subtotal, and guest checkout form validation/review.
- Mobile checks at 390px: menu, category/filter interaction, product detail, unavailable-item handling and empty search. Narrow basket at 320px has no horizontal overflow.
- Checkout and the scheduler setting remain zero; no enabled outgoing email accounts or email notifications were found at final verification.

The earlier visual tests did not create orders. The checkout-candidate tests create synthetic orders, invoices, payments and credit notes only in a separate local database, with Stripe calls simulated. Real Stripe credentials, hosted checkout/SCA, callbacks from Stripe and the deployed UAT version remain to be verified. No real charge or refund has been made.

## Design asset provenance

The official transparent Callus logo is bundled unchanged as `webshop/public/callus/callus-logo.png`, sourced from https://www.callusgardencentre.com/wp-content/uploads/2023/05/Logo-Transparent.png. It replaces the text wordmark in all 15 page headers. The existing storefront palette is unchanged.


The hero is a generated editorial scene, not a photograph of the actual premises or a promise that pictured pots are sold as a set. Product photography is from the actual catalogue.

Generated with the built-in image-generation tool; web asset: `webshop/public/callus/garden-hero.webp`. Prompt:

> Create a premium editorial photograph for a Mediterranean garden centre ecommerce website hero, wide landscape 1536x1024. A quiet Maltese limestone courtyard with warm sand coloured textured wall, sunlit terracotta pots containing lush sculptural strelitzia leaves, a small olive tree, rosemary and basil, fern and monstera. Natural plants, imperfect terracotta textures, morning sunshine coming from upper left casting beautiful soft organic leaf shadows on stone. Composition: tall foliage predominantly on right half and middle, terracotta pots foreground right, a little empty stone wall left. Close crop, abundant real botanical detail, muted sophisticated olive green and warm cream colour palette, rich deep greens, architectural digest photography, 50mm lens. No people, no text, no logos, no graphics, no artificial oversaturation. This is an inspirational garden scene, not a product photograph.
