"""One signed pickup handover, with its stock posting in the same transaction."""
import json

import frappe
from frappe.utils import flt, now_datetime

from webshop.callus_storefront import checkout, hospice_fulfilment
from webshop.callus_storefront.hospice_signature import ACKNOWLEDGEMENT, clean_name, clean_signature


def receipt_info(receipt):
    return {key: receipt.get(key) for key in
            ("name", "recipient_name", "handed_over_at", "receipt_pdf", "email_state")}


def paid_pickup(order_name):
    order = frappe.get_doc("Sales Order", order_name)
    order.check_permission("write")
    payment = hospice_fulfilment.checkout_for(order_name)
    if (not payment or payment.status != "Paid" or order.docstatus != 1
            or hospice_fulfilment.fulfilment(order, payment) != "Pickup"):
        frappe.throw("Choose a paid, submitted Hospice pickup order.")
    invoice = frappe.db.get_value("Sales Invoice", payment.sales_invoice,
        ["docstatus", "outstanding_amount", "grand_total", "rounded_total"], as_dict=True)
    if (not invoice or invoice.docstatus != 1 or abs(flt(invoice.outstanding_amount)) > 0.005
            or abs(flt(invoice.rounded_total or invoice.grand_total) - payment.amount_minor / 100) > 0.005
            or frappe.db.get_value("Payment Entry", payment.payment_entry, "docstatus") != 1):
        frappe.throw("The invoice or payment needs review before collection.")
    return order, payment


def product_snapshot(order, payment):
    expected = {row["id"]: flt(row["qty"]) for row in json.loads(payment.summary)["items"]}
    actual = {}
    items = []
    for row in order.items:
        if row.item_code not in expected:
            frappe.throw("This paid pickup order needs review before handover.")
        actual[row.item_code] = actual.get(row.item_code, 0) + flt(row.qty)
        items.append(dict(item_code=row.item_code, item_name=row.item_name, qty=row.qty, uom=row.uom))
    if actual != expected:
        frappe.throw("The paid order quantities changed. Review the order before collection.")
    return items


def complete_stock_handover(order):
    """Reuse submitted notes; submit a matching draft or create only remaining goods."""
    rows = frappe.db.sql("""SELECT i.so_detail, i.qty, i.conversion_factor, d.name, d.docstatus,
            d.is_return, d.customer, d.company
        FROM `tabDelivery Note Item` i JOIN `tabDelivery Note` d ON d.name=i.parent
        WHERE i.against_sales_order=%s AND d.docstatus<2""", order.name, as_dict=True)
    stock = {row.name: row for row in order.items
             if frappe.get_cached_value("Item", row.item_code, "is_stock_item")}
    posted = dict.fromkeys(stock, 0.0)
    notes, drafts = set(), set()
    for row in rows:
        if row.customer != order.customer or row.company != order.company or row.is_return:
            frappe.throw("Existing delivery or return documents need review before collection.")
        if row.docstatus == 0:
            drafts.add(row.name)
        else:
            notes.add(row.name)
            if row.so_detail in stock:
                posted[row.so_detail] += flt(row.qty) * flt(row.conversion_factor or 1)
    remaining = {name: flt(row.qty) * flt(row.conversion_factor or 1) - posted[name]
                 for name, row in stock.items()}
    if any(qty < -1e-8 for qty in remaining.values()):
        frappe.throw("The stock handover exceeds the order. Review its Delivery Notes.")
    if not any(qty > 1e-8 for qty in remaining.values()):
        if drafts:
            frappe.throw("Resolve the outstanding draft Delivery Note before collection.")
        return sorted(notes)
    if len(drafts) > 1:
        frappe.throw("Resolve the multiple draft Delivery Notes before collection.")
    if drafts:
        note = frappe.get_doc("Delivery Note", next(iter(drafts)))
        quantities = dict.fromkeys(stock, 0.0)
        for row in note.items:
            if row.against_sales_order != order.name or row.so_detail not in stock:
                frappe.throw("The draft Delivery Note includes unrelated goods. Review it before collection.")
            quantities[row.so_detail] += flt(row.qty) * flt(row.conversion_factor or 1)
        if any(abs(quantities[name] - remaining[name]) > 1e-8 for name in stock):
            frappe.throw("The draft Delivery Note must match all remaining pickup goods.")
        note.check_permission("write")
    else:
        from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
        note = make_delivery_note(order.name)
        note.check_permission("create")
    note.check_permission("submit")
    timestamp = now_datetime()
    note.posting_date, note.posting_time = timestamp.date(), timestamp.time()
    note.set_posting_time = 1
    note.save()
    note.submit()
    if not hospice_fulfilment.operational_facts(order)[2]:
        frappe.throw("The Delivery Note did not record all pickup goods. Collection was not completed.")
    notes.add(note.name)
    return sorted(notes)


@frappe.whitelist(methods=["POST"])
def collection_details(order_name):
    order, payment = paid_pickup(order_name)
    name = frappe.db.get_value("Callus Handover", {"source_key":"pickup:" + payment.name, "docstatus":1}, "name")
    return {"items": product_snapshot(order, payment), "acknowledgement": ACKNOWLEDGEMENT,
            "receipt": receipt_info(frappe.get_doc("Callus Handover", name)) if name else None}


def protect_signed_stock(doc, method=None):
    rows = frappe.get_all("Callus Handover", filters={"handover_type":"Pickup", "docstatus":1,
        "delivery_notes":["like", "%" + doc.name + "%"]}, pluck="delivery_notes")
    if any(doc.name in value.splitlines() for value in rows):
        frappe.throw("This Delivery Note supports a signed collection. Use the normal returns workflow.")


@frappe.whitelist(methods=["POST"])
def confirm_collection(order_name, recipient_name, signature):
    order, payment = paid_pickup(order_name)
    with checkout._locked(payment.name):
        frappe.db.sql("SELECT name FROM `tabSales Order` WHERE name=%s FOR UPDATE", order_name)
        order, payment = paid_pickup(order_name)
        key = "pickup:" + payment.name
        existing = frappe.db.get_value("Callus Handover", {"source_key":key, "docstatus":1}, "name")
        if existing:
            return receipt_info(frappe.get_doc("Callus Handover", existing))
        if hospice_fulfilment.progress_for(order, payment)["delivery_state"] != "Ready for pickup":
            frappe.throw("Mark this order ready for pickup before confirming collection.")
        try:
            recipient_name, signature = clean_name(recipient_name), clean_signature(signature)
        except ValueError as error:
            frappe.throw(str(error))
        items = product_snapshot(order, payment)
        # On any failure, both stock and evidence roll back even if a caller catches
        # the exception. No commit or external email occurs inside this operation.
        frappe.db.savepoint("hospice_collection")
        try:
            notes = complete_stock_handover(order)
            from webshop.callus_storefront.hospice_receipts import create_handover
            receipt = create_handover(order, payment, key, "Pickup", recipient_name, signature,
                                      items, notes, now_datetime(), frappe.session.user)
            order.reload()
            order.custom_hospice_preparation = "Collected"
            order.save()
            return receipt_info(receipt)
        except Exception:
            frappe.db.rollback(save_point="hospice_collection")
            raise
