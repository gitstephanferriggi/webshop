// Resolution is server-validated; this grants no general write access to the inbox.
for (const doctype of ['Callus Bolt Event', 'Callus Bolt Order']) {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            const pending = doctype === 'Callus Bolt Event'
                ? frm.doc.status === 'Review' : frm.doc.workflow_state === 'Needs attention';
            if (frm.is_new() || !pending || !frappe.user.has_role('System Manager')) return;
            frm.add_custom_button(__('Resolve review'), () => {
                frappe.prompt([{fieldname: 'reason', fieldtype: 'Small Text',
                    label: __('Review reason'), reqd: 1,
                    description: __('Cancelled sales require completed returns and POS consolidation. No payment will be refunded through Bolt.')}],
                async ({reason}) => {
                    await frappe.call({method: 'webshop.bolt_integration.review.resolve_review',
                        args: {doctype, name: frm.doc.name, reason}, freeze: true});
                    await frm.reload_doc();
                    frappe.show_alert({message: __('Review resolved'), indicator: 'green'});
                }, __('Resolve review'), __('Resolve'));
            });
        }
    });
}
