# Product images

Changing an existing Item's main image updates its Website Item through the
normal save/permission path and regenerates its thumbnail. Other Item edits do
not overwrite a separately chosen website photo. Private images are not made
public automatically. Clearing the Item image clears the website main image.
Existing website images are not bulk overwritten during migration.

On Website Item, use **Product gallery** to choose additional public image
uploads, enter optional image descriptions, and drag rows into display order.
Remove a row to remove that photo from the storefront without deleting the file.
The main image appears first; duplicate URLs are displayed once. There is a
20-photo limit. Item attachments and legacy slideshows are not auto-published.
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
