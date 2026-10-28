// Exercise the actual Desk script's trip dialogs and action visibility.
const assert = require('assert'), fs = require('fs'), vm = require('vm'), path = require('path');
(async () => {
  let handler, dialog, values, calls=[], route, fail=false;
  const frappe={model:{can_create:()=>true,can_write:()=>true}, ui:{form:{on:(_,h)=>handler=h},Dialog:class{
    constructor(options){this.options=options;dialog=this;this.disabled=false;this.hidden=false;}
    show(){} hide(){this.hidden=true;}get_values(){return values;}
    get_primary_btn(){return {prop:(_,v)=>this.disabled=v};}
  }},async call(r){calls.push(r);if(fail)throw Error('Connection lost');
    return {message:r.method.endsWith('trip_options')?{company:'Shop',delivery_notes:['DN-1'],departure_time:'2026-10-28 12:00:00'}:{name:'TRIP-1'}};
  },set_route(...r){route=r;},msgprint(){},utils:{escape_html:x=>x}};
  const ctx={frappe,__:x=>x};vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../webshop/public/js/hospice_sales_order.js'),'utf8'),ctx);
  const form=(status='Ready for dispatch',pickup=false,write=true)=>({doc:{name:'SO-1',docstatus:1,custom_hospice_order:1,
    custom_hospice_fulfilment:pickup?'Pickup':'Delivery',custom_hospice_status:status},perm:[{write}],buttons:{},
    is_dirty:()=>false,set_df_property(){},set_intro(){},add_custom_button(l,cb){this.buttons[l]=cb;}});
  const frm=form();handler.refresh(frm);assert(frm.buttons['New delivery trip']);assert(frm.buttons['Add to delivery trip']);
  await frm.buttons['New delivery trip']();
  assert(dialog.options.fields.some(f=>f.fieldname==='driver'&&f.reqd));
  assert(dialog.options.fields.some(f=>f.fieldname==='vehicle'&&f.reqd));
  assert(dialog.options.fields.some(f=>f.fieldname==='departure_time'&&f.reqd));
  values={delivery_note:'DN-1',driver:'DRIVER',vehicle:'VAN',departure_time:'2026-10-28 12:00:00'};
  fail=true;await assert.rejects(dialog.options.primary_action());assert(!dialog.hidden);assert(!dialog.disabled);
  fail=false;await dialog.options.primary_action();assert(dialog.hidden);assert.equal(route.join('/'),'Form/Delivery Trip/TRIP-1');
  assert.equal(calls.at(-1).args.order_name,'SO-1');assert.equal(calls.at(-1).args.delivery_note,'DN-1');
  await frm.buttons['Add to delivery trip']();
  const link=dialog.options.fields.find(f=>f.fieldname==='trip_name');assert(link);assert.equal(link.get_query().filters.docstatus,0);
  assert.equal(link.get_query().filters.company,'Shop');assert.equal(link.get_query().filters.custom_is_bowser_trip,0);
  values={delivery_note:'DN-1',trip_name:'DRAFT-1'};await dialog.options.primary_action();assert.equal(calls.at(-1).args.trip_name,'DRAFT-1');
  for(const other of [form('Ready for pickup',true),form('Ready for dispatch',false,false),form('Delivered')]){
    handler.refresh(other);assert(!other.buttons['New delivery trip']);assert(!other.buttons['Add to delivery trip']);
  }
  const dirty=form();dirty.is_dirty=()=>true;handler.refresh(dirty);const before=calls.length;await dirty.buttons['New delivery trip']();assert.equal(calls.length,before);
  console.log('Trip actions, draft filters, scheduling fields, permissions and retry checks passed.');
})().catch(e=>{console.error(e);process.exit(1);});
