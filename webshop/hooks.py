from . import __version__ as _version

app_name = "webshop"
app_title = "Webshop"
app_publisher = "Frappe Technologies Pvt. Ltd."
app_description = "Open Source eCommerce Platform"
app_email = "contact@frappe.io"
app_license = "GNU General Public License (v3)"
app_version = _version
required_apps = ["payments", "erpnext", "builder"]

web_include_css = "webshop-web.bundle.css"

web_include_js = "web.bundle.js"

after_install = "webshop.setup.install.after_install"
on_logout = "webshop.webshop.shopping_cart.utils.clear_cart_count"
on_session_creation = [
    "webshop.webshop.utils.portal.update_debtors_account",
    "webshop.webshop.shopping_cart.utils.set_cart_count",
]
update_website_context = [
    "webshop.webshop.shopping_cart.utils.update_website_context",
]

website_generators = ["Website Item", "Item Group"]

override_doctype_class = {
    "Payment Request": "webshop.webshop.doctype.override_doctype.payment_request.PaymentRequest",
    "Item Group": "webshop.webshop.doctype.override_doctype.item_group.WebshopItemGroup",
    "Item": "webshop.webshop.doctype.override_doctype.item.WebshopItem",
}

doctype_js = {
    "Callus Bolt Event": "public/js/bolt_review.js",
    "Callus Bolt Order": "public/js/bolt_review.js",
    "Sales Order": "public/js/hospice_sales_order.js",
    "Item": "public/js/override/item.js",
    "Homepage": "public/js/override/homepage.js",
}

doc_events = {
    "Sales Order": {
        "validate": "webshop.callus_storefront.hospice_fulfilment.validate_preparation",
        "before_update_after_submit": "webshop.callus_storefront.hospice_fulfilment.validate_preparation",
        "on_update": "webshop.callus_storefront.hospice_fulfilment.on_order_change",
        "on_update_after_submit": "webshop.callus_storefront.hospice_fulfilment.on_order_change",
        "on_cancel": "webshop.callus_storefront.hospice_fulfilment.on_order_change",
    },
    "Callus Checkout": {"on_update": "webshop.callus_storefront.hospice_fulfilment.on_checkout_change"},
    "POS Closing Shift": {"before_submit": "webshop.bolt_integration.pos_sales.validate_closing"},
    "Website Item": {"validate": "webshop.callus_storefront.product_images.validate_gallery"},
    "Sales Invoice": {
        "validate": "webshop.callus_storefront.hospice_fulfilment.clear_linked_pickup_address",
        "before_submit": "webshop.callus_storefront.notifications.mark_website_invoice",
    },
    "Item": {
        "on_update": [
            "webshop.webshop.crud_events.item.update_website_item.execute",
            "webshop.webshop.crud_events.item.invalidate_item_variants_cache.execute",
        ],
        "before_rename": [
            "webshop.webshop.crud_events.item.validate_duplicate_website_item.execute",
        ],
        "after_rename": [
            "webshop.webshop.crud_events.item.invalidate_item_variants_cache.execute",
        ],
    },
    "Sales Taxes and Charges Template": {
        "on_update": [
            "webshop.webshop.doctype.webshop_settings.webshop_settings.validate_cart_settings",
        ],
    },
    "Quotation": {
        "validate": [
            "webshop.webshop.crud_events.quotation.validate_shopping_cart_items.execute",
        ],
    },
    "Price List": {
        "validate": [
            "webshop.webshop.crud_events.price_list.check_impact_on_cart.execute"
        ],
    },
    "Tax Rule": {
        "validate": [
            "webshop.webshop.crud_events.tax_rule.validate_use_for_cart.execute",
        ],
    },
}

# Linked document changes refresh the public and desk progress from the same facts.
for _doctype in ("Pick List", "Delivery Note", "Delivery Trip", "Delivery Execution"):
    doc_events[_doctype] = {
        event: "webshop.callus_storefront.hospice_fulfilment.on_fulfilment_change"
        for event in ("on_update", "on_submit", "on_update_after_submit", "on_cancel", "after_delete")
    }
doc_events["Delivery Note"]["validate"] = "webshop.callus_storefront.hospice_fulfilment.clear_linked_pickup_address"
doc_events["Delivery Note"]["before_cancel"] = "webshop.callus_storefront.hospice_collection.protect_signed_stock"
doc_events["Delivery Execution"]["before_submit"] = "webshop.callus_storefront.hospice_receipts.validate_delivery_signature"
doc_events["Delivery Execution"]["on_submit"] = [
    "webshop.callus_storefront.hospice_fulfilment.on_fulfilment_change",
    "webshop.callus_storefront.hospice_receipts.enqueue_delivery",
]
doc_events["Delivery Execution"]["on_cancel"] = [
    "webshop.callus_storefront.hospice_fulfilment.on_fulfilment_change",
    "webshop.callus_storefront.hospice_receipts.on_delivery_cancel",
]

# The delivery app consults these before using a customer's default contact email.
customer_pod_email_handlers = ["webshop.callus_storefront.hospice_receipts.handle_customer_pod_email"]

has_website_permission = {
    "Website Item": "webshop.webshop.doctype.website_item.website_item.has_website_permission_for_website_item",
    "Item Group": "webshop.webshop.doctype.website_item.website_item.has_website_permission_for_item_group",
}


add_to_apps_screen = [
    {
        "name": "webshop",
        "logo": "/assets/webshop/images/webshop_logo.png",
        "title": "Webshop",
    }
]

fixtures = [
    {
        "dt": "Website Category",
        "filters": [["name", "like", "All Website Categories"]],
    }
]

# Retries missed Stripe callbacks without depending on the customer return page.
scheduler_events = {"cron": {"* * * * *": ["webshop.bolt_integration.processing.process_pending", "webshop.bolt_integration.operations.flag_interrupted_actions"], "*/5 * * * *": ["webshop.callus_storefront.checkout.reconcile_pending", "webshop.callus_storefront.hospice.queue_pending_emails", "webshop.bolt_integration.sync.tick"]}}

# Marcella's account must not inherit unrelated access from All / Guest.
# Hooks return None for every other user and never grant permissions.
has_permission = {'*': 'webshop.callus_storefront.marketing_access.has_permission'}
permission_query_conditions = {'*': 'webshop.callus_storefront.marketing_access.permission_query'}

# A dedicated Bolt API identity can receive events but cannot access ERP documents.
auth_hooks = ['webshop.bolt_integration.webhooks.restrict_service_user']

# Keep the independent Bolt product selection field reproducible on site migration.
after_migrate = ["webshop.callus_storefront.hospice.setup", "webshop.callus_storefront.hospice_receipts.setup", "webshop.bolt_integration.setup.ensure_product_flag", "webshop.bolt_integration.setup.ensure_operations_roles", "webshop.callus_storefront.product_images.setup"]

# Public campaign responses must never be cached or embedded.
after_request = ["webshop.callus_storefront.hospice.private_response"]
