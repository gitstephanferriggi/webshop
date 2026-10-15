frappe.ui.form.on('Sales Order', {
  refresh(frm) {
    if (!frm.doc.custom_hospice_order) return;
    const pickup = frm.doc.custom_hospice_fulfilment === 'Pickup';
    const status = frm.doc.custom_hospice_status || 'Awaiting payment';
    frm.set_df_property('custom_hospice_preparation', 'options', pickup
      ? ['Awaiting preparation', 'Preparing', 'Ready for pickup', 'Collected']
      : ['Awaiting preparation', 'Preparing', 'Ready for dispatch']);
    frm.set_intro(`${pickup ? __('Pickup from shop') : __('Delivery')} · ${__(status)}`, pickup ? 'blue' : 'green');
    if (frm.doc.docstatus !== 1 || !frm.perm.some(p => p.write)
        || ['Awaiting payment', 'Cancelled', 'Refunded', 'Refund in progress', 'Collected', 'Delivered'].includes(status)) return;
    const action = (label, state) => frm.add_custom_button(__(label), () => frappe.call({
      method: 'webshop.callus_storefront.hospice_fulfilment.set_preparation',
      args: {order_name: frm.doc.name, state}, freeze: true,
      callback: () => frm.reload_doc()
    }), __('Hospice'));
    if (status === 'Awaiting preparation') action('Start preparation', 'Preparing');
    if (pickup && status !== 'Ready for pickup') action('Ready for pickup', 'Ready for pickup');
    if (pickup && status === 'Ready for pickup') action('Mark collected', 'Collected');
    if (!pickup && ['Awaiting preparation', 'Preparing'].includes(status)) action('Ready for dispatch', 'Ready for dispatch');
  }
});
