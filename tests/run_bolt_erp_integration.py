"""Run from bench sites with --site LOCAL.localhost. All writes are rolled back."""
import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
import uuid
from unittest.mock import patch
parser = argparse.ArgumentParser()
parser.add_argument('--site', required=True)
parser.add_argument('--invoice-mode', choices=('pos','sales'), default='pos')
args = parser.parse_args()
if not args.site.endswith('.localhost'):
    raise SystemExit('Only isolated .localhost sites are permitted')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frappe
frappe.init(site=args.site)
frappe.connect()
# Imported customer Server Scripts are disabled on this isolated bench. Exclude
# only those scripts in this process; standard ERP document hooks still run.
legacy_scripts = patch('frappe.model.document.run_server_script_for_doc_event')
legacy_scripts.start()
try:
    frappe.set_user('Administrator')
    frappe.flags.in_test = True
    from webshop.bolt_integration.operations import amend_sale, record_sale
    from frappe.utils import nowdate
    suffix = uuid.uuid4().hex[:8]
    company = 'Blooming Garden Ltd'
    warehouse = 'Garden Center - BGL'
    customer = frappe.get_doc({'doctype': 'Customer', 'customer_name': 'LOCAL BOLT TEST ' + suffix,
        'customer_type': 'Company', 'customer_group': frappe.db.get_value('Customer Group', {'is_group': 0}, 'name'),
        'territory': frappe.db.get_value('Territory', {'is_group': 0}, 'name')}).insert(ignore_permissions=True)
    code = 'LOCAL-BOLT-' + suffix
    item = frappe.get_doc({'doctype': 'Item', 'item_code': code, 'item_name': code,
        'item_group': frappe.db.get_value('Item Group', {'is_group': 0}, 'name'),
        'stock_uom': 'Pcs', 'is_stock_item': 1, 'is_sales_item': 1}).insert(ignore_permissions=True)
    code = item.name
    from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
    make_stock_entry(item_code=code, qty=10, company=company, to_warehouse=warehouse, rate=2)
    so = frappe.get_doc({'doctype': 'Sales Order', 'company': company, 'customer': customer.name,
        'transaction_date': nowdate(), 'delivery_date': nowdate(), 'currency': 'EUR',
        'selling_price_list': 'Standard Selling', 'ignore_pricing_rule': 1, 'disable_rounded_total': 1,
        'items': [{'item_code': code, 'qty': 3, 'rate': 5, 'warehouse': warehouse, 'delivery_date': nowdate()}]})
    template = frappe.get_doc('Sales Taxes and Charges Template', 'Taxable Goods / Services @ 18%')
    for tax in template.taxes:
        so.append('taxes', {'charge_type': tax.charge_type, 'account_head': tax.account_head, 'rate': tax.rate, 'description': tax.description, 'included_in_print_rate': 1})
    so.flags.ignore_permissions = True
    so.insert(ignore_permissions=True); so.submit()
    link = SimpleNamespace(sales_order=so.name, sales_invoice=None, source_amount=15, status='Draft Sale')
    account = frappe.get_doc({'doctype':'Account','account_name':'LOCAL BOLT CLEARING '+suffix,
        'company':company,'parent_account':'3025-3100 - Other Current Asset - BGL',
        'root_type':'Asset','report_type':'Balance Sheet','account_currency':'EUR','is_group':0}).insert(ignore_permissions=True)
    mode = frappe.get_doc({'doctype':'Mode of Payment','mode_of_payment':'LOCAL BOLT '+suffix,
        'enabled':1,'type':'General','accounts':[{'company':company,'default_account':account.name}]}).insert(ignore_permissions=True)
    profile = frappe.copy_doc(frappe.get_doc('POS Profile','Siggiewi Shop'))
    profile.name='LOCAL BOLT '+suffix
    profile.set('applicable_for_users',[{'user':'Administrator','default':0}])
    profile.warehouse=warehouse
    profile.create_pos_invoice_instead_of_sales_invoice=int(args.invoice_mode=='pos')
    profile.append('payments',{'mode_of_payment':mode.name,'default':0})
    profile.insert(ignore_permissions=True)
    shift=frappe.get_doc({'doctype':'POS Opening Shift','company':company,'pos_profile':profile.name,
        'user':'Administrator','period_start_date':frappe.utils.now_datetime(),
        'balance_details':[{'mode_of_payment':mode.name,'amount':0}]}).insert(ignore_permissions=True)
    shift.submit()
    link.pos_invoice=None
    settings = frappe._dict(warehouse=warehouse,company=company,pos_profile=profile.name,payment_method=mode.name)
    payload = {'items': [{'sku': code, 'qty': 2, 'unit_item_price': {'value': 5, 'currency': 'EUR'},
        'total_item_price': {'value': 10, 'currency': 'EUR'}}], 'total_order_price': {'value': 10, 'currency': 'EUR'}}
    amend_sale(link, settings, payload)
    amended = frappe.get_doc('Sales Order', link.sales_order)
    assert amended.docstatus == 1 and amended.amended_from == so.name
    assert frappe.db.get_value('Sales Order', so.name, 'docstatus') == 2
    assert amended.grand_total == 10 and amended.items[0].qty == 2
    record_sale(link, settings)
    invoice_name = link.pos_invoice or link.sales_invoice
    invoice = frappe.get_doc('POS Invoice' if args.invoice_mode=='pos' else 'Sales Invoice', invoice_name)
    assert invoice.docstatus == 1 and invoice.grand_total == 10
    assert invoice.is_pos == 1
    assert invoice.posa_pos_opening_shift==shift.name and invoice.owner=='Administrator'
    assert len(invoice.payments)==1 and invoice.payments[0].mode_of_payment==mode.name
    assert invoice.payments[0].amount==10 and invoice.outstanding_amount==0, (invoice.payments[0].amount,invoice.paid_amount,invoice.outstanding_amount,invoice.grand_total,invoice.rounded_total)
    record_sale(link, settings)
    assert (link.pos_invoice or link.sales_invoice) == invoice_name
    from posawesome.posawesome.doctype.pos_closing_shift.closing_processing.creation import make_closing_shift_from_opening
    closing=make_closing_shift_from_opening(shift.as_json())['closing_shift']
    if isinstance(closing,dict): closing=frappe.get_doc(closing)
    assert any(row.get('pos_invoice' if args.invoice_mode=='pos' else 'sales_invoice')==invoice_name for row in closing.pos_transactions)
    tender=[row for row in closing.payment_reconciliation if row.mode_of_payment==mode.name]
    assert len(tender)==1 and tender[0].expected_amount==10
    from webshop.bolt_integration.processing import cancel_sale
    try:
        cancel_sale(link)
        raise AssertionError('Paid POS cancellation should require review')
    except frappe.ValidationError:
        pass
    for row in closing.payment_reconciliation:
        row.closing_amount=row.expected_amount
    # Core consolidation commits internally; suppress it only inside this rollback test.
    with patch.object(frappe.db, 'commit'), patch.object(frappe, 'publish_realtime'):
        closing.insert(ignore_permissions=True)
        closing.submit()
    invoice.reload()
    consolidated=frappe.get_doc('Sales Invoice',invoice.consolidated_invoice) if args.invoice_mode=='pos' else invoice
    assert consolidated.docstatus==1 and consolidated.outstanding_amount==0
    assert consolidated.payments[0].mode_of_payment==mode.name
    assert frappe.db.get_value('Bin',{'item_code':code,'warehouse':warehouse},'actual_qty')==8
    assert frappe.db.count('Stock Ledger Entry',{'voucher_no':consolidated.name,'is_cancelled':0})==1
    record_sale(link, settings)
    assert (link.pos_invoice or link.sales_invoice)==invoice_name
    entries=frappe.get_all('GL Entry',filters={'voucher_no':consolidated.name,'account':account.name,'is_cancelled':0},fields=['debit','credit'])
    assert abs(sum(row.debit-row.credit for row in entries)-10)<.01
    assert invoice.total_taxes_and_charges > 0
    print(args.invoice_mode, 'PASS: amended Bolt order, inclusive VAT, paid POS Invoice, cashier shift, separate closing tender, cancellation guard and duplicate prevention')
finally:
    frappe.db.rollback()
    legacy_scripts.stop()
    frappe.destroy()
