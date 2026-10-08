"""Explicit public product galleries and Item-to-Website-Item image updates."""
import ast
import json
import re
from urllib.parse import urlsplit

import frappe

FIELD = 'custom_product_images'


def public_image(url):
    path = urlsplit(url or '').path
    return bool(url and url.startswith('/files/') and path.lower().endswith(
        ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')) and
        frappe.db.exists('File', {'file_url': url, 'is_private': 0}))


def validate_gallery(doc, method=None):
    rows = doc.get(FIELD) or []
    if len(rows) > 20:
        frappe.throw('Choose up to 20 additional product photos.')
    seen = set()
    for row in rows:
        if not public_image(row.image):
            frappe.throw('Gallery images must be public image uploads. Private attachments are not published automatically.')
        if row.image in seen:
            frappe.throw('This photo is already in the product gallery.')
        seen.add(row.image)


def sync_main_image(item, previous, website_item):
    if previous.get('image') == item.get('image'):
        return
    image = item.get('image') or ''
    # Never silently expose a private attachment or replace a public photo with
    # an unusable URL. Removing the main image intentionally clears the website.
    if image and not public_image(image):
        frappe.msgprint('The website photo was not updated: select a public image upload on the Item.')
        return
    web = frappe.get_doc('Website Item', website_item)
    if (web.website_image or '') != image:
        web.website_image = image
        web.save()  # Normal permissions, marketing guards and thumbnail generation.


def allow_gallery(script, client=False):
    """Extend only the existing allowlist; preserve all other live guard changes."""
    pattern = r'(const allowed\s*=\s*)(\[[^\n;]*\])' if client else r'(allowed\s*=\s*)(\[[^\n]*\])'
    match = re.search(pattern, script)
    if not match:
        frappe.throw('Cannot locate the marketing Website Item field allowlist.')
    fields = ast.literal_eval(match.group(2))
    if FIELD not in fields:
        fields.append(FIELD)
    return script[:match.start(2)] + json.dumps(fields) + script[match.end(2):]


def setup():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({'Website Item': [{
        'fieldname': FIELD, 'label': 'Product gallery', 'fieldtype': 'Table',
        'options': 'Callus Product Image', 'insert_after': 'website_image',
        'description': 'Public Item image attachments can be imported automatically. Drag rows to reorder. Tick Hide from website or remove a row to exclude it; repeat imports preserve your choice.'
    }, {
        'fieldname': 'custom_gallery_import_history', 'label': 'Gallery import history',
        'fieldtype': 'Long Text', 'hidden': 1, 'read_only': 1, 'no_copy': 1,
        'insert_after': FIELD,
        'description': 'Processed attachment URLs, retained to prevent deleted gallery rows being re-imported.'
    }]}, update=True)
    for dt, name, client in [
        ('Server Script', 'Callus Marketing - Website Item Fields', False),
        ('Client Script', 'Callus Marketing - Website Item Form', True),
    ]:
        if frappe.db.exists(dt, name):
            doc = frappe.get_doc(dt, name)
            updated = allow_gallery(doc.script, client)
            if updated != doc.script:
                doc.script = updated
                doc.save(ignore_permissions=True)


def plan_attachment_import(web, attachments):
    """Pure import plan. A processed URL stays processed after row removal."""
    history = set(json.loads(web.get('custom_gallery_import_history') or '[]'))
    existing = {row.get('image') for row in (web.get(FIELD) or [])}
    processed = history | existing
    additions = []
    remaining = max(0, 20 - len(web.get(FIELD) or []))
    for attachment in attachments:
        url = attachment.get('file_url') or ''
        if attachment.get('is_private') or not url.startswith('/files/'):
            continue
        if not urlsplit(url).path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')):
            continue
        if url in processed:
            continue
        if url == web.get('website_image'):
            processed.add(url)
            continue
        if len(additions) >= remaining:
            continue  # Not processed: a later run can fill newly available slots.
        additions.append({'image': url, 'caption': '', 'hide_from_website': 0})
        processed.add(url)
    return additions, json.dumps(sorted(processed))


def import_item_attachments(dry_run=True):
    """Run via bench execute; dry-run by default. Never changes attachment privacy.

    Run explicitly after migration. No import on every save or migration, so a
    deployment cannot silently publish new photos. Re-runs add new URLs only.
    """
    if frappe.session.user != 'Administrator' and 'System Manager' not in frappe.get_roles():
        frappe.throw('Only a System Manager may import product attachments.', frappe.PermissionError)
    dry_run = frappe.utils.cint(dry_run)
    summary = {'dry_run': bool(dry_run), 'products_changed': 0, 'images_added': 0, 'errors': []}
    for name in frappe.get_all('Website Item', pluck='name', order_by='name'):
        frappe.db.savepoint('gallery_import_product')
        try:
            web = frappe.get_doc('Website Item', name)
            attachments = frappe.get_all('File', filters={
                'attached_to_doctype': 'Item', 'attached_to_name': web.item_code, 'is_private': 0,
            }, fields=['file_url', 'is_private'], order_by='creation asc, name asc')
            additions, history = plan_attachment_import(web, attachments)
            changed = history != (web.get('custom_gallery_import_history') or '[]')
            if not dry_run and changed:
                for row in additions:
                    web.append(FIELD, row)
                web.custom_gallery_import_history = history
                web.save()  # Preserve standard validation, permissions and cache invalidation.
            summary['products_changed'] += int(bool(additions))
            summary['images_added'] += len(additions)
        except Exception:
            frappe.db.rollback(save_point='gallery_import_product')
            summary['errors'].append(name)
            frappe.log_error(title='Product gallery import: ' + name)
    return summary
