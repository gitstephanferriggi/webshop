"""Idempotent ERP sales processing from the durable Bolt inbox.

Disabled by default. Order acceptance/picking and settlement stay with Bolt.
No customer emails, payment entries or stock ledger postings are initiated here.
"""
import json
import hashlib
import frappe
from frappe.utils import nowdate, get_url
from webshop.bolt_integration.orders import order_key, sales_lines, money


def enabled_settings():
    s=frappe.get_single('Callus Bolt Settings')
    from urllib.parse import urlparse
    if not s.enabled or not s.process_orders:
        return None
    if urlparse(get_url()).hostname != s.site_hostname:
        frappe.throw('Bolt hostname binding mismatch')
    if not all([s.provider_id,s.company,s.customer,s.price_list,s.taxes_and_charges]):
        frappe.throw('Complete Bolt sales configuration first')
    return s


def process_pending():
    s=enabled_settings()
    if not s:
        return
    for name in frappe.get_all('Callus Bolt Event',filters={'status':['in',['Captured','Retry']]},order_by='creation asc',limit=50,pluck='name'):
        frappe.db.savepoint('bolt_process')
        try:
            event=frappe.get_doc('Callus Bolt Event',name)
            process_event(event,s)
            frappe.db.commit()
        except Exception as exc:
            frappe.db.rollback(save_point='bolt_process')
            frappe.db.set_value('Callus Bolt Event',name,{'status':'Review','processing_error':str(exc)[:1000]})
            frappe.db.commit()
            frappe.log_error(title='Bolt order requires review',message=frappe.get_traceback())


def process_event(event,s):
    if event.is_test or not event.provider_verified or event.provider_id!=s.provider_id:
        event.db_set('status','Ignored')
        return
    p=json.loads(event.payload)
    if event.event_type=='provider_status':
        event.db_set('status','Processed')
        return
    key=order_key(event.provider_id,event.bolt_order_id)
    # Unique identity exists even if cancellation arrives before the order.
    if not frappe.db.exists('Callus Bolt Order',key):
        try:
            frappe.get_doc({'doctype':'Callus Bolt Order','name':key,'provider_id':event.provider_id,
                            'bolt_order_id':event.bolt_order_id,'environment':s.environment,
                            'status':'Received'}).insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            pass
    frappe.db.sql('select name from `tabCallus Bolt Order` where name=%s for update',(key,))
    order=frappe.get_doc('Callus Bolt Order',key)
    if event.event_type=='cancel_order':
        cancel_sale(order)
    elif event.event_type=='new_order':
        if order.status=='Cancelled':
            pass # Never resurrect an order cancelled before its creation callback.
        elif order.sales_order:
            if order.source_hash != basket_hash(p):
                frappe.throw('Changed order amount requires staff review')
        else:
            create_sale(order,p,s)
    elif event.event_type=='order_update':
        order.last_bolt_status=p.get('request_type')
    elif event.event_type=='courier_details':
        # Retain courier data only in the restricted event; never public remarks.
        order.last_bolt_status='Courier details received'
    order.save(ignore_permissions=True)
    event.db_set({'status':'Processed','sales_order':order.sales_order,'processing_error':''})


def basket_hash(payload):
    return hashlib.sha256(json.dumps({'items':payload['items'],'total':payload['total_order_price']},sort_keys=True,separators=(',',':')).encode()).hexdigest()


def create_sale(link,p,s):
    rows=sales_lines(p,lambda code:frappe.db.get_value('Item',code,['stock_uom','disabled','is_sales_item'],as_dict=True))
    for r in rows:
        r['delivery_date']=nowdate()
    so=frappe.get_doc({'doctype':'Sales Order','company':s.company,'customer':s.customer,
        'order_type':'Sales','transaction_date':nowdate(),'delivery_date':nowdate(),
        'currency':'EUR','selling_price_list':s.price_list,'ignore_pricing_rule':1,
        'disable_rounded_total':1,'items':rows,'taxes_and_charges':s.taxes_and_charges,
        'remarks':'Bolt Food order '+str(p['order_reference_id'])})
    so.flags.ignore_permissions=True
    so.set_missing_values()
    so.set('taxes',[])
    so.append_taxes_from_master()
    if not so.taxes or any(not x.included_in_print_rate for x in so.taxes if x.charge_type=='On Net Total'):
        frappe.throw('Bolt gross prices require an inclusive ERP tax template')
    so.calculate_taxes_and_totals()
    if abs(money(so.grand_total)-money(p['total_order_price']['value']))>money('0.01'):
        frappe.throw('Bolt and ERP order totals differ')
    so.insert(ignore_permissions=True)
    link.sales_order=so.name
    link.source_amount=float(money(p['total_order_price']['value']))
    link.source_hash=basket_hash(p)
    link.status='Draft Sale'
    if s.submit_sales:
        so.submit()
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
        invoice=make_sales_invoice(so.name,ignore_permissions=True)
        invoice.flags.ignore_permissions=True
        invoice.update_stock=0
        invoice.disable_rounded_total=1
        invoice.insert(ignore_permissions=True)
        if abs(money(invoice.grand_total)-money(p['total_order_price']['value']))>money('0.01'):
            frappe.throw('Bolt and ERP invoice totals differ')
        invoice.submit()
        link.sales_invoice=invoice.name
        link.status='Recorded'


def cancel_sale(link):
    if link.sales_invoice:
        inv=frappe.get_doc('Sales Invoice',link.sales_invoice)
        if inv.docstatus==1:
            if inv.update_stock or abs(inv.outstanding_amount-inv.grand_total)>.01:
                frappe.throw('Paid or stock-posted invoice requires normal refund/return review')
            inv.flags.ignore_permissions=True
            inv.cancel()
    if link.sales_order:
        so=frappe.get_doc('Sales Order',link.sales_order)
        if so.per_delivered:
            frappe.throw('Delivered Bolt order requires return review')
        if so.docstatus==1:
            so.flags.ignore_permissions=True
            so.cancel()
        # Retain a draft with an explicit cancellation marker for the audit trail.
        elif so.docstatus==0:
            so.add_comment('Comment', 'Cancelled by Bolt; do not fulfil.')
    link.status='Cancelled'


@frappe.whitelist(methods=['POST'])
def run_now():
    """System Manager maintenance action; webhook credentials cannot call it."""
    frappe.only_for('System Manager')
    process_pending()
    return {'ok':True}
