frappe.ui.form.on("Callus Checkout", {
    refresh(frm) {
        if (frm.doc.status === "Paid" && frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Refund full payment"), () => {
                frappe.confirm(__("Refund this payment in Stripe and create its credit note? This sends money back to the customer."), () => {
                    frappe.call({method: "webshop.callus_storefront.checkout.refund", args: {checkout: frm.doc.name}, freeze: true,
                        callback: () => frm.reload_doc()});
                });
            });
        }
    }
});
