def ensure_product_flag():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({'Website Item': [{
        'fieldname': 'custom_bolt_enabled', 'label': 'Publish on Bolt Food',
        'fieldtype': 'Check', 'default': '0', 'insert_after': 'published',
        'in_standard_filter': 1,
        'description': 'Include this product in the Bolt Food catalogue independently of website publication. Changes take effect on the next successful synchronisation.'
    }]}, update=True)


def ensure_operations_roles():
    import frappe
    for role in ('Bolt Order Operator', 'Bolt Order Manager'):
        if not frappe.db.exists('Role', role):
            frappe.get_doc({'doctype': 'Role', 'role_name': role, 'desk_access': 1}).insert(ignore_permissions=True)
    # Roles are intentionally not assigned to any user by migration.
