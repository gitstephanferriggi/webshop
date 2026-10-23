"""Private, signed Hospice receipts and an idempotent PDF/email outbox."""
import json
import hashlib
from email.utils import formataddr
from pathlib import Path

import frappe
from frappe.utils import flt, format_datetime, get_datetime, get_fullname, get_system_timezone, now_datetime

from webshop.callus_storefront import checkout, hospice_fulfilment
from webshop.callus_storefront.hospice_signature import ACKNOWLEDGEMENT, clean_name, clean_signature

ROOT = Path(__file__).parent


def create_handover(order, payment, key, kind, recipient, signature, items, notes, timestamp, staff,
                    execution=None):
    receipt = frappe.get_doc(dict(doctype="Callus Handover", source_key=key, checkout=payment.name,
        sales_order=order.name, company=order.company, handover_type=kind, delivery_execution=execution,
        delivery_notes="\n".join(notes), recipient_name=recipient, signature=signature,
        acknowledgement=ACKNOWLEDGEMENT, handed_over_at=timestamp, recorded_by=staff,
        staff_name=get_fullname(staff), timezone=get_system_timezone(), customer_email=json.loads(payment.buyer)["email"], items=items,
        email_state="Pending"))
    receipt.flags.callus_verified_handover = True
    receipt.insert(ignore_permissions=True)
    receipt.flags.ignore_permissions = True
    receipt.submit()
    return receipt


def enqueue_receipt(name):
    def dispatch():
        try:
            if not frappe.db.exists("Callus Handover", {"name":name, "docstatus":1}):
                return
            frappe.enqueue("webshop.callus_storefront.hospice_receipts.process_receipt", receipt_name=name)
        except Exception:
            # The handover has committed. The five-minute outbox retry will recover.
            frappe.log_error(title="Hospice receipt queue unavailable", message=frappe.get_traceback())
    frappe.db.after_commit.add(dispatch)


def hospice_orders(execution):
    if not execution.get("delivery_note"):
        return []
    return frappe.db.sql("""SELECT DISTINCT c.sales_order FROM `tabCallus Checkout` c
        JOIN `tabDelivery Note Item` i ON i.against_sales_order=c.sales_order
        WHERE i.parent=%s AND c.campaign='hospice'""", execution.delivery_note, pluck=True)


def validate_delivery_signature(doc, method=None):
    if doc.execution_status not in ("Delivered", "Partially Delivered") or not hospice_orders(doc):
        return
    from bloominggarden.bloominggarden.delivery import notifications
    if not getattr(notifications, "CUSTOMER_POD_HANDLERS_SUPPORTED", False):
        frappe.throw("Deploy the delivery receipt integration before completing Hospice deliveries.")
    try:
        doc.recipient_name, doc.signature = clean_name(doc.recipient_name), clean_signature(doc.signature)
    except ValueError as error:
        frappe.throw(str(error))


def handle_customer_pod_email(execution):
    """Claim Hospice mail before the delivery app considers a shared customer email."""
    if not hospice_orders(execution):
        return False
    enqueue_delivery(execution)
    return True


def enqueue_delivery(doc, method=None):
    if (doc.docstatus == 1 and doc.execution_status in ("Delivered", "Partially Delivered")
            and after_cutoff(doc) and hospice_orders(doc)):
        def dispatch():
            try:
                frappe.enqueue("webshop.callus_storefront.hospice_receipts.record_delivery", execution_name=doc.name)
            except Exception:
                frappe.log_error(title="Hospice delivery receipt queue unavailable", message=frappe.get_traceback())
        frappe.db.after_commit.add(dispatch)


def after_cutoff(execution):
    cutoff = checkout._settings().get("hospice_signed_receipts_from")
    return bool(cutoff and execution.delivered_at and get_datetime(execution.delivered_at) >= get_datetime(cutoff))


def valid_execution(execution):
    if execution.docstatus != 1 or execution.execution_status not in ("Delivered", "Partially Delivered"):
        return False
    from bloominggarden.bloominggarden.delivery.status import get_latest_valid_execution
    return (frappe.db.get_value("Delivery Trip", execution.delivery_trip, "docstatus") == 1
            and get_latest_valid_execution(execution.delivery_note) == execution.name)


def record_delivery(execution_name):
    execution = frappe.get_doc("Delivery Execution", execution_name)
    if not valid_execution(execution) or not after_cutoff(execution):
        return
    # Delivery-app signed evidence is authoritative. Never email an unsigned override.
    recipient, signature = clean_name(execution.recipient_name), clean_signature(execution.signature)
    note = frappe.get_doc("Delivery Note", execution.delivery_note)
    if note.docstatus != 1 or note.is_return or note.customer != execution.customer:
        frappe.throw("The delivery evidence does not match its submitted Delivery Note.")
    linked = {row.name: row for row in note.items}
    for order_name in hospice_orders(execution):
        payment = hospice_fulfilment.checkout_for(order_name)
        if not payment or payment.status != "Paid":
            continue
        if json.loads(payment.buyer)["delivery"] != "delivery":
            continue
        order = frappe.get_doc("Sales Order", order_name)
        if order.docstatus != 1 or order.customer != note.customer or order.company != note.company:
            continue
        with checkout._locked(payment.name):
            key = "delivery:" + execution.name + ":" + payment.name
            if frappe.db.exists("Callus Handover", {"source_key":key}):
                continue
            products = {row["id"] for row in json.loads(payment.summary)["items"]}
            lines = {row.name: row for row in order.items if row.item_code in products}
            quantities = dict.fromkeys(lines, 0.0)
            for row in execution.items:
                source = linked.get(row.delivery_note_item)
                if source and source.against_sales_order == order.name and source.so_detail in lines:
                    line = lines[source.so_detail]
                    qty = flt(row.delivered_qty) * flt(source.conversion_factor or 1) / flt(line.conversion_factor or 1)
                    if qty < 0 or qty > flt(line.qty) + 1e-8:
                        frappe.throw("The signed delivery quantity does not match the order.")
                    quantities[source.so_detail] += qty
            items = [dict(item_code=lines[name].item_code, item_name=lines[name].item_name,
                          qty=qty, uom=lines[name].uom) for name, qty in quantities.items() if qty > 0]
            if not items:
                continue
            create_handover(order, payment, key, "Delivery", recipient, signature, items, [note.name],
                execution.delivered_at, execution.completed_by or execution.modified_by, execution=execution.name)
            frappe.db.commit()


def source_is_valid(receipt):
    order = frappe.get_doc("Sales Order", receipt.sales_order)
    payment = frappe.get_doc("Callus Checkout", receipt.checkout)
    if order.docstatus != 1 or payment.status != "Paid" or payment.sales_order != order.name:
        return False
    return receipt.handover_type == "Pickup" or valid_execution(
        frappe.get_doc("Delivery Execution", receipt.delivery_execution))


def on_delivery_cancel(doc, method=None):
    for name in frappe.get_all("Callus Handover", filters={"delivery_execution":doc.name}, pluck="name"):
        frappe.db.set_value("Callus Handover", name, "email_state", "Superseded")
        for queue in frappe.get_all("Email Queue", filters={"reference_doctype":"Callus Handover",
                "reference_name":name, "status":["in", ["Not Sent", "Error"]]}, pluck="name"):
            frappe.db.set_value("Email Queue", queue, {
                "status":"Error", "error":"Delivery evidence was cancelled. This receipt must not be sent."})


def render_pdf(receipt):
    from frappe.utils.pdf import get_pdf
    template = (ROOT / "templates/hospice_receipt.html").read_text()
    return get_pdf(frappe.render_template(template, receipt_context(receipt)),
                   options={"page-size":"A4", "margin-top":"16mm", "margin-bottom":"16mm"})


def receipt_context(receipt):
    return {"receipt":receipt, "date_label":format_datetime(receipt.handed_over_at, "dd MMM yyyy, HH:mm:ss")}


def private_pdf(receipt):
    name = receipt.get("receipt_file")
    if name and frappe.db.exists("File", name):
        file = frappe.get_doc("File", name)
        if file.is_private != 1 or file.attached_to_doctype != "Sales Order" or file.attached_to_name != receipt.sales_order:
            frappe.throw("The receipt attachment needs an access review before emailing.")
        try:
            content = file.get_content()
            raw = content.encode() if isinstance(content, str) else content
            if hashlib.sha256(raw).hexdigest() == receipt.pdf_sha256:
                return file
        except FileNotFoundError:
            pass
        # Regenerate missing/corrupt managed evidence from the immutable snapshot.
        frappe.delete_doc("File", name, ignore_permissions=True, force=True)
    content = render_pdf(receipt)
    if not isinstance(content, bytes) or not content.startswith(b"%PDF-"):
        frappe.throw("The signed receipt PDF could not be generated.")
    return frappe.get_doc(dict(doctype="File", file_name="Receipt-" + receipt.name + ".pdf",
        attached_to_doctype="Sales Order", attached_to_name=receipt.sales_order,
        is_private=1, content=content)).insert(ignore_permissions=True)


def process_receipt(receipt_name, resend=False):
    with frappe.cache.lock("callus-handover:" + receipt_name, timeout=180, blocking_timeout=5):
        receipt = frappe.get_doc("Callus Handover", receipt_name)
        if receipt.docstatus != 1:
            return
        if not source_is_valid(receipt):
            receipt.db_set("email_state", "Superseded")
            frappe.db.commit()
            return
        if receipt.email_state == "Queued" and not resend:
            return
        try:
            file = private_pdf(receipt)
            payment = frappe.get_doc("Callus Checkout", receipt.checkout)
            settings = checkout._settings()
            if not payment.is_live and not settings.hospice_test_email:
                frappe.throw("Set a Hospice test email before sending receipt emails.")
            recipient = settings.hospice_test_email or receipt.customer_email
            template = (ROOT / "emails/hospice_receipt.html").read_text()
            frappe.sendmail(recipients=[recipient], sender=formataddr(("Callus Garden Centre", "sales@callusgardencentre.com")),
                subject=("Your signed collection receipt — " if receipt.handover_type == "Pickup"
                         else "Your signed delivery receipt — ") + receipt.sales_order,
                message=frappe.render_template(template, receipt_context(receipt)), attachments=[{"fid":file.name}],
                delayed=True, reference_doctype="Callus Handover", reference_name=receipt.name)
            content = file.get_content()
            raw = content.encode() if isinstance(content, str) else content
            receipt.db_set(dict(receipt_pdf=file.file_url, email_state="Queued", email_queued_at=now_datetime(),
                receipt_file=file.name, pdf_sha256=hashlib.sha256(raw).hexdigest(),
                last_error=None, resend_count=(receipt.resend_count or 0) + int(resend)))
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Hospice signed receipt needs retry", message=frappe.get_traceback())
            frappe.db.set_value("Callus Handover", receipt_name, {
                "email_state":"Queued" if resend else "Failed",
                "last_error":"Receipt PDF or email could not be queued. Retry from the Sales Order."})
            frappe.db.commit()
            if resend:
                frappe.throw("The receipt could not be resent. The signed handover remains recorded.")


@frappe.whitelist(methods=["POST"])
def order_receipts(order_name):
    frappe.get_doc("Sales Order", order_name).check_permission("read")
    return frappe.get_all("Callus Handover", filters={"sales_order":order_name, "docstatus":1},
        fields=["name", "handover_type", "recipient_name", "handed_over_at", "receipt_pdf", "email_state", "last_error"],
        order_by="handed_over_at desc")


@frappe.whitelist(methods=["POST"])
def retry_or_resend(receipt_name):
    receipt = frappe.get_doc("Callus Handover", receipt_name)
    frappe.get_doc("Sales Order", receipt.sales_order).check_permission("write")
    process_receipt(receipt_name, resend=receipt.email_state == "Queued")
    return frappe.db.get_value("Callus Handover", receipt_name, ["email_state", "receipt_pdf", "last_error"], as_dict=True)


def reconcile():
    cutoff = checkout._settings().get("hospice_signed_receipts_from")
    if cutoff and frappe.db.table_exists("Delivery Execution"):
        # Recover a lost on-submit job, without emailing historical deliveries.
        rows = frappe.db.sql("""SELECT DISTINCT e.name FROM `tabDelivery Execution` e
            JOIN `tabDelivery Note Item` i ON i.parent=e.delivery_note
            JOIN `tabCallus Checkout` c ON c.sales_order=i.against_sales_order
            WHERE e.docstatus=1 AND e.execution_status IN ('Delivered', 'Partially Delivered')
              AND e.delivered_at >= %s AND c.campaign='hospice' AND c.status='Paid'
              AND NOT EXISTS (SELECT 1 FROM `tabCallus Handover` h
                  WHERE h.delivery_execution=e.name AND h.checkout=c.name)
            ORDER BY e.name LIMIT 100""", cutoff, pluck=True)
        for name in rows:
            try:
                record_delivery(name)
            except Exception:
                frappe.db.rollback()
                frappe.log_error(title="Hospice delivery evidence needs review", message=frappe.get_traceback())
    for name in frappe.get_all("Callus Handover", filters={"docstatus":1, "email_state":["in", ["Pending", "Failed"]]},
                              pluck="name", limit_page_length=100):
        process_receipt(name)


def setup():
    # get_single_value coerces an empty Datetime to datetime.min (truthy).
    if not checkout._settings().get("hospice_signed_receipts_from"):
        frappe.db.set_single_value("Callus Checkout Settings", "hospice_signed_receipts_from", now_datetime())
