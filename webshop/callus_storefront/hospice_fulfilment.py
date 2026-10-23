"""Hospice progress from operational records; a dispatch note is not a POD."""
import json
from copy import deepcopy
from email.utils import formataddr
from pathlib import Path

import frappe
from frappe.utils import flt

from webshop.callus_storefront import checkout


def fulfilment(order, doc):
    # Existing orders predate the fulfilment field; the checkout snapshot is authoritative.
    return "Pickup" if json.loads(doc.buyer)["delivery"] == "collection" else "Delivery"


def preparation_state(manual, pickup, started, picked, dispatched):
    if pickup and manual == "Collected":
        return "Collected"
    ready = "Ready for pickup" if pickup else "Ready for dispatch"
    if picked or dispatched or manual == ready:
        return ready
    if started or manual == "Preparing":
        return "Preparing"
    return "Awaiting preparation"


def operational_facts(order):
    from webshop.callus_storefront.hospice import delivery_item
    service = delivery_item(checkout._settings())
    lines = {row.name: row for row in order.items if row.item_code != service
             and frappe.get_cached_value("Item", row.item_code, "is_stock_item")}
    if not lines:
        return False, False, False
    picks = frappe.db.sql("""SELECT i.sales_order_item, i.picked_qty, p.docstatus
        FROM `tabPick List Item` i JOIN `tabPick List` p ON p.name=i.parent
        WHERE i.sales_order=%s AND p.docstatus<2""", order.name, as_dict=True)
    notes = frappe.db.sql("""SELECT i.so_detail, i.qty, i.conversion_factor
        FROM `tabDelivery Note Item` i JOIN `tabDelivery Note` d ON d.name=i.parent
        WHERE i.against_sales_order=%s AND d.docstatus=1""", order.name, as_dict=True)
    picked, dispatched = dict.fromkeys(lines, 0.0), dict.fromkeys(lines, 0.0)
    for row in picks:
        if row.sales_order_item in lines and row.docstatus == 1:
            # Pick List.picked_qty is stored in stock UOM.
            picked[row.sales_order_item] += flt(row.picked_qty)
    for row in notes:
        if row.so_detail in lines:
            dispatched[row.so_detail] += flt(row.qty) * flt(row.conversion_factor or 1)
    def complete(qtys):
        return all(qtys[name] + 1e-8 >= flt(line.qty) * flt(line.conversion_factor or 1)
                   for name, line in lines.items())
    return bool(picks or notes), complete(picked), complete(dispatched)


def progress_for(order, doc):
    pickup = fulfilment(order, doc) == "Pickup"
    started, picked, dispatched = operational_facts(order)
    state = preparation_state(order.get("custom_hospice_preparation"), pickup, started, picked, dispatched)
    if pickup:
        progress = dict(delivery_state=state, needs_attention=False, deliveries=[],
            quantities=[dict(item_code=row["id"], ordered_qty=row["qty"],
                             delivered_qty=row["qty"] if state == "Collected" else 0)
                        for row in json.loads(doc.summary)["items"]])
    else:
        from bloominggarden.bloominggarden.customer_ordering.progress import order_progress
        products = {row["id"] for row in json.loads(doc.summary)["items"]}
        physical_order = deepcopy(order)
        physical_order.set("items", [row for row in physical_order.items if row.item_code in products])
        progress = order_progress(physical_order)
        if progress["delivery_state"] == "Awaiting planning":
            progress["delivery_state"] = state
        # Delivery is a service, never something the driver must physically deliver.
        progress["quantities"] = [row for row in progress.get("quantities", [])
                                  if row["item_code"] in products]
    if order.docstatus == 2:
        progress["delivery_state"] = "Cancelled"
    elif doc.status in ("Refunded", "Refund Pending"):
        progress["delivery_state"] = "Refunded" if doc.status == "Refunded" else "Refund in progress"
    elif doc.status == "Expired":
        progress["delivery_state"] = "Expired"
    elif doc.status != "Paid":
        progress["delivery_state"] = "Awaiting payment"
    return progress


def checkout_for(order_name):
    name = frappe.db.get_value("Callus Checkout", {"campaign":"hospice", "sales_order":order_name}, "name")
    return frappe.get_doc("Callus Checkout", name) if name else None


def sync_order(order_name, order=None):
    doc = checkout_for(order_name)
    if not doc:
        return
    order = order or frappe.get_doc("Sales Order", order_name)
    state = progress_for(order, doc)["delivery_state"]
    values = dict(custom_hospice_fulfilment=fulfilment(order, doc), custom_hospice_status=state)
    if any(order.get(key) != value for key, value in values.items()):
        order.db_set(values, notify=True)
    if state == "Ready for pickup" and not doc.get("pickup_ready_notified"):
        frappe.enqueue("webshop.callus_storefront.hospice_fulfilment.queue_pickup_ready_email",
                       checkout_name=doc.name, enqueue_after_commit=True)


def on_order_change(doc, method=None):
    if doc.get("custom_hospice_order"):
        sync_order(doc.name, order=doc)


def on_checkout_change(doc, method=None):
    if doc.get("campaign") == "hospice" and doc.sales_order:
        sync_order(doc.sales_order)


def on_fulfilment_change(doc, method=None):
    orders = set()
    if doc.doctype == "Pick List":
        orders.update(row.sales_order for row in doc.locations if row.sales_order)
    else:
        notes = []
        if doc.doctype == "Delivery Note":
            orders.update(row.against_sales_order for row in doc.items if row.against_sales_order)
        elif doc.doctype == "Delivery Execution":
            notes = [doc.delivery_note]
        elif doc.doctype == "Delivery Trip":
            notes = [row.delivery_note for row in doc.delivery_stops if row.delivery_note]
        if notes:
            orders.update(frappe.get_all("Delivery Note Item", filters={"parent":["in", notes]},
                                         pluck="against_sales_order"))
    for name in sorted(filter(None, orders)):
        sync_order(name)


def clear_pickup_address(doc, pickup=False):
    if pickup or doc.get("custom_hospice_fulfilment") == "Pickup":
        # ERPNext otherwise selects a previous buyer's address on the shared customer.
        for field in ("customer_address", "shipping_address_name", "address_display", "shipping_address"):
            doc.set(field, None)


def clear_linked_pickup_address(doc, method=None):
    orders = {row.get("sales_order") or row.get("against_sales_order") for row in doc.items}
    orders.discard(None)
    orders.discard("")
    if len(orders) == 1:
        order = frappe.db.get_value("Sales Order", next(iter(orders)),
            ["custom_hospice_order", "custom_hospice_fulfilment"], as_dict=True)
        if order and order.custom_hospice_order and order.custom_hospice_fulfilment == "Pickup":
            clear_pickup_address(doc, pickup=True)


def validate_preparation(doc, method=None):
    if not doc.get("custom_hospice_order"):
        return
    clear_pickup_address(doc)
    old = doc.get_doc_before_save()
    if not old or old.get("custom_hospice_preparation") == doc.custom_hospice_preparation:
        return
    payment = checkout_for(doc.name)
    if not payment or payment.status != "Paid" or doc.docstatus != 1:
        frappe.throw("Preparation can only be changed on a paid, submitted Hospice order.")
    pickup = fulfilment(doc, payment) == "Pickup"
    allowed = ("Awaiting preparation", "Preparing", "Ready for pickup", "Collected") if pickup else (
        "Awaiting preparation", "Preparing", "Ready for dispatch")
    if doc.custom_hospice_preparation not in allowed:
        frappe.throw("Choose a preparation step matching this order's fulfilment method.")
    if old.custom_hospice_preparation == "Collected" and doc.custom_hospice_preparation != "Collected":
        frappe.throw("A collected order requires the normal return workflow.")
    if doc.custom_hospice_preparation == "Collected":
        if not frappe.db.exists("Callus Handover", {"source_key":"pickup:" + payment.name, "docstatus":1}):
            frappe.throw("Use Confirm collection to record the collector's name and signature.")


@frappe.whitelist(methods=["POST"])
def set_preparation(order_name, state):
    order = frappe.get_doc("Sales Order", order_name)
    order.check_permission("write")
    if not order.get("custom_hospice_order"):
        frappe.throw("This is not a Hospice order.")
    order.custom_hospice_preparation = state
    order.save()
    return {"status": frappe.db.get_value("Sales Order", order_name, "custom_hospice_status")}


def queue_pickup_ready_email(checkout_name):
    with checkout._locked(checkout_name):
        doc = frappe.get_doc("Callus Checkout", checkout_name)
        if doc.get("campaign") != "hospice" or doc.status != "Paid" or doc.get("pickup_ready_notified"):
            return
        order = frappe.get_doc("Sales Order", doc.sales_order)
        if fulfilment(order, doc) != "Pickup" or progress_for(order, doc)["delivery_state"] != "Ready for pickup":
            return
        buyer = json.loads(doc.buyer)
        settings = checkout._settings()
        recipient = settings.hospice_test_email or buyer["email"]
        if not doc.is_live and not settings.hospice_test_email:
            frappe.throw("Set a Hospice test email before sending test confirmations.")
        source = (Path(__file__).parent / "emails/hospice_pickup_ready.html").read_text()
        frappe.sendmail(recipients=[recipient],
            sender=formataddr(("Callus Garden Centre", "sales@callusgardencentre.com")),
            subject="Your Hospice order is ready for pickup — " + order.name,
            message=frappe.render_template(source, dict(buyer=buyer, order=order.name,
                items=json.loads(doc.summary)["items"])), delayed=True,
            reference_doctype="Callus Checkout", reference_name=doc.name)
        doc.db_set("pickup_ready_notified", 1)
        # Queue row and marker are atomic; the scheduler retries transaction failures.
        frappe.db.commit()


def reconcile():
    start = 0
    while True:
        rows = frappe.get_all("Callus Checkout", filters={"campaign":"hospice"},
            fields=["name", "sales_order"], order_by="name", start=start, page_length=200)
        for row in rows:
            try:
                sync_order(row.sales_order)
                frappe.db.commit()
                queue_pickup_ready_email(row.name)
            except Exception:
                frappe.db.rollback()
                frappe.log_error(title="Hospice fulfilment needs review", message=frappe.get_traceback())
        if len(rows) < 200:
            break
        start += 200
    from webshop.callus_storefront.hospice_receipts import reconcile as reconcile_receipts
    reconcile_receipts()
