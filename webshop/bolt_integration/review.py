"""Manager resolution of reviewed events and financially reversed cancellations."""
from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlparse

import frappe
from frappe.utils import get_url


def amount(value):
    return Decimal(str(value or 0))


def require(condition, message):
    if not condition:
        frappe.throw(message)


def context(reason):
    frappe.only_for('System Manager')
    require(isinstance(reason, str) and 10 <= len(reason.strip()) <= 2000,
            'Enter a review reason of 10 to 2000 characters.')
    settings = frappe.get_single('Callus Bolt Settings')
    require(urlparse(get_url()).hostname == settings.site_hostname, 'Bolt site binding does not match.')
    return settings, reason.strip()


def fully_reversed(original, returns):
    """Verify complete item/warehouse and amount reversal, not merely a linked return."""
    require(bool(returns), 'A submitted return is required.')
    remaining = defaultdict(Decimal)
    for row in original.items:
        remaining[(row.item_code, row.warehouse, row.stock_uom)] += amount(row.stock_qty)
    total = amount(original.grand_total)
    for doc in returns:
        require(doc.docstatus == 1 and doc.is_return and doc.return_against == original.name
                and doc.company == original.company and doc.customer == original.customer
                and doc.currency == original.currency, 'Return does not match the original sale.')
        require(abs(amount(doc.outstanding_amount)) <= Decimal('0.01'), 'Return payment reconciliation is incomplete.')
        total += amount(doc.grand_total)
        for row in doc.items:
            remaining[(row.item_code, row.warehouse, row.stock_uom)] += amount(row.stock_qty)
    require(abs(total) <= Decimal('0.01') and all(abs(v) < Decimal('0.000001') for v in remaining.values()),
            'The complete sale and stock quantities must be reversed before resolving this order.')


def verify_sale(order):
    dt = 'POS Invoice' if order.pos_invoice else 'Sales Invoice'
    name = order.pos_invoice or order.sales_invoice
    if not name:
        return []
    original = frappe.get_doc(dt, name, for_update=True)
    # Consolidated POS cancellation must be handled through normal returns.
    require(original.docstatus == 1, 'Original sale must be submitted; review its cancellation separately.')
    returns = [frappe.get_doc(dt, n, for_update=True) for n in frappe.get_all(dt,
        filters={'return_against': name, 'is_return': 1, 'docstatus': 1}, pluck='name')]
    fully_reversed(original, returns)
    if dt == 'POS Invoice':
        tenders = defaultdict(Decimal)
        for invoice in [original, *returns]:
            for payment in invoice.payments:
                tenders[(payment.mode_of_payment, payment.account)] += amount(payment.amount)
        require(all(abs(v) <= Decimal('0.01') for v in tenders.values()),
                'Returns must reverse the original payment method and clearing account.')
        require(bool(original.consolidated_invoice), 'Close the original POS shift first.')
        source = frappe.get_doc('Sales Invoice', original.consolidated_invoice, for_update=True)
        credits = []
        for ret in returns:
            require(bool(ret.consolidated_invoice), 'Close the return POS shift before resolving this order.')
            credit = frappe.get_doc('Sales Invoice', ret.consolidated_invoice, for_update=True)
            require(credit.docstatus == 1 and credit.is_return and credit.return_against == source.name
                    and bool(credit.update_stock) == bool(source.update_stock),
                    'The consolidated credit note must reverse the original invoice and its stock.')
            credits.append(credit.name)
        return [r.name for r in returns] + sorted(set(credits))
    require(all(bool(r.update_stock) == bool(original.update_stock) for r in returns),
            'Returns must reverse the original stock posting.')
    return [r.name for r in returns]


@frappe.whitelist(methods=['POST'])
def resolve_review(doctype, name, reason):
    settings, reason = context(reason)
    require(doctype in ('Callus Bolt Order', 'Callus Bolt Event'), 'Unsupported review document.')
    doc = frappe.get_doc(doctype, name, for_update=True)
    require(doc.provider_id == settings.provider_id, 'Document belongs to another Bolt provider.')
    references = []
    if doctype == 'Callus Bolt Order':
        require(doc.environment == settings.environment and doc.workflow_state == 'Needs attention',
                'Only an order needing attention in this environment can be resolved.')
        require(bool(frappe.db.exists('Callus Bolt Event', {'provider_id': doc.provider_id,
            'bolt_order_id': doc.bolt_order_id, 'event_type': 'cancel_order', 'provider_verified': 1})),
            'A verified Bolt cancellation is required.')
        references = verify_sale(doc)
        if doc.sales_order:
            so = frappe.get_doc('Sales Order', doc.sales_order, for_update=True)
            require(not so.per_delivered and not so.per_billed, 'Review delivered or billed Sales Order before resolving.')
            if so.docstatus == 1:
                so.check_permission('cancel')
                so.cancel()
        values = {'status': 'Cancelled', 'workflow_state': 'Cancelled', 'operation_error': ''}
    else:
        require(doc.status == 'Review', 'Only an event needing review can be resolved.')
        orders = frappe.get_all('Callus Bolt Order', filters={'provider_id': doc.provider_id,
            'bolt_order_id': doc.bolt_order_id}, fields=['status', 'environment'])
        synthetic = settings.environment == 'Staging' and (doc.is_test or
            (doc.bolt_order_id or '').startswith(('BOLT-UAT-', 'BOLT-POS-UAT-')))
        require(all(o.status == 'Cancelled' and o.environment == settings.environment for o in orders)
                and (bool(orders) or synthetic),
                'Resolve the linked order first. Unlinked live order events cannot be dismissed.')
        values = {'status': 'Ignored'}  # Preserve the original payload and processing error.
    from frappe.utils import escape_html
    doc.add_comment('Comment', escape_html('Manager review by ' + frappe.session.user + ': ' + reason
                    + (' | Verified returns: ' + ', '.join(references) if references else '')))
    doc.db_set(values)
    return {'status': values['status'], 'references': references}
