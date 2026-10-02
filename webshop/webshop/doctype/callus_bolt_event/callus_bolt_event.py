from frappe.model.document import Document
import frappe


class CallusBoltEvent(Document):
    def autoname(self):
        self.name = self.receipt_key or frappe.generate_hash(length=32)
