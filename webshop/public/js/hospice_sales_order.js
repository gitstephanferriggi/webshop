frappe.ui.form.on('Sales Order', {
  refresh(frm) {
    if (!frm.doc.custom_hospice_order) return;
    const pickup = frm.doc.custom_hospice_fulfilment === 'Pickup';
    const status = frm.doc.custom_hospice_status || 'Awaiting payment';
    frm.set_df_property('custom_hospice_preparation', 'options', pickup
      ? ['Awaiting preparation', 'Preparing', 'Ready for pickup', ...(status === 'Collected' ? ['Collected'] : [])]
      : ['Awaiting preparation', 'Preparing', 'Ready for dispatch']);
    frm.set_df_property('custom_hospice_preparation', 'read_only', ['Collected', 'Delivered'].includes(status));
    frm.set_intro(`${pickup ? __('Pickup from shop') : __('Delivery')} · ${__(status)}`, pickup ? 'blue' : 'green');
    if (frm.doc.docstatus === 1) frm.add_custom_button(__('Signed receipts'), () => hospice_receipts(frm), __('Hospice'));
    if (frm.doc.docstatus !== 1 || !frm.perm.some(p => p.write)
        || ['Awaiting payment', 'Cancelled', 'Refunded', 'Refund in progress', 'Collected', 'Delivered'].includes(status)) return;
    const action = (label, state) => frm.add_custom_button(__(label), () => frappe.call({
      method: 'webshop.callus_storefront.hospice_fulfilment.set_preparation',
      args: {order_name: frm.doc.name, state}, freeze: true,
      callback: () => frm.reload_doc()
    }), __('Hospice'));
    if (!pickup && status === 'Ready for dispatch') {
      if (frappe.model.can_create('Delivery Trip')) frm.add_custom_button(__('New delivery trip'), () => hospice_trip(frm, true), __('Hospice'));
      if (frappe.model.can_write('Delivery Trip')) frm.add_custom_button(__('Add to delivery trip'), () => hospice_trip(frm, false), __('Hospice'));
    }
    if (status === 'Awaiting preparation') action('Start preparation', 'Preparing');
    if (pickup && status !== 'Ready for pickup') action('Ready for pickup', 'Ready for pickup');
    if (pickup && status === 'Ready for pickup') frm.add_custom_button(__('Confirm collection'), () => hospice_collection(frm), __('Hospice'));
    if (!pickup && ['Awaiting preparation', 'Preparing'].includes(status)) action('Ready for dispatch', 'Ready for dispatch');
  }
});

async function hospice_collection(frm) {
  const response = await frappe.call({method: 'webshop.callus_storefront.hospice_collection.collection_details',
    args: {order_name: frm.doc.name}, freeze: true});
  if (!response.message) return;
  const data = response.message, esc = frappe.utils.escape_html;
  if (data.receipt) { await frm.reload_doc(); return hospice_receipts(frm); }
  const items = data.items.map(item => `<li>${esc(String(item.qty))} × ${esc(item.item_name)} (${esc(item.uom)})</li>`).join('');
  const dialog = new frappe.ui.Dialog({title: __('Confirm collection'), size: 'large', fields: [
    {fieldtype: 'HTML', fieldname: 'goods', options: `<p>${__('Check the goods with the collector before confirming handover.')}</p><ul>${items}</ul>`},
    {fieldtype: 'Data', fieldname: 'recipient_name', label: __('Collector name'), reqd: 1,
      description: __('Enter the name of the person receiving the goods, including when collecting on someone else’s behalf.')},
    {fieldtype: 'Signature', fieldname: 'signature', label: __('Collector signature'), reqd: 1},
    {fieldtype: 'Check', fieldname: 'acknowledged', label: __(data.acknowledgement), reqd: 1}
  ], primary_action_label: __('Confirm handover'), async primary_action() {
    const values = dialog.get_values();
    if (!values || !values.acknowledged) return;
    dialog.get_primary_btn().prop('disabled', true);
    try {
      const result = await frappe.call({method: 'webshop.callus_storefront.hospice_collection.confirm_collection',
        args: {order_name: frm.doc.name, recipient_name: values.recipient_name, signature: values.signature}, freeze: true});
      if (!result.message) return;
      dialog.hide();
      frappe.show_alert({message: __('Collection recorded. The signed receipt will be emailed to the customer.'), indicator: 'green'});
      await frm.reload_doc();
    } finally { dialog.get_primary_btn().prop('disabled', false); }
  }});
  dialog.show();
}

async function hospice_receipts(frm) {
  const response = await frappe.call({method: 'webshop.callus_storefront.hospice_receipts.order_receipts',
    args: {order_name: frm.doc.name}, freeze: true});
  const rows = response.message || [], esc = frappe.utils.escape_html;
  const dialog = new frappe.ui.Dialog({title: __('Signed receipts'), size: 'large',
    fields: [{fieldtype: 'HTML', fieldname: 'receipts'}]});
  const wrapper = dialog.fields_dict.receipts.$wrapper;
  if (!rows.length) wrapper.text(__('No signed handover has been recorded for this order.'));
  rows.forEach(row => {
    const block = $('<div class="mb-4"></div>').appendTo(wrapper);
    $('<p></p>').text(`${row.handover_type} · ${row.recipient_name} · ${row.handed_over_at} · ${row.email_state}`).appendTo(block);
    if (row.receipt_pdf && row.receipt_pdf.startsWith('/private/files/')) {
      $(`<a class="btn btn-default btn-sm mr-2" target="_blank" rel="noopener" href="${esc(row.receipt_pdf)}">${__('Open signed receipt')}</a>`).appendTo(block);
    }
    if (row.last_error) $('<p class="text-danger"></p>').text(row.last_error).appendTo(block);
    if (row.email_state === 'Superseded' || !frm.perm.some(p => p.write)) return;
    const resend = row.email_state === 'Queued';
    const button = $('<button class="btn btn-default btn-sm" type="button"></button>')
      .text(resend ? __('Resend receipt email') : __('Retry receipt email')).appendTo(block);
    button.on('click', () => {
      const send = async () => {
        button.prop('disabled', true);
        try {
          const result = await frappe.call({method: 'webshop.callus_storefront.hospice_receipts.retry_or_resend',
            args: {receipt_name: row.name}, freeze: true});
          if (result.message && result.message.email_state === 'Queued') frappe.show_alert({message: __('Receipt email queued.'), indicator: 'green'});
          dialog.hide(); await hospice_receipts(frm);
        } finally { button.prop('disabled', false); }
      };
      if (resend) frappe.confirm(__('Email this signed receipt to the original customer again?'), send);
      else send();
    });
  });
  dialog.show();
}


async function hospice_trip(frm, create) {
  if (frm.is_dirty()) return frappe.msgprint(__('Save the Sales Order before planning its delivery.'));
  const response = await frappe.call({method: 'webshop.callus_storefront.hospice_trips.trip_options',
    args: {order_name: frm.doc.name}, freeze: true});
  if (!response.message) return;
  const data = response.message;
  const fields = [
    {fieldtype: 'Select', fieldname: 'delivery_note', label: __('Delivery Note'),
      options: data.delivery_notes, default: data.delivery_notes[0], reqd: 1},
    {fieldtype: 'HTML', options: `<p>${__('The trip will remain a draft. Review and submit it separately to release it to the driver.')}</p>`}
  ];
  if (create) fields.push(
    {fieldtype: 'Link', fieldname: 'driver', label: __('Driver'), options: 'Driver', reqd: 1,
      get_query: () => ({filters: {status: 'Active'}})},
    {fieldtype: 'Link', fieldname: 'vehicle', label: __('Vehicle'), options: 'Vehicle', reqd: 1},
    {fieldtype: 'Datetime', fieldname: 'departure_time', label: __('Departure Time'), reqd: 1, default: data.departure_time}
  );
  else fields.push({fieldtype: 'Link', fieldname: 'trip_name', label: __('Draft Delivery Trip'),
    options: 'Delivery Trip', reqd: 1, get_query: () => ({filters: {
      docstatus: 0, company: data.company, custom_is_bowser_trip: 0
    }})});
  const dialog = new frappe.ui.Dialog({title: __(create ? 'New delivery trip' : 'Add to delivery trip'), fields,
    primary_action_label: __(create ? 'Create draft trip' : 'Add to draft trip'), async primary_action() {
      const values = dialog.get_values();
      if (!values) return;
      dialog.get_primary_btn().prop('disabled', true);
      try {
        const result = await frappe.call({method: 'webshop.callus_storefront.hospice_trips.add_to_trip',
          args: {order_name: frm.doc.name, ...values}, freeze: true});
        if (!result.message) return;
        dialog.hide();
        frappe.set_route('Form', 'Delivery Trip', result.message.name);
      } finally { dialog.get_primary_btn().prop('disabled', false); }
    }});
  dialog.show();
}
