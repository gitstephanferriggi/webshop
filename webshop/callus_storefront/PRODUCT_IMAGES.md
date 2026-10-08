# Product images

Changing an existing Item's main image updates its Website Item through the
normal save/permission path and regenerates its thumbnail. Other Item edits do
not overwrite a separately chosen website photo. Private images are not made
public automatically. Clearing the Item image clears the website main image.
Existing website images are not bulk overwritten during migration.

On Website Item, use **Product gallery** to choose additional public image
uploads, enter optional image descriptions, and drag rows into display order.
Tick **Hide from website** to hide a gallery photo, or remove its row. Neither deletes the attachment. The main image is controlled separately by the main image field.
The main image appears first; duplicate URLs are displayed once. There is a
20-photo limit. The attachment import script adds public Item photos; legacy slideshows are not imported.
Existing Item photos can be selected through the attachment picker.

The migration installs Callus Product Image and the Website Item table field,
and extends only Marcella's existing Website Item server/client allowlists.
The after-migrate hook maintains that setup; unrelated live rule changes are
preserved. Builder exports include the gallery data and shared responsive UI.

Deploy to UAT first. As Marcella, change the main image of a disposable Item;
check its website thumbnail. Add two public gallery photos, reorder and remove
one, and check mobile/desktop thumbnails. Verify a private photo is rejected and
protected names remain blocked. Check an anonymous product page. No sales,
payments, stock updates or production data changes are needed for acceptance.

Local checks: product image unit tests, catalogue/gallery data tests, marketing
permission regressions, JavaScript gallery checks and syntax check. These do not
replace the authenticated UAT acceptance checks above.

## Import existing Item attachments

After deploying and migrating the site, preview the import:

```sh
bench --site SITE execute webshop.callus_storefront.product_images.import_item_attachments
```

Then apply it:

```sh
bench --site SITE execute webshop.callus_storefront.product_images.import_item_attachments --kwargs '{"dry_run": false}'
```

The command is restricted to Administrator/System Manager. It imports existing
public Item image attachments for Website Items (including unpublished ones),
without changing publication, prices, stock or attachment privacy. It uses normal
Website Item saves and reports per-product errors. Review any errors before
considering the import complete. The preview writes no product changes.

A hidden, read-only URL history prevents subsequent imports from restoring removed
rows; hidden rows retain their checkbox and caption. New URLs can be imported by
running the command again. Rows past the 20-photo limit remain eligible for a
later run. Import is explicitly run, not scheduled and not run on every deployment.
Marcella can edit gallery rows and hide flags but cannot change import history.
