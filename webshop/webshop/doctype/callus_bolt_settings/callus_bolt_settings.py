from frappe.model.document import Document


class CallusBoltSettings(Document):
    def validate(self):
        if self.enabled and (not self.site_hostname or self.environment not in ("Staging", "Production")):
            from frappe import throw
            throw("Set the site hostname and environment before enabling Bolt receipt.")
