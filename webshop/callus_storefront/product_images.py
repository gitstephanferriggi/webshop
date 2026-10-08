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
        'description': 'Choose public photos to show after the main image. Drag rows to reorder; remove rows to hide photos. Item attachments are not added automatically.'
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
