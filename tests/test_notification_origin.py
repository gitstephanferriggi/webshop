"""Invoice-origin classification, including POS-Awesome consolidated invoices."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import frappe
from webshop.callus_storefront.notifications import mark_website_invoice
class Row(frappe._dict):
    # Document.items is a child table; dict.items is otherwise a method.
    @property
    def items(self):return self['items']
def invoice(**kwargs):
    values=dict(flags=frappe._dict(),is_return=0,is_pos=0,is_consolidated=0,pos_profile=None,customer='Buyer',customer_group='Website',company='Shop',items=[Row(sales_order='WEB-ORDER',pos_invoice=None)])
    values.update(kwargs);return Row(values)
class OriginTests(unittest.TestCase):
    def setUp(self):
        self.order=Row(docstatus=1,order_type='Shopping Cart',customer='Buyer',company='Shop',items=[Row(prevdoc_docname='WEB-QUOTE')])
        self.checkout=Row(sales_order='WEB-ORDER',stripe_session='cs_fixture',customer='Buyer',company='Shop',status='Pending')
    def classify(self,doc,quotation_type='Shopping Cart'):
        with patch('frappe.get_doc',side_effect=lambda dt,name:self.checkout if dt=='Callus Checkout' else self.order),patch('frappe.db',new=SimpleNamespace(get_value=lambda dt, name, field: self.order.company if dt == "Sales Order" else quotation_type)):
            mark_website_invoice(doc)
        return bool(doc.flags.callus_website_order)
    def test_customer_group_does_not_identify_order_origin(self):
        self.assertFalse(self.classify(invoice(items=[Row(sales_order=None)])))
    def test_pos_and_consolidated_pos_are_excluded_even_with_website_order_link(self):
        for flag in ('is_pos','is_consolidated','pos_profile'):
            with self.subTest(flag=flag):self.assertFalse(self.classify(invoice(**{flag:1})))
        self.assertFalse(self.classify(invoice(items=[Row(sales_order='WEB-ORDER',pos_invoice='POS-1')])) )
    def test_return_is_excluded(self):self.assertFalse(self.classify(invoice(is_return=1)))
    def test_verified_checkout_does_not_depend_on_customer_group(self):
        self.assertTrue(self.classify(invoice(customer_group='Retail',flags=frappe._dict(callus_verified_checkout='CHECKOUT'))))
    def test_verified_checkout_requires_matching_customer_company_order_and_session(self):
        for key,value in [('customer','Other'),('sales_order','OTHER'),('stripe_session',None),('status','Draft')]:
            original=self.checkout[key];self.checkout[key]=value
            with self.subTest(key=key):self.assertFalse(self.classify(invoice(flags=frappe._dict(callus_verified_checkout='CHECKOUT'))))
            self.checkout[key]=original
    def test_checkout_company_must_match(self):
        self.order.company='Other'
        self.assertFalse(self.classify(invoice(flags=frappe._dict(callus_verified_checkout='CHECKOUT'))))
    def test_legacy_webshop_requires_shopping_cart_quotation(self):
        self.assertTrue(self.classify(invoice()))
        self.assertFalse(self.classify(invoice(),quotation_type='Sales'))
        self.order.order_type='Sales';self.assertFalse(self.classify(invoice()))
    def test_mixed_manual_and_website_invoice_is_excluded(self):
        self.assertFalse(self.classify(invoice(items=[Row(sales_order='WEB-ORDER'),Row(sales_order=None)])))
    def test_hospice_uses_campaign_emails_only(self):
        self.checkout['campaign']='hospice'
        self.assertFalse(self.classify(invoice(flags=frappe._dict(callus_verified_checkout='CHECKOUT'))))
    def test_stale_marker_is_cleared(self):
        doc=invoice(is_pos=1,flags=frappe._dict(callus_website_order=True));self.assertFalse(self.classify(doc))
if __name__=='__main__':unittest.main()
