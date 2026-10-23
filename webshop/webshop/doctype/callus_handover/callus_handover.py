import frappe
from frappe.model.document import Document

from webshop.callus_storefront.hospice_signature import clean_name, clean_signature


class CallusHandover(Document):
    def validate(self):
        if self.is_new() and not self.flags.callus_verified_handover:
            frappe.throw("Use the signed Hospice handover workflow to create a receipt.", frappe.PermissionError)
        try:
            self.recipient_name = clean_name(self.recipient_name)
            self.signature = clean_signature(self.signature)
        except ValueError as error:
            frappe.throw(str(error))
        if not self.items or any(row.qty <= 0 for row in self.items):
            frappe.throw("A handover must list the quantities actually received.")

    def on_submit(self):
        from webshop.callus_storefront.hospice_receipts import enqueue_receipt
        enqueue_receipt(self.name)

    def before_cancel(self):
        frappe.throw("Signed handover evidence is retained. Use the normal returns or delivery amendment workflow.")

    def on_trash(self):
        if self.docstatus == 1:
            frappe.throw("Submitted handover evidence cannot be deleted.")
