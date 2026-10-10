import frappe

no_cache = 1

def get_context(context):
    from frappe.sessions import get_csrf_token
    context.no_cache = 1
    context.csrf_token = get_csrf_token()
