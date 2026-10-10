"""Isolated ERP accounting tests. Stripe and email delivery are intercepted."""
import json
import secrets
import time
import unittest
from unittest.mock import patch
import frappe
from checkout_integration import CheckoutIntegrationTests, fixtures, COMPANY
from webshop.callus_storefront import checkout as api, hospice
from webshop.callus_storefront.checkout_validation import checkout_id


class HospiceIntegrationTests(unittest.TestCase):
    stripe = CheckoutIntegrationTests.stripe
    mark_paid = CheckoutIntegrationTests.mark_paid

    @classmethod
    def setUpClass(cls):
        hospice.setup()
        fixtures()
        if not frappe.db.exists('Customer', {'customer_name':hospice.CUSTOMER_NAME}):
            frappe.get_doc(dict(doctype='Customer',customer_name=hospice.CUSTOMER_NAME,
                customer_type='Company',customer_group='Checkout Retail',territory='All Territories')).insert()
        if not frappe.db.exists('Notification', hospice.BUSINESS):
            frappe.get_doc(dict(doctype='Notification',name=hospice.BUSINESS,subject='Team',document_type='Sales Invoice',
                event='Submit',channel='Email',enabled=0,message='Team',recipients=[dict(cc='team@example.com')])).insert()
        frappe.db.commit()

    def setUp(self):
        CheckoutIntegrationTests.setUp(self)
        self.buyer.update(delivery='delivery',company='Buyer Company',company_vat='MT12345678',instructions='Ring the bell')
        company=frappe.get_doc('Company',COMPANY)
        rule=frappe.get_doc(dict(doctype='Shipping Rule',label='Hospice Test '+self.token[:8],shipping_rule_type='Selling',company=COMPANY,
            calculate_based_on='Net Total',account=company.default_income_account,cost_center=company.cost_center,
            conditions=[dict(from_value=0.01,to_value=35,shipping_amount=5)],countries=[dict(country='Malta')])).insert()
        settings=api._settings()
        settings.update(dict(hospice_enabled=1,hospice_customer=frappe.db.get_value('Customer',{'customer_name':hospice.CUSTOMER_NAME},'name'),
            hospice_warehouse=frappe.db.get_value('Website Item',{'item_code':'CHECKOUT-BASIL'},'website_warehouse'),
            hospice_test_email='tester@example.com',delivery_rule=rule.name))
        settings.set('hospice_items',[dict(item_code='CHECKOUT-BASIL')]);settings.save();frappe.db.commit()
        self.mail=patch('frappe.sendmail');self.sent=self.mail.start()

    def tearDown(self):
        self.mail.stop()
        frappe.set_user('Administrator')
        frappe.db.rollback()
        settings=api._settings();settings.delivery_rule=None;settings.hospice_enabled=0;settings.save();frappe.db.commit()
        CheckoutIntegrationTests.tearDown(self)

    def prepare(self):
        return hospice.prepare(self.token,[dict(id='CHECKOUT-BASIL',qty=2,rate=.01)],self.buyer)

    def pay(self):
        result=self.prepare();api.pay(self.token);return result

    def test_shared_customer_isolated_addresses_and_server_prices(self):
        frappe.set_user('Guest')
        a=self.prepare();doc=api._doc(self.token)
        order=frappe.get_doc('Sales Order',a['order']);self.assertEqual(a['summary']['total'],12)
        self.assertEqual(order.customer,api._settings().hospice_customer)
        self.assertEqual(order.contact_email,self.buyer['email'])
        self.assertEqual('Buyer Company',order.custom_hospice_buyer_company)
        self.token=secrets.token_hex(32);self.buyer.update(email='second@example.com',address='2 Other Street')
        b=self.prepare();other=frappe.get_doc('Sales Order',b['order'])
        self.assertEqual(order.customer,other.customer);self.assertNotEqual(order.shipping_address_name,other.shipping_address_name)
        self.assertEqual(frappe.db.get_value('Address',order.shipping_address_name,'address_line1'),'1 Garden Street')
        self.assertFalse(frappe.has_permission('Address','read'));self.assertFalse(frappe.has_permission('Sales Order','read'))
        self.assertEqual(frappe.session.user,'Guest')

    def test_forbidden_product_and_collection_rejected(self):
        with self.assertRaises(frappe.ValidationError):hospice.prepare(self.token,[dict(id='CHECKOUT-EMPTY',qty=1)],self.buyer)
        self.buyer['delivery']='collection'
        with self.assertRaises(frappe.ValidationError):self.prepare()

    def test_removed_product_rejected_before_stripe(self):
        self.prepare();settings=api._settings();settings.set('hospice_items',[dict(item_code='CHECKOUT-EMPTY')]);settings.save()
        with self.assertRaises(frappe.ValidationError):api.pay(self.token)
        self.assertFalse(self.calls)

    def test_campaign_cannot_be_changed_by_reusing_checkout_token(self):
        self.prepare()
        with self.assertRaises(frappe.ValidationError):api.prepare(self.token,[dict(id='CHECKOUT-BASIL',qty=2)],self.buyer)

    def test_paid_order_emails_once_to_test_recipient(self):
        self.pay();self.mark_paid();api.status(self.token);api.status(self.token)
        doc=api._doc(self.token)
        self.assertEqual(doc.status,'Paid');self.assertTrue(doc.payment_entry)
        self.sent.reset_mock();hospice.queue_emails(doc.name);hospice.queue_emails(doc.name)
        self.assertEqual(self.sent.call_count,2)
        for call in self.sent.call_args_list:
            self.assertEqual(call.kwargs['recipients'],['tester@example.com'])
            self.assertIn('3–5 working days',call.kwargs['message'])
        buyer_mail=self.sent.call_args_list[0].kwargs['message']
        self.assertIn('/hospice-track#',buyer_mail)
        doc.reload();self.assertTrue(doc.campaign_notified);self.assertTrue(doc.tracking_hash)
        self.assertNotIn('/hospice-track#',self.sent.call_args_list[1].kwargs['message'])
        self.assertEqual(frappe.db.count('Payment Entry',{'reference_no':doc.payment_intent,'docstatus':1}),1)

    def test_unpaid_never_sends_confirmation(self):
        self.pay();self.sent.reset_mock();hospice.queue_emails(api._doc(self.token).name);self.sent.assert_not_called()

    def test_tracking_token_cannot_select_other_order_and_is_revocable(self):
        self.pay();self.mark_paid();api.status(self.token)
        doc=api._doc(self.token);tracking=secrets.token_hex(32)
        doc.tracking_hash=checkout_id(tracking);doc.tracking_expires_at=int(time.time())+60;doc.save(ignore_permissions=True)
        frappe.set_user('Guest')
        with patch('bloominggarden.bloominggarden.customer_ordering.progress.order_progress',return_value={'delivery_state':'Awaiting planning'}) as progress:
            result=hospice.track(tracking);self.assertEqual(result['order'],doc.sales_order)
            self.assertEqual(progress.call_args.args[0].name,doc.sales_order)
            for key in ('buyer','email','address','customer','sales_invoice'):
                self.assertNotIn(key,result)
            for bad in (self.token,doc.sales_order,secrets.token_hex(32)):
                with self.assertRaises(frappe.PermissionError):hospice.track(bad)
            with self.assertRaises(TypeError):hospice.track(tracking,order='OTHER')
            frappe.db.set_value('Callus Checkout',doc.name,'tracking_revoked',1)
            with self.assertRaises(frappe.PermissionError):hospice.track(tracking)

    def test_tracking_expiry_and_unpaid_denied(self):
        self.prepare();doc=api._doc(self.token);tracking=secrets.token_hex(32)
        doc.tracking_hash=checkout_id(tracking);doc.tracking_expires_at=int(time.time())+60;doc.save(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):hospice.track(tracking)
        self.pay();self.mark_paid();api.status(self.token)
        frappe.db.set_value('Callus Checkout',doc.name,'tracking_expires_at',1)
        with self.assertRaises(frappe.PermissionError):hospice.track(tracking)

    def test_catalogue_contains_only_allowed_products(self):
        frappe.set_user('Guest');data=hospice.catalogue()
        self.assertEqual([i['id'] for i in data['items']],['CHECKOUT-BASIL'])
        self.assertEqual(data['items'][0]['price'],3.5)
        self.assertNotIn('customer',data)

    def test_setup_is_manager_only_and_keeps_existing_campaign_selection(self):
        settings=api._settings()
        source=frappe._dict(customer=settings.hospice_customer,company=COMPANY,
            allowed_items=[frappe._dict(item_code='CHECKOUT-EMPTY')],default_warehouse=settings.hospice_warehouse)
        original=frappe.get_single
        with patch('frappe.get_single',side_effect=lambda dt: source if dt=='Blooming Garden Customer Ordering Settings' else original(dt)):
            result=hospice.configure(enable=1,test_email='tester@example.com')
            self.assertTrue(result['enabled'])
            self.assertEqual(api._settings().hospice_items[0].item_code,'CHECKOUT-BASIL')
            frappe.set_user('Guest')
            frappe.flags.in_test=False  # Frappe only_for deliberately bypasses roles in test mode.
            try:
                with self.assertRaises(frappe.PermissionError):hospice.configure(enable=1)
            finally:
                frappe.flags.in_test=True
