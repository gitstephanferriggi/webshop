from frappe.model.document import Document


class CallusBoltSettings(Document):
    def validate(self):
        from frappe import throw
        from webshop.bolt_integration.pricing import markup_percentage
        try:
            markup_percentage(self.get('price_markup_percent') if self.get('price_markup_percent') is not None else 20)
        except ValueError as exc:
            throw(str(exc))
        if self.enabled and (not self.site_hostname or self.environment not in ("Staging", "Production")):
            throw("Set the site hostname and environment before enabling Bolt receipt.")
        if self.process_orders and not all([self.enabled, self.provider_id, self.company, self.customer, self.price_list, self.taxes_and_charges]):
            throw("Complete the Bolt sales configuration before enabling order processing.")
        if self.submit_sales and not self.process_orders:
            throw("Enable order processing before enabling submitted sales.")
        if self.sync_catalogue and not all([self.enabled, self.provider_id, self.integrator_id, self.region_id, self.secret_key, self.vat_tag, self.price_list]):
            throw("Complete the Bolt catalogue configuration before enabling synchronisation.")
        if self.get('two_way_enabled'):
            import frappe
            if not all([self.process_orders, self.pos_profile, self.warehouse, self.integrator_id, self.secret_key]):
                throw("Complete the POS Profile, warehouse and Bolt API credentials before enabling POS operations.")
            if self.submit_sales:
                throw("Disable automatic submitted sales when using POS operations; sales are posted at handover.")
            profile = frappe.get_doc('POS Profile', self.pos_profile)
            if profile.company != self.company or profile.warehouse != self.warehouse:
                throw("The Bolt POS Profile must use the configured company and fulfilment warehouse.")
        self.mode = "Sales processing enabled" if self.process_orders else "Capture only"
