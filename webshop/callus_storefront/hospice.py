"""Opt-in public Hospice campaign. Never expose shared Customer address/order lists."""
import json
import secrets
import time
from datetime import timedelta
from email.utils import formataddr
from pathlib import Path

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import getdate, nowdate, get_url, validate_email_address

from webshop.callus_storefront import checkout
from webshop.callus_storefront.checkout_validation import checkout_id
from webshop.callus_storefront.notifications import BUSINESS

DONATION = "Your purchase supports Hospice Malta through a donation from Callus Garden Centre."
CUSTOMER_NAME = "Cash Sales - Hospice Malta"


def clean_buyer(buyer, raw):
    for key, maximum in (("company", 140), ("company_vat", 40), ("instructions", 500)):
        value = raw.get(key, "")
        if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
            raise ValueError("Please check your " + key.replace("_", " ") + ".")
        buyer[key] = value.strip()
    return buyer


def campaign_settings():
    settings = checkout._settings()
    if not settings.get("hospice_enabled"):
        frappe.throw("Hospice ordering is not available yet.")
    if not settings.hospice_customer or not settings.hospice_items:
        frappe.throw("Hospice ordering needs configuration. Please contact Callus.")
    customer = frappe.get_doc("Customer", settings.hospice_customer)
    if customer.disabled or customer.customer_name != CUSTOMER_NAME:
        frappe.throw("The Hospice cash customer needs review.")
    warehouse = frappe.get_doc("Warehouse", settings.hospice_warehouse)
    shop = frappe.get_cached_doc("Webshop Settings")
    if warehouse.disabled or warehouse.is_group or warehouse.company != shop.company:
        frappe.throw("The Hospice warehouse needs review.")
    return settings


def validate_selection(items, settings):
    allowed = {row.item_code for row in settings.hospice_items}
    if any(row["id"] not in allowed for row in items):
        frappe.throw("A product is not part of the Hospice collection. Please refresh the page.")


def decorate_order(order, buyer):
    # The buyer's company is an order snapshot, never the shared Customer's identity.
    order.custom_hospice_order = 1
    order.custom_hospice_buyer_company = buyer.get("company", "")
    order.custom_hospice_buyer_vat = buyer.get("company_vat", "")
    order.custom_hospice_instructions = buyer.get("instructions", "")
    order.custom_hospice_preparation = "Awaiting preparation"
    order.custom_hospice_fulfilment = "Pickup" if buyer["delivery"] == "collection" else "Delivery"
    order.custom_hospice_status = "Awaiting payment"
    date = getdate(nowdate())
    holiday_list = frappe.db.get_value("Company", order.company, "default_holiday_list")
    holidays = {getdate(row) for row in frappe.get_all("Holiday", filters={"parent":holiday_list}, pluck="holiday_date")} if holiday_list else set()
    remaining = 5
    while remaining:
        date += timedelta(days=1)
        if date.weekday() < 5 and date not in holidays:
            remaining -= 1
    order.delivery_date = date
    for row in order.items:
        row.delivery_date = date


def delivery_item(settings):
    return settings.get("hospice_delivery_item") or "ITE-2025-016885"


def price_order(order, buyer, shop, settings):
    """Hospice shelf prices include VAT; delivery is a taxable service item."""
    code = delivery_item(settings)
    if any(row.item_code == code for row in order.items):
        frappe.throw("The delivery service cannot be selected as a Hospice product.")
    for tax in order.taxes:
        if tax.charge_type != "On Net Total":
            frappe.throw("Hospice checkout needs a tax template with item VAT only.")
        tax.included_in_print_rate = 1
    order.run_method("calculate_taxes_and_totals")
    threshold = settings.get("hospice_free_delivery_from")
    threshold = float(35 if threshold is None else threshold)
    if threshold <= 0:
        frappe.throw("Set a positive Hospice free-delivery threshold.")
    # Compare rounded gross prices, rather than ERPNext's VAT-exclusive net total.
    gross = round(sum(row.amount for row in order.items), 2)
    if buyer["delivery"] != "delivery" or gross >= threshold:
        return None
    from erpnext.stock.get_item_details import get_price_list_rate_for
    item = frappe.get_cached_doc("Item", code)
    if item.disabled or not item.is_sales_item or item.is_stock_item or item.has_variants:
        frappe.throw("The Hospice delivery item must be an enabled non-stock sales item.")
    rate = get_price_list_rate_for(frappe._dict(price_list=shop.price_list,
        customer=order.customer, uom=item.stock_uom, stock_uom=item.stock_uom,
        qty=1, transaction_date=nowdate()), code)
    if not rate or rate <= 0:
        frappe.throw("Set the Hospice delivery item's VAT-inclusive price.")
    order.append("items", dict(item_code=code, qty=1, uom=item.stock_uom,
        conversion_factor=1, rate=rate, price_list_rate=rate, delivery_date=order.delivery_date))
    order.run_method("set_missing_item_details")
    order.append_taxes_from_item_tax_template()
    for tax in order.taxes:
        tax.included_in_print_rate = 1
    return code


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=60)
def prepare(token, items, buyer):
    campaign_settings()
    return checkout._prepare(token, items, buyer, campaign="hospice")


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=40, seconds=60)
def catalogue():
    from erpnext.stock.get_item_details import get_price_list_rate_for
    settings = campaign_settings()
    shop, _, live = checkout._gateway(settings)
    result = []
    for row in settings.hospice_items:
        item = frappe.get_cached_doc("Item", row.item_code)
        if item.disabled or not item.is_sales_item or item.has_variants or item.is_fixed_asset:
            continue
        rate = get_price_list_rate_for(frappe._dict(price_list=shop.price_list,
            customer=settings.hospice_customer, uom=item.stock_uom, stock_uom=item.stock_uom,
            qty=1, transaction_date=nowdate()), item.name)
        stock = frappe.db.get_value("Bin", {"item_code":item.name,"warehouse":settings.hospice_warehouse},
            ["actual_qty","reserved_qty"], as_dict=True)
        available = max(0, (stock.actual_qty or 0)-(stock.reserved_qty or 0)) if stock else 0
        image = item.image or ""
        # Never publish private attachments, arbitrary URLs or HTML from Item.
        if not image.startswith("/files/") or not frappe.db.exists("File", {"file_url":image,"is_private":0}):
            image = ""
        result.append(dict(id=item.name, name=item.item_name, image=image,
            price=float(rate or 0), available=bool(rate and (not item.is_stock_item or available > 0))))
    return dict(items=result, donation=DONATION, delivery="3–5 working days", is_live=live,
                prices_include_vat=True, free_delivery_from=settings.get("hospice_free_delivery_from") or 35)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=60)
def track(token):
    # Token is sent in a POST body; it is never an order ID or Customer ID.
    try:
        digest = checkout_id(token)
    except ValueError:
        digest = "invalid"
    name = frappe.db.get_value("Callus Checkout", {"tracking_hash":digest,"campaign":"hospice"}, "name")
    doc = frappe.get_doc("Callus Checkout", name) if name else None
    if not doc or doc.tracking_revoked or doc.tracking_expires_at < time.time() or doc.status not in ("Paid","Refund Pending","Refunded"):
        frappe.throw("This tracking link is unavailable. Please contact Callus.", frappe.PermissionError)
    from webshop.callus_storefront.hospice_fulfilment import progress_for
    order = frappe.get_doc("Sales Order", doc.sales_order)
    progress = progress_for(order, doc)
    if doc.status == "Refunded":
        progress["delivery_state"] = "Refunded"
    elif doc.status == "Refund Pending":
        progress["delivery_state"] = "Refund in progress"
    # No names, email, telephone, address, invoice, driver or POD attachments.
    return dict(order=doc.sales_order, payment=doc.status, progress=progress,
        fulfilment=json.loads(doc.buyer)["delivery"],
        items=json.loads(doc.summary)["items"], delivery="3–5 working days")


def queue_emails(name):
    """Queue both emails and token hash atomically, once, after verified accounting.

    Must run outside reconciliation's transaction: mail failures never undo payment.
    The raw token exists only in the recipient's email, not in the checkout record.
    """
    with checkout._locked(name):
        doc = frappe.get_doc("Callus Checkout", name)
        if doc.get("campaign") != "hospice" or doc.status != "Paid" or not doc.payment_entry or doc.campaign_notified:
            return
        from frappe.email.doctype.notification.notification import get_context
        invoice = frappe.get_doc("Sales Invoice", doc.sales_invoice)
        notification = frappe.get_doc("Notification", BUSINESS)
        settings = checkout._settings()
        buyer = json.loads(doc.buyer)
        recipients, cc, bcc = notification.get_list_of_recipients(invoice, get_context(invoice))
        customer_email = buyer["email"]
        if settings.hospice_test_email:
            customer_email = settings.hospice_test_email
            recipients, cc, bcc = [settings.hospice_test_email], [], []
        elif not doc.is_live:
            frappe.throw("Set a Hospice test email before sending test confirmations.")
        if not recipients and not cc and not bcc:
            frappe.throw("The website preparation team has no email recipients configured.")
        token = secrets.token_hex(32)
        doc.tracking_hash = checkout_id(token)
        doc.tracking_expires_at = int(time.time()) + 180 * 86400
        context = dict(buyer=buyer, summary=json.loads(doc.summary), order=doc.sales_order,
            donation=DONATION, tracking_url=get_url()+"/hospice-track#"+token,
            staff_url=get_url()+"/app/sales-order/"+doc.sales_order)
        source = (Path(__file__).parent / "emails/hospice.html").read_text()
        sender = formataddr(("Callus Garden Centre", "sales@callusgardencentre.com"))
        for business in (False, True):
            context["business"] = business
            frappe.sendmail(recipients=recipients if business else [customer_email],
                cc=cc if business else [], bcc=bcc if business else [], sender=sender,
                subject=("New paid Hospice order — " if business else "Your Hospice order — ")+doc.sales_order,
                message=frappe.render_template(source, context), delayed=True,
                reference_doctype="Callus Checkout", reference_name=doc.name)
        doc.campaign_notified = 1
        doc.save(ignore_permissions=True)
        frappe.db.commit()


def queue_pending_emails():
    from webshop.callus_storefront.hospice_fulfilment import reconcile
    reconcile()
    for name in frappe.get_all("Callus Checkout", filters={"campaign":"hospice","status":"Paid","campaign_notified":0}, pluck="name", limit_page_length=100):
        try:
            queue_emails(name)
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Hospice order email requires review", message="Checkout " + name)


@frappe.whitelist(methods=["POST"])
def configure(enable=0, test_email=None, warehouse=None):
    """Explicit manager setup; migrations never enable the public campaign."""
    frappe.only_for("System Manager")
    from frappe.utils.nestedset import get_root_of
    settings = checkout._settings()
    source = frappe.get_single("Blooming Garden Customer Ordering Settings")
    shop = frappe.get_cached_doc("Webshop Settings")
    source_customer = frappe.db.get_value("Customer", source.customer, "customer_name") or ""
    if "hospice" not in source_customer.lower():
        frappe.throw("The existing product selection is not assigned to Hospice. Please review it first.")
    if source.company != shop.company or not source.allowed_items:
        frappe.throw("Review the existing Hospice product selection and company first.")
    if warehouse is not None:
        selected_warehouse = frappe.get_doc("Warehouse", warehouse)
        if selected_warehouse.disabled or selected_warehouse.is_group or selected_warehouse.company != shop.company:
            frappe.throw("Select an active stock warehouse for the webshop company.")
        settings.hospice_warehouse = selected_warehouse.name
    if not settings.hospice_customer:
        existing = frappe.get_all("Customer", filters={"customer_name":CUSTOMER_NAME}, pluck="name")
        if len(existing) > 1:
            frappe.throw("There are duplicate Hospice cash customers. Please resolve them first.")
        settings.hospice_customer = existing[0] if existing else frappe.get_doc(dict(doctype="Customer",
            customer_name=CUSTOMER_NAME, customer_type="Company", customer_group=shop.default_customer_group,
            territory=get_root_of("Territory"))).insert().name
    if not settings.hospice_items:
        settings.set("hospice_items", [dict(item_code=row.item_code) for row in source.allowed_items])
    if not settings.hospice_warehouse:
        settings.hospice_warehouse = source.default_warehouse
    if test_email is not None:
        if test_email and not validate_email_address(test_email):
            frappe.throw("Enter a valid test email address.")
        settings.hospice_test_email = test_email
    settings.hospice_enabled = int(str(enable) == "1")
    settings.save(ignore_permissions=True)
    if settings.hospice_enabled:
        campaign_settings()
        _, _, live = checkout._gateway(settings)
        if not live and not settings.hospice_test_email:
            frappe.throw("Set a test email before enabling test checkout.")
    return dict(enabled=bool(settings.hospice_enabled), customer=settings.hospice_customer,
        products=len(settings.hospice_items))


@frappe.whitelist(methods=["POST"])
def revoke_tracking(checkout_name):
    frappe.only_for("System Manager")
    with checkout._locked(checkout_name):
        doc = frappe.get_doc("Callus Checkout", checkout_name)
        if doc.get("campaign") != "hospice":
            frappe.throw("This is not a Hospice checkout.")
        doc.tracking_revoked = 1
        doc.save(ignore_permissions=True)


def private_response(response, request=None):
    request = request or frappe.local.request
    path = request.path
    if path in ("/hospice", "/hospice-track") or "webshop.callus_storefront.hospice." in path:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    return response


def setup():
    """Only add staff fields. Never activate checkout or create customers on migration."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({"Sales Order": [
        dict(fieldname="custom_hospice_order", label="Hospice Campaign Order", fieldtype="Check", read_only=1, insert_after="customer"),
        dict(fieldname="custom_hospice_fulfilment", label="Hospice Fulfilment", fieldtype="Select",
             options="Delivery\nPickup", read_only=1, allow_on_submit=1, in_list_view=1,
             depends_on="eval:doc.custom_hospice_order", insert_after="custom_hospice_order"),
        dict(fieldname="custom_hospice_status", label="Hospice Order Progress", fieldtype="Data",
             read_only=1, allow_on_submit=1, in_list_view=1,
             depends_on="eval:doc.custom_hospice_order", insert_after="custom_hospice_fulfilment"),
        dict(fieldname="custom_hospice_preparation", label="Manual Preparation Step", fieldtype="Select",
             options="Awaiting preparation\nPreparing\nReady for dispatch\nReady for pickup\nCollected", allow_on_submit=1,
             description="Order progress advances automatically from picking, dispatch and proof of delivery. Use this field for manual shop preparation.",
             depends_on="eval:doc.custom_hospice_order", insert_after="custom_hospice_status"),
        dict(fieldname="custom_hospice_buyer_company", label="Hospice Buyer Company", fieldtype="Data", read_only=1,
             depends_on="eval:doc.custom_hospice_order", insert_after="custom_hospice_preparation"),
        dict(fieldname="custom_hospice_buyer_vat", label="Hospice Buyer VAT Number", fieldtype="Data", read_only=1,
             depends_on="eval:doc.custom_hospice_order", insert_after="custom_hospice_buyer_company"),
        dict(fieldname="custom_hospice_instructions", label="Hospice Delivery Instructions", fieldtype="Small Text", read_only=1,
             depends_on="eval:doc.custom_hospice_order", insert_after="custom_hospice_buyer_vat"),
    ]})
