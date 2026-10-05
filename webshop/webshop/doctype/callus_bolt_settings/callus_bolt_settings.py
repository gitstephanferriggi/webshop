from frappe.model.document import Document


class CallusBoltSettings(Document):
    def validate(self):
        from frappe import throw
        if self.enabled and (not self.site_hostname or self.environment not in ("Staging", "Production")):
            throw("Set the site hostname and environment before enabling Bolt receipt.")
        if self.process_orders and not all([self.enabled, self.provider_id, self.company, self.customer, self.price_list, self.taxes_and_charges]):
            throw("Complete the Bolt sales configuration before enabling order processing.")
        if self.submit_sales and not self.process_orders:
            throw("Enable order processing before enabling submitted sales.")
        if self.sync_catalogue and not all([self.enabled, self.provider_id, self.integrator_id, self.region_id, self.secret_key, self.vat_tag, self.price_list]):
            throw("Complete the Bolt catalogue configuration before enabling synchronisation.")
        self.mode = "Sales processing enabled" if self.process_orders else "Capture only"
