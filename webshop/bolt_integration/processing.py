"""Idempotent ERP sales processing from the durable Bolt inbox.

Disabled by default. Optional POS operations enrol new orders into a separate workflow.
No customer emails, payment entries or stock ledger postings are initiated here.
"""
import json
import hashlib
from contextlib import contextmanager
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


@contextmanager
def _processing_user():
    """Elevate private ERP work, never the webhook account or its API access."""
    user = frappe.session.user
    session = dict(frappe.local.session)
    form = frappe.local.form_dict
    try:
        frappe.set_user('Administrator')
        yield
    finally:
        frappe.set_user(user)
        frappe.local.session.update(session)
        frappe.local.form_dict = form


def process_pending():
    s=enabled_settings()
    if not s:
        return
    for name in frappe.get_all('Callus Bolt Event',filters={'status':['in',['Captured','Retry']]},order_by='creation asc',limit=50,pluck='name'):
        frappe.db.savepoint('bolt_process')
        try:
            # Re-read under lock: another worker may have completed this queued event.
            event=frappe.get_doc('Callus Bolt Event',name,for_update=True)
            if event.status not in ('Captured', 'Retry'):
                frappe.db.commit()
                continue
            with _processing_user():
                process_event(event,s)
            frappe.db.commit()
        except Exception as exc:
            frappe.db.rollback(save_point='bolt_process')
            frappe.db.set_value('Callus Bolt Event',name,{'status':'Review','processing_error':(str(exc) or type(exc).__name__)[:1000]})
            frappe.db.commit()
            frappe.log_error(title='Bolt order requires review',message=frappe.get_traceback())


def process_event(event,s):
    if event.is_test or not event.provider_verified or event.provider_id!=s.provider_id:
        event.db_set('status','Ignored')
        return
    p=json.loads(event.payload)
    if event.event_type=='provider_status':
        from frappe.utils import now_datetime
        frappe.db.set_single_value('Callus Bolt Settings', {'provider_status': p['new_status'], 'provider_status_at': now_datetime()})
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
    # A locking read also avoids a stale repeatable-read snapshot after waiting.
    order=frappe.get_doc('Callus Bolt Order',key,for_update=True)
    if event.event_type=='cancel_order':
        if getattr(s, 'two_way_enabled', 0) and order.get('workflow_state'):
            frappe.db.savepoint('bolt_cancel')
            try:
                cancel_sale(order)
                order.workflow_state = 'Cancelled'
            except Exception:
                frappe.db.rollback(save_point='bolt_cancel')
                order = frappe.get_doc('Callus Bolt Order', key)
                order.workflow_state = 'Needs attention'
                order.operation_error = 'Bolt cancelled this order. Its posted sale or stock requires manager return/refund review.'
        else:
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
    elif event.event_type=='courier_picked_up':
        order.courier_pickup_ts = max(order.get('courier_pickup_ts') or 0, p['pickup_ts'])
        order.last_bolt_status = 'Courier picked up order'
        # Preserve accounting and cancellation states. A callback is not a new sale.
        if order.status == 'Cancelled':
            order.workflow_state = 'Needs attention'
            order.operation_error = 'Bolt reports pickup of a cancelled order. Manager review required.'
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
    if getattr(s, 'two_way_enabled', 0):
        link.workflow_state = 'New'
        link.order_reference = str(p.get('order_reference_id') or p['order_id'])
        link.order_type = p.get('order_type')
        link.payment_type = p.get('payment_type')
        link.acceptance_deadline = p.get('max_acceptance_ts') or 0
        link.due_at = site_due_at(p['due_ts'])
        link.picking = '{}'
        if link.get('courier_pickup_ts'):
            link.workflow_state = 'Needs attention'
            link.operation_error = 'Pickup arrived before the order. Verify with Bolt before fulfilling.'
        if link.payment_type != 'card_online' or link.order_type != 'delivery':
            link.workflow_state = 'Needs attention'
            link.operation_error = 'Unsupported payment or delivery type. Contact Bolt before fulfilment.'
    elif s.submit_sales:
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
    if getattr(link, 'pos_invoice', None):
        frappe.throw('Bolt POS sale requires manager return/refund review, including any consolidated invoice.')
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


@frappe.whitelist(methods=['POST'])
def retry_event(name):
    """Manager recovery without granting callers write access to the inbox."""
    frappe.only_for('System Manager')
    event = frappe.get_doc('Callus Bolt Event', name, for_update=True)
    if event.status != 'Review':
        frappe.throw('Only an event requiring review can be retried.')
    event.db_set({'status': 'Retry', 'processing_error': ''})
    process_pending()
    event.reload()
    return {'status': event.status, 'sales_order': event.get('sales_order'),
            'processing_error': event.get('processing_error')}


def site_due_at(timestamp):
    """Frappe Datetime columns store site-local wall time without a UTC offset."""
    from datetime import datetime, timezone
    from frappe.utils import convert_utc_to_system_timezone
    utc_time = datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)
    return convert_utc_to_system_timezone(utc_time).replace(tzinfo=None)
