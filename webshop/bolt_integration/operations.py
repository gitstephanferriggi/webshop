"""Server-authoritative Bolt POS operations. Disabled until explicitly configured.

Remote actions are durably marked Sending before calling Bolt. Ambiguous outcomes
are never automatically retried. Ordinary POS carts, tenders and shifts are untouched.
"""
import json
import time
from urllib.parse import urlparse
import frappe
from frappe.utils import get_url, now_datetime
from webshop.bolt_integration import client
from webshop.bolt_integration.workflow import (
    REMOTE, TARGET, TERMINAL, check_action, validate_picks, all_picked, numeric_order_id,
)

OPERATOR = 'Bolt Order Operator'
MANAGER = 'Bolt Order Manager'


def settings(profile):
    if frappe.session.user == 'Guest':
        frappe.throw('Sign in to handle Bolt orders.', frappe.PermissionError)
    s = frappe.get_single('Callus Bolt Settings')
    if not s.enabled or not s.two_way_enabled or not s.process_orders:
        return None
    if urlparse(get_url()).hostname != s.site_hostname:
        frappe.throw('Bolt site binding does not match.', frappe.PermissionError)
    roles = frappe.get_roles()
    if not set(roles).intersection((OPERATOR, MANAGER, 'System Manager')):
        frappe.throw('Bolt order access is not assigned to this user.', frappe.PermissionError)
    if not s.pos_profile or profile != s.pos_profile:
        frappe.throw('Switch to the POS Profile assigned to Bolt orders.', frappe.PermissionError)
    pos = frappe.get_doc('POS Profile', s.pos_profile)
    if pos.company != s.company or pos.warehouse != s.warehouse or not s.warehouse:
        frappe.throw('Bolt company and warehouse must match its POS Profile.')
    if 'System Manager' not in roles and frappe.session.user not in [r.user for r in pos.applicable_for_users]:
        frappe.throw('This user is not assigned to the Bolt POS Profile.', frappe.PermissionError)
    if frappe.db.get_value('Warehouse', s.warehouse, 'company') != s.company:
        frappe.throw('Bolt warehouse does not belong to this company.')
    return s


def locked_order(name, s):
    frappe.db.sql('select name from `tabCallus Bolt Order` where name=%s for update', (name,))
    order = frappe.get_doc('Callus Bolt Order', name)
    if (order.provider_id != s.provider_id or order.environment != s.environment
            or not order.workflow_state):
        frappe.throw('Order is outside this Bolt workspace.', frappe.PermissionError)
    return order


def lines(order):
    so = frappe.get_doc('Sales Order', order.sales_order)
    return [{'id': r.name, 'code': r.item_code, 'name': r.item_name, 'qty': r.qty, 'rate': r.rate,
             'uom': r.uom, 'image': r.image if (r.image or '').startswith('/files/') else '',
             'barcodes': frappe.get_all('Item Barcode', filters={'parent': r.item_code, 'parenttype': 'Item'}, pluck='barcode')}
            for r in so.items]


def dto(order):
    keys = ('name', 'modified', 'bolt_order_id', 'order_reference', 'workflow_state',
            'acknowledged_by', 'assigned_to', 'source_amount', 'order_type', 'due_at',
            'acceptance_deadline', 'operation', 'operation_state', 'operation_error',
            'sales_order', 'sales_invoice', 'pos_invoice', 'handover_at', 'courier_pickup_ts', 'attention_from')
    result = {k: order.get(k) for k in keys}
    result['picks'] = json.loads(order.picking or '{}')
    return result


@frappe.whitelist(methods=['GET', 'POST'])
def queue(profile):
    s = settings(profile)
    if not s:
        return {'enabled': False, 'orders': []}
    names = frappe.get_all('Callus Bolt Order', filters={'provider_id': s.provider_id,
        'environment': s.environment, 'workflow_state': ['not in', ['', *TERMINAL]]},
        order_by='creation asc', pluck='name', limit_page_length=201)
    recent = frappe.get_all('Callus Bolt Order', filters={'provider_id': s.provider_id,
        'environment': s.environment, 'workflow_state': ['in', list(TERMINAL)]},
        order_by='modified desc', pluck='name', limit_page_length=30)
    reviews = frappe.db.count('Callus Bolt Event', {'provider_id': s.provider_id, 'status': 'Review'})
    return {'store_status': s.get('provider_status') or 'unknown', 'store_action_state': s.get('store_action_state') or '',
            'store_action': s.get('store_action') or '',
            'store_action_at': s.get('store_action_at'), 'store_status_at': s.get('provider_status_at'),
            'review_events': reviews, 'recent': [dto(frappe.get_doc('Callus Bolt Order', n)) for n in recent],
            'enabled': True, 'orders': [dto(frappe.get_doc('Callus Bolt Order', n)) for n in names[:200]],
            'overflow': len(names) > 200, 'user': frappe.session.user,
            'can_reject': bool(set(frappe.get_roles()).intersection((MANAGER, 'System Manager')))}


@frappe.whitelist(methods=['GET', 'POST'])
def detail(profile, name):
    s = settings(profile)
    if not s:
        frappe.throw('Bolt operations are disabled.')
    order = locked_order(name, s)
    result = dto(order)
    result['lines'] = lines(order)
    result['courier'] = {}
    events = frappe.get_all('Callus Bolt Event', filters={'provider_id': s.provider_id,
        'bolt_order_id': order.bolt_order_id, 'event_type': 'courier_details', 'provider_verified': 1},
        fields=['payload'], order_by='creation desc', limit_page_length=1)
    if events:
        courier = json.loads(events[0].payload).get('courier', {})
        result['courier'] = {k: str(courier.get(k) or '')[:100] for k in ('partial_name', 'phone', 'eta_ts')}
    originals = frappe.get_all('Callus Bolt Event', filters={'provider_id': s.provider_id,
        'bolt_order_id': order.bolt_order_id, 'event_type': 'new_order', 'provider_verified': 1},
        fields=['payload'], order_by='creation asc', limit_page_length=1)
    result['instructions'] = str(json.loads(originals[0].payload).get('user_note') or '')[:2000] if originals else ''
    return result


def save(order):
    order.save(ignore_permissions=True)


@frappe.whitelist(methods=['POST'])
def act(profile, name, action, version, quantities=None, note=None, replacements=None, preview_token=None):
    s = settings(profile)
    if not s:
        frappe.throw('Bolt operations are disabled.')
    order = locked_order(name, s)
    if str(order.modified) != str(version):
        frappe.throw('Another terminal updated this order. Refresh before continuing.')
    if action in ('takeover', 'ready_adjusted'):
        if not set(frappe.get_roles()).intersection((MANAGER, 'System Manager')):
            frappe.throw('Only a Bolt manager can take over picking.', frappe.PermissionError)
    check_action(order.workflow_state, action, order.operation_state, order.payment_type)
    if action == 'acknowledge':
        order.acknowledged_by = frappe.session.user
        order.acknowledged_at = now_datetime()
        save(order)
        return dto(order)
    if action == 'takeover':
        order.assigned_to = frappe.session.user
        save(order)
        return dto(order)
    if action == 'shortage':
        if not note or len(note.strip()) < 5 or len(note) > 500:
            frappe.throw('Describe the shortage or problem (5–500 characters).')
        order.attention_from = order.workflow_state
        order.workflow_state = 'Needs attention'
        order.operation_error = note.strip()
        save(order)
        return dto(order)
    if action == 'reject' and not set(frappe.get_roles()).intersection((MANAGER, 'System Manager')):
        frappe.throw('A Bolt manager must reject the order.', frappe.PermissionError)
    if action in ('pick', 'ready', 'ready_adjusted', 'handover') and order.assigned_to != frappe.session.user:
        frappe.throw('This order is assigned to another picker.')
    if action == 'pick':
        quantities = frappe.parse_json(quantities)
        order.picking = json.dumps(validate_picks(lines(order), quantities))
        save(order)
        return dto(order)
    if action in REMOTE and frappe.db.exists('Callus Bolt Event', {'provider_id': s.provider_id, 'bolt_order_id': order.bolt_order_id, 'event_type': 'cancel_order'}):
        frappe.throw('Bolt has sent a cancellation. Do not change this order.')
    if action == 'accept':
        from webshop.bolt_integration.pos_sales import context
        context(s)
        if order.acceptance_deadline and time.time() >= order.acceptance_deadline:
            frappe.throw('The Bolt acceptance deadline has passed. Ask a manager to check Bolt.')
        if order.order_type != 'delivery':
            frappe.throw('This release supports Bolt-courier delivery only. Ask a manager to review.')
        # Validate ERP submission before contacting Bolt. Any failure rolls back.
        so = frappe.get_doc('Sales Order', order.sales_order)
        if so.company != s.company or so.customer != s.customer:
            frappe.throw('Order accounting configuration does not match.')
        if so.docstatus == 0:
            for row in so.items:
                row.warehouse = s.warehouse
            so.flags.ignore_permissions = True
            so.submit()
        if so.docstatus != 1:
            frappe.throw('The linked Sales Order cannot be fulfilled.')
    if action == 'ready' and not all_picked(lines(order), json.loads(order.picking or '{}')):
        frappe.throw('Pick every item before marking this order ready.')
    if action == 'handover':
        if frappe.db.exists('Callus Bolt Event', {'provider_id': s.provider_id, 'bolt_order_id': order.bolt_order_id, 'event_type': 'cancel_order'}):
            frappe.throw('Bolt has sent a cancellation. Do not hand over the order.')
        if order.order_type != 'delivery':
            frappe.throw('Only Bolt-courier handover is supported.')
        if not note or note.strip() != order.order_reference:
            frappe.throw('Enter the customer order reference to confirm handover.')
        # Delivery handover is an internal record, never markOrderAsPickedUp.
        record_sale(order, s)
        order.workflow_state = 'Collected'
        order.handover_by = frappe.session.user
        order.handover_at = now_datetime()
        save(order)
        return dto(order)
    if action not in REMOTE:
        frappe.throw('Unsupported Bolt action.')
    payload = {'provider_id': s.provider_id, 'order_id': numeric_order_id(order.bolt_order_id)}
    if action == 'ready_adjusted':
        if not note or not 5 <= len(note.strip()) <= 500:
            frappe.throw('Explain the adjustment (5–500 characters).')
        plan = adjustment(order, s, quantities, replacements)
        if plan['token'] != preview_token:
            frappe.throw('Review the current adjustment and refund before confirming.')
        order.adjustment_plan = json.dumps(plan)
        order.adjustment_reason = note.strip()
        payload['items'] = plan['items']
    if action == 'reject':
        if not note or not 5 <= len(note.strip()) <= 500:
            frappe.throw('Explain the rejection (5–500 characters).')
        payload.update(reject_reason='other', reject_comment=note.strip())
    order.operation = action
    order.operation_state = 'Sending'
    order.operation_started = now_datetime()
    order.operation_error = ''
    save(order)
    # Deliberately commit before external I/O. Worker interruption leaves a durable
    # Sending record; neither duplicate clicks nor retries repeat the remote call.
    frappe.db.commit()
    try:
        client.request(s, '/genericClient/' + REMOTE[action], payload)
    except Exception:
        order = locked_order(name, s)
        order.operation_state = 'Review'
        order.workflow_state = 'Needs attention'
        order.operation_error = 'Bolt did not confirm the action. Check Bolt before retrying; the remote outcome may be unknown.'
        save(order)
        frappe.db.commit()
        return dto(order)
    order = locked_order(name, s)
    order.operation_state = 'Confirmed'
    if order.status == 'Cancelled' or order.workflow_state == 'Needs attention':
        order.workflow_state = 'Needs attention'
        order.operation_error = 'Bolt confirmed an action while another event changed the order. Manager review is required.'
    else:
        if action == 'ready_adjusted':
            order.workflow_state = 'Needs attention'
            order.operation_error = 'Bolt confirmed the adjustment. Final basket reconciliation is pending.'
            save(order)
            frappe.db.commit()
            return reconcile_adjustment(profile, name)
        order.workflow_state = TARGET[action]
        if action == 'accept':
            order.assigned_to = frappe.session.user
            order.acknowledged_by = frappe.session.user
            order.acknowledged_at = now_datetime()
        if action == 'reject':
            from webshop.bolt_integration.processing import cancel_sale
            cancel_sale(order)
    save(order)
    return dto(order)


def record_sale(order, s):
    """Record the Bolt tender in the cashier's active shift, exactly once."""
    pos_invoice = getattr(order, 'pos_invoice', None)
    existing = pos_invoice or order.sales_invoice
    if existing:
        inv = frappe.get_doc('POS Invoice' if pos_invoice else 'Sales Invoice', existing)
        if inv.docstatus != 1:
            frappe.throw('The existing invoice needs manager review.')
        return
    from webshop.bolt_integration.pos_sales import context, as_pos_invoice
    profile, shift, mode, account = context(s)
    from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
    inv = make_sales_invoice(order.sales_order, ignore_permissions=True)
    if profile.get('create_pos_invoice_instead_of_sales_invoice'):
        inv = as_pos_invoice(inv)
        # The Sales Order mapper calculates SI outstanding before POS payments exist.
        # POS Invoice validation does not recalculate this Sales-Invoice-only field.
        inv.outstanding_amount = 0
    inv.flags.ignore_permissions = True
    inv.is_pos = 1
    inv.pos_profile = profile.name
    inv.posa_pos_opening_shift = shift.name
    inv.owner = frappe.session.user
    inv.update_stock = 1
    inv.set_warehouse = s.warehouse
    inv.disable_rounded_total = 1
    inv.ignore_pricing_rule = 1
    inv.set('payments', [{'mode_of_payment': mode, 'account': account,
                          'amount': float(order.source_amount)}])
    for row in inv.items:
        row.warehouse = s.warehouse
    inv.insert(ignore_permissions=True)
    if (abs(float(inv.grand_total) - float(order.source_amount)) > .01
            or len(inv.payments) != 1 or inv.payments[0].mode_of_payment != mode
            or inv.payments[0].account != account
            or abs(float(inv.paid_amount) - float(inv.grand_total)) > .01
            or abs(float(inv.change_amount or 0)) > .01):
        frappe.throw('Bolt invoice total or payment differs. Handover was not recorded.')
    inv.submit()
    if inv.doctype == 'POS Invoice':
        order.pos_invoice = inv.name
    else:
        order.sales_invoice = inv.name
    order.status = 'Recorded'


def flag_interrupted_actions():
    """Surface interrupted requests; never resend an action with an unknown outcome."""
    from datetime import timedelta
    s = frappe.get_single('Callus Bolt Settings')
    if not s.enabled or not s.two_way_enabled or urlparse(get_url()).hostname != s.site_hostname:
        return
    cutoff = now_datetime() - timedelta(minutes=3)
    names = frappe.get_all('Callus Bolt Order', filters={'provider_id': s.provider_id,
        'environment': s.environment, 'operation_state': 'Sending', 'operation_started': ['<', cutoff]}, pluck='name')
    for name in names:
        order = locked_order(name, s)
        if order.operation_state == 'Sending' and order.operation_started < cutoff:
            order.operation_state = 'Review'
            order.workflow_state = 'Needs attention'
            order.operation_error = 'The action was interrupted without confirmation. A manager must verify Bolt before any retry.'
            save(order)


def require_manager():
    if not set(frappe.get_roles()).intersection((MANAGER, 'System Manager')):
        frappe.throw('A Bolt manager must approve this action.', frappe.PermissionError)


def replacement_catalogue(s):
    from webshop.bolt_integration.sync import snapshot
    data = snapshot(s)
    published = set(json.loads(s.last_synced_skus or '[]'))
    prices = {r['sku']: r['base_selling_price'] for r in data['prices'] if r['sku'] in published}
    return data, prices


@frappe.whitelist(methods=['GET', 'POST'])
def replacements(profile):
    s = settings(profile)
    if not s:
        frappe.throw('Bolt operations are disabled.')
    require_manager()
    data, prices = replacement_catalogue(s)
    return [{'code': r['sku'], 'name': r['name']['en-US'], 'price': prices[r['sku']]}
            for r in data['products'] if r['sku'] in prices]


def adjustment(order, s, quantities, replacements):
    from webshop.bolt_integration.adjustments import build_adjustment
    import hashlib
    _, prices = replacement_catalogue(s)
    plan = build_adjustment(lines(order), frappe.parse_json(quantities), frappe.parse_json(replacements or '{}'), prices)
    plan['original_total'] = order.source_amount
    if plan['expected_total'] > float(order.source_amount):
        frappe.throw('An adjustment cannot increase the customer charge.')
    plan['token'] = hashlib.sha256(json.dumps([order.name, str(order.modified), plan], sort_keys=True).encode()).hexdigest()
    return plan


@frappe.whitelist(methods=['POST'])
def preview_adjustment(profile, name, version, quantities, replacements=None):
    s = settings(profile)
    if not s:
        frappe.throw('Bolt operations are disabled.')
    require_manager()
    order = locked_order(name, s)
    if str(order.modified) != str(version):
        frappe.throw('Refresh this order before reviewing adjustments.')
    check_action(order.workflow_state, 'ready_adjusted', order.operation_state, order.payment_type)
    return adjustment(order, s, quantities, replacements)


@frappe.whitelist(methods=['POST'])
def reconcile_adjustment(profile, name):
    """Retry only the read/reconciliation step after a confirmed remote adjustment."""
    s = settings(profile)
    if not s:
        frappe.throw('Bolt operations are disabled.')
    require_manager()
    order = locked_order(name, s)
    if order.operation != 'ready_adjusted' or order.operation_state != 'Confirmed':
        frappe.throw('Bolt has not confirmed an adjusted-ready request. Verify with Bolt support.')
    if order.workflow_state in ('Ready', 'Collected'):
        return dto(order)
    if order.status == 'Cancelled' or order.get('attention_from'):
        frappe.throw('This order has another unresolved event. Manager review is required.')
    if frappe.db.exists('Callus Bolt Event', {'provider_id': s.provider_id, 'bolt_order_id': order.bolt_order_id, 'event_type': 'cancel_order'}):
        frappe.throw('Bolt has sent a cancellation. Resolve that before reconciliation.')
    plan = json.loads(order.adjustment_plan)
    frappe.db.savepoint('bolt_adjustment')
    try:
        from webshop.bolt_integration.adjustments import confirmed_basket
        basket = client.request(s, '/genericClient/getOrderBasket',
            {'provider_id': s.provider_id, 'order_id': numeric_order_id(order.bolt_order_id)})
        payload = confirmed_basket(basket, order.bolt_order_id, plan['expected'], plan['original_total'])
        amend_sale(order, s, payload)
        order.workflow_state = 'Ready'
        order.operation_error = ''
        order.picking = json.dumps({r['id']: r['qty'] for r in lines(order)})
        save(order)
    except Exception as exc:
        frappe.db.rollback(save_point='bolt_adjustment')
        order = locked_order(name, s)
        order.workflow_state = 'Needs attention'
        order.operation_error = 'Bolt confirmed readiness; ERP reconciliation failed: ' + str(exc)[:350]
        save(order)
    return dto(order)


def amend_sale(order, s, payload):
    from webshop.bolt_integration.orders import sales_lines, money
    from frappe.utils import nowdate
    if order.sales_invoice or getattr(order, 'pos_invoice', None):
        frappe.throw('An invoiced order cannot be adjusted by this workflow.')
    original = frappe.get_doc('Sales Order', order.sales_order)
    if original.docstatus != 1 or original.per_delivered or original.per_billed:
        frappe.throw('The Sales Order is no longer eligible for adjustment.')
    amended = frappe.copy_doc(original)
    amended.amended_from = original.name
    amended.docstatus = 0
    amended.flags.ignore_permissions = True
    rows = sales_lines(payload, lambda code: frappe.db.get_value('Item', code,
        ['stock_uom', 'disabled', 'is_sales_item'], as_dict=True))
    for row in rows:
        row.update(warehouse=s.warehouse, delivery_date=nowdate())
    amended.set('items', rows)
    amended.ignore_pricing_rule = 1
    amended.disable_rounded_total = 1
    amended.calculate_taxes_and_totals()
    if abs(money(amended.grand_total) - money(payload['total_order_price']['value'])) > money('.01'):
        frappe.throw('Adjusted ERP tax total differs from Bolt.')
    original.flags.ignore_permissions = True
    original.cancel()
    amended.insert(ignore_permissions=True)
    if abs(money(amended.grand_total) - money(payload['total_order_price']['value'])) > money('.01'):
        frappe.throw('ERP validation changed the adjusted total. Review before handover.')
    amended.submit()
    order.sales_order = amended.name
    order.source_amount = float(money(payload['total_order_price']['value']))
    # Keep source_hash as the ORIGINAL receipt hash for duplicate new_order callbacks.


@frappe.whitelist(methods=['POST'])
def store_status(profile, action):
    """Serialize store controls across terminals; never blindly repeat an uncertain call."""
    require_manager()
    s = settings(profile)
    if not s:
        frappe.throw('Bolt operations are disabled.')
    if action not in ('open', 'pause'):
        frappe.throw('Choose open or pause.')
    with frappe.cache().lock('callus-bolt-store-control', timeout=90, blocking_timeout=1):
        s.reload()
        if s.store_action_state in ('Sending', 'Review'):
            frappe.throw('The previous store change is unconfirmed. Check Bolt before retrying.')
        frappe.db.set_single_value('Callus Bolt Settings', {
            'store_action': action, 'store_action_state': 'Sending',
            'store_action_at': now_datetime(), 'store_action_by': frappe.session.user})
        frappe.db.commit()
        try:
            client.request(s, '/genericClient/' + ('startAcceptingOrders' if action == 'open' else 'pauseOrders'),
                           {'provider_id': s.provider_id})
        except Exception:
            frappe.db.set_single_value('Callus Bolt Settings', 'store_action_state', 'Review')
            frappe.db.commit()
            return {'state': 'Review', 'message': 'Bolt did not confirm the store change. Check Bolt before retrying.'}
        frappe.db.set_single_value('Callus Bolt Settings', 'store_action_state', 'Confirmed')
        return {'state': 'Confirmed', 'message': 'Bolt confirmed the request. The reported store status updates via webhook.'}


@frappe.whitelist(methods=['POST'])
def resume_problem(profile, name, version):
    s = settings(profile)
    if not s:
        frappe.throw('Bolt operations are disabled.')
    require_manager()
    order = locked_order(name, s)
    if str(order.modified) != str(version):
        frappe.throw('Refresh this order first.')
    if (order.workflow_state != 'Needs attention' or order.attention_from not in ('New', 'Picking', 'Ready')
            or order.operation_state in ('Sending', 'Review') or order.status == 'Cancelled'):
        frappe.throw('This is not a staff-reported problem that can be resumed.')
    if frappe.db.exists('Callus Bolt Event', {'provider_id': s.provider_id,
            'bolt_order_id': order.bolt_order_id, 'event_type': 'cancel_order'}):
        frappe.throw('Bolt has sent a cancellation. Do not resume fulfilment.')
    order.workflow_state = order.attention_from
    order.attention_from = ''
    order.operation_error = ''
    order.assigned_to = frappe.session.user
    save(order)
    return dto(order)
