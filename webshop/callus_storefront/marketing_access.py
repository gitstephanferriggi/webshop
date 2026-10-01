"""Additional deny rules for the restricted marketing account.

Normal ERPNext permissions still apply: these hooks never grant permission.
The site-level field guards and role configuration are installed separately.
"""
import frappe

MARKETING_USER = 'marketing@callusgardencentre.com'
PRODUCTS = {'Item', 'Website Item'}
READ_ACTIONS = {'read', 'select'}
REFERENCE_TYPES = {'Item Group', 'UOM', 'Country', 'Language'}
WEBSITE_ORDERS = (
    'EXISTS (SELECT 1 FROM `tabCallus Checkout` cc '
    'WHERE cc.sales_order = `tabSales Order`.name)'
)


def restricted(user=None):
    return (user or frappe.session.user) == MARKETING_USER


def permission_query(user=None, doctype=None):
    """Filter every list, including doctypes inherited through All/Guest roles."""
    if not restricted(user):
        return None
    if doctype in PRODUCTS | REFERENCE_TYPES:
        return None
    if doctype == 'Sales Order':
        return WEBSITE_ORDERS
    if doctype == 'User':
        return '`tabUser`.name = ' + frappe.db.escape(MARKETING_USER)
    if doctype == 'File':
        return (
            "(`tabFile`.attached_to_doctype IN ('Item', 'Website Item') OR "
            "(`tabFile`.owner = " + frappe.db.escape(MARKETING_USER) +
            " AND COALESCE(`tabFile`.attached_to_doctype, '') = ''))"
        )
    # Framework metadata is not business data; native role permissions still apply.
    if doctype in {'DocType', 'DocField', 'Workspace', 'Module Def'}:
        return None
    return '1=0'


def has_permission(doc, ptype, user=None, **kwargs):
    """Block direct URLs/API reads as well as writes to unrelated documents."""
    if not restricted(user):
        return None
    dt = doc.doctype
    if dt in PRODUCTS:
        allowed = READ_ACTIONS | {'write'}
        if dt == 'Website Item':
            allowed.add('create')
        return None if ptype in allowed else False
    if dt == 'Sales Order':
        if ptype not in READ_ACTIONS:
            return False
        return None if frappe.db.exists('Callus Checkout', {'sales_order': doc.name}) else False
    if dt in REFERENCE_TYPES | {'DocType', 'DocField', 'Workspace', 'Module Def'}:
        return None if ptype in READ_ACTIONS else False
    if dt == 'User':
        return None if doc.name == MARKETING_USER and ptype in READ_ACTIONS else False
    if dt == 'File':
        target = doc.get('attached_to_doctype')
        own = doc.owner == MARKETING_USER
        if target not in PRODUCTS and not (not target and own):
            return False
        if ptype in READ_ACTIONS:
            return None
        if own and ptype in {'create', 'write', 'delete'}:
            return None
        return False
    return False
