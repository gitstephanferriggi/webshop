"""Exercise payment/refund routines against the older ERPNext payment API."""
import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'webshop/callus_storefront/checkout.py'

class PaymentCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.order = Mock(name='order', docstatus=1, rounded_total=25.47)
        self.order.name = 'SO-TEST'
        self.invoice = Mock(docstatus=1, rounded_total=25.47, outstanding_amount=0)
        self.invoice.name = 'INV-TEST'
        self.credit = Mock(rounded_total=-25.47)
        self.credit.name = 'CREDIT-TEST'
        self.entry = Mock(paid_from_account_currency='EUR', paid_to_account_currency='EUR')
        self.entry.name = 'PAY-TEST'
        self.calls = []
        # Deliberately excludes ignore_permissions, matching production's API.
        def get_payment_entry(dt, dn, bank_account=None, bank_amount=None):
            self.calls.append((dt, dn, bank_account, bank_amount))
            return self.entry
        modules = {
            'erpnext.accounts.doctype.payment_entry.payment_entry': types.SimpleNamespace(get_payment_entry=get_payment_entry),
            'erpnext.selling.doctype.sales_order.sales_order': types.SimpleNamespace(make_sales_invoice=lambda *a, **k: self.invoice),
            'erpnext.accounts.doctype.sales_invoice.sales_invoice': types.SimpleNamespace(make_sales_return=lambda *a: self.credit),
        }
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        tree = ast.parse(SOURCE.read_text())
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('_record_payment', '_record_refund')]
        for function in functions:
            function.decorator_list = []
        self.scope = dict(frappe=types.SimpleNamespace(get_doc=lambda *a: self.order),
                          cents=lambda amount: round(amount * 100), nowdate=lambda: '2026-09-30',
                          fail=lambda message: self.fail(message),
                          _can_refund=lambda doc: (self.order, self.invoice))
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), self.scope)
        self.doc = types.SimpleNamespace(name='CHECKOUT', payment_entry=None, sales_order='SO-TEST',
            amount_minor=2547, payment_intent=None, payment_account='Stripe Clearing', refund_entry=None)

    def test_paid_order_uses_compatible_api_and_records_once(self):
        self.scope['_record_payment'](self.doc, {'payment_intent': 'pi_fixture'})
        self.scope['_record_payment'](self.doc, {'payment_intent': 'pi_fixture'})
        self.assertEqual(self.calls, [('Sales Invoice', 'INV-TEST', 'Stripe Clearing', 25.47)])
        self.assertEqual(self.doc.status, 'Paid')
        self.assertEqual(self.doc.sales_invoice, 'INV-TEST')
        self.invoice.submit.assert_called_once()
        self.entry.submit.assert_called_once()

    def test_refund_uses_compatible_api_and_records_once(self):
        self.scope['_record_refund'](self.doc, 're_fixture')
        self.scope['_record_refund'](self.doc, 're_fixture')
        self.assertEqual(self.calls, [('Sales Invoice', 'CREDIT-TEST', 'Stripe Clearing', 25.47)])
        self.assertEqual(self.doc.status, 'Refunded')
        self.credit.submit.assert_called_once()
        self.entry.submit.assert_called_once()
        self.order.update_status.assert_called_once_with('Closed')

if __name__ == '__main__':
    unittest.main()
