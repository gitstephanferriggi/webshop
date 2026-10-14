"""Run from bench sites with --site LOCAL.localhost. All writes are rolled back."""
import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
import uuid
from unittest.mock import patch
parser = argparse.ArgumentParser()
parser.add_argument('--site', required=True)
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
    settings = SimpleNamespace(warehouse=warehouse)
    payload = {'items': [{'sku': code, 'qty': 2, 'unit_item_price': {'value': 5, 'currency': 'EUR'},
        'total_item_price': {'value': 10, 'currency': 'EUR'}}], 'total_order_price': {'value': 10, 'currency': 'EUR'}}
    amend_sale(link, settings, payload)
    amended = frappe.get_doc('Sales Order', link.sales_order)
    assert amended.docstatus == 1 and amended.amended_from == so.name
    assert frappe.db.get_value('Sales Order', so.name, 'docstatus') == 2
    assert amended.grand_total == 10 and amended.items[0].qty == 2
    record_sale(link, settings)
    invoice_name = link.sales_invoice
    invoice = frappe.get_doc('Sales Invoice', invoice_name)
    assert invoice.docstatus == 1 and invoice.grand_total == 10
    assert invoice.is_pos == 0 and invoice.update_stock == 1 and not invoice.payments
    record_sale(link, settings)
    assert link.sales_invoice == invoice_name
    assert frappe.db.get_value('Bin', {'item_code': code, 'warehouse': warehouse}, 'actual_qty') == 8
    assert invoice.total_taxes_and_charges > 0
    assert frappe.db.count('Stock Ledger Entry', {'voucher_no': invoice_name, 'is_cancelled': 0}) == 1
    print('PASS: amendment, inclusive VAT, submitted invoice, stock deducted once, no POS payment, repeat handover idempotency')
finally:
    frappe.db.rollback()
    legacy_scripts.stop()
    frappe.destroy()
