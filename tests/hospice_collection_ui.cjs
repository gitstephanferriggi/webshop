// Desk form contract checks; uses the actual Hospice form script and a small Frappe adapter.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
(async () => {
  let handler, dialog, values, fail = false, calls = [], reloads = 0;
  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const frappe = {utils: {escape_html: esc}, ui: {form: {on: (_, obj) => handler = obj}, Dialog: class {
    constructor(options) {this.options=options;dialog=this;this.disabled=false;this.hidden=false;}
    get_values() {return values;} show() {} hide() {this.hidden=true;}
    get_primary_btn() {return {prop: (_, value) => this.disabled=value};}
  }}, show_alert() {}, async call(request) {
    calls.push(request);
    if(request.method.endsWith('.collection_details')) return {message:{items:[{qty:2,item_name:'Plant <img src=x onerror=bad>',uom:'Pcs'}],acknowledgement:'I confirm receipt.'}};
    if(fail) throw new Error('Temporary connection failure');
    return {message:{name:'HO-1'}};
  }};
  const context = {frappe, __: value => value};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../webshop/public/js/hospice_sales_order.js'),'utf8'),context);
  function form(status, write=true) {
    return {doc:{name:'SO-TEST',custom_hospice_order:1,custom_hospice_fulfilment:'Pickup',custom_hospice_status:status,docstatus:1},
      perm:[{write}],buttons:{},set_df_property(){},set_intro(){},add_custom_button(label,callback){this.buttons[label]=callback;},async reload_doc(){reloads++;}};
  }
  const frm=form('Ready for pickup');handler.refresh(frm);
  assert(frm.buttons['Confirm collection']);assert(!frm.buttons['Mark collected']);assert(frm.buttons['Signed receipts']);
  await frm.buttons['Confirm collection']();
  assert(dialog.options.fields.some(field=>field.fieldtype==='Signature'&&field.reqd));
  assert(!dialog.options.fields[0].options.includes('<img'));assert(dialog.options.fields[0].options.includes('&lt;img'));
  values={recipient_name:'Collector',signature:'data:image/png;base64,test',acknowledged:0};
  const before=calls.length;await dialog.options.primary_action();assert.equal(calls.length,before);
  values.acknowledged=1;fail=true;
  await assert.rejects(dialog.options.primary_action());assert.equal(dialog.hidden,false);assert.equal(dialog.disabled,false);
  fail=false;await dialog.options.primary_action();assert.equal(dialog.hidden,true);assert.equal(reloads,1);
  const sent=calls[calls.length-1];assert(sent.method.endsWith('.confirm_collection'));assert.equal(sent.args.order_name,'SO-TEST');
  const collected=form('Collected');handler.refresh(collected);assert(!collected.buttons['Confirm collection']);assert(collected.buttons['Signed receipts']);
  const readonly=form('Ready for pickup',false);handler.refresh(readonly);assert(!readonly.buttons['Confirm collection']);
  console.log('Signed collection UI, permissions, acknowledgement, escaping and retry checks passed.');
})().catch(error=>{console.error(error);process.exit(1);});
