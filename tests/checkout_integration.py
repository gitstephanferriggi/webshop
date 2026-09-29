"""Run only in an isolated Frappe site with ERPNext, Payments and Webshop installed.

Real ERPNext documents/GL entries; only Stripe's network boundary is simulated.
No production credentials or calls. Runner asserts a dedicated test DB port.
"""
import json
import secrets
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import nowdate, getdate
from frappe.utils.password import set_encrypted_password
from webshop.callus_storefront import checkout as api
from webshop.callus_storefront.checkout_validation import checkout_id

COMPANY='Callus Checkout Test'


def fixtures():
    if not frappe.db.exists("Warehouse Type", "Transit"):
        from erpnext.setup.setup_wizard.operations.install_fixtures import install
        install("Malta")
        frappe.db.commit()
    if not frappe.db.exists('Fiscal Year',str(getdate().year)):
        year=getdate().year
        frappe.get_doc(dict(doctype='Fiscal Year',year=str(year),year_start_date=f'{year}-01-01',year_end_date=f'{year}-12-31')).insert()
    if not frappe.db.exists('Company',COMPANY):
        frappe.get_doc(dict(doctype='Company',company_name=COMPANY,abbr='CCT',default_currency='EUR',country='Malta',chart_of_accounts='Standard',enable_perpetual_inventory=1)).insert()
    company=frappe.get_doc('Company',COMPANY)
    warehouse=frappe.db.get_value('Warehouse',{'company':COMPANY,'is_group':0},'name')
    if not frappe.db.exists('Customer Group','Checkout Retail'):
        frappe.get_doc(dict(doctype='Customer Group',customer_group_name='Checkout Retail',parent_customer_group='All Customer Groups',is_group=0)).insert()
    if not frappe.db.exists('Price List','Checkout Retail'):
        frappe.get_doc(dict(doctype='Price List',price_list_name='Checkout Retail',currency='EUR',selling=1,enabled=1)).insert()
    bank=frappe.db.get_value('Account',{'company':COMPANY,'account_type':'Bank','is_group':0},'name')
    if not bank:
        parent=frappe.db.get_value('Account',{'company':COMPANY,'account_name':'Bank Accounts'},'name')
        bank=frappe.get_doc(dict(doctype='Account',account_name='Stripe Clearing',company=COMPANY,parent_account=parent,account_type='Bank',account_currency='EUR')).insert().name
    if not frappe.db.exists('Stripe Settings','Checkout Test'):
        # Fixture only: no validate() call, which would contact Stripe.
        doc=frappe.get_doc(dict(doctype='Stripe Settings',name='Checkout Test',gateway_name='Checkout Test',publishable_key='pk_test_local_only'))
        doc.db_insert()
        set_encrypted_password('Stripe Settings','Checkout Test','sk_test_local_only','secret_key')
    if not frappe.db.exists('Payment Gateway','Checkout Stripe'):
        frappe.get_doc(dict(doctype='Payment Gateway',gateway='Checkout Stripe',gateway_settings='Stripe Settings',gateway_controller='Checkout Test')).insert()
    gateway=frappe.db.get_value('Payment Gateway Account',{'payment_gateway':'Checkout Stripe'},'name')
    if not gateway:
        gateway=frappe.get_doc(dict(doctype='Payment Gateway Account',payment_gateway='Checkout Stripe',company=COMPANY,payment_account=bank,currency='EUR')).insert().name
    settings=frappe.get_single('Webshop Settings')
    settings.update(dict(enabled=1,show_price=1,enable_checkout=0,company=COMPANY,price_list='Checkout Retail',default_customer_group='Checkout Retail',quotation_series='QTN-CART-',payment_gateway_account=gateway))
    settings.save()
    new=frappe.get_single('Callus Checkout Settings');new.update(dict(enabled=1,site_url='http://checkout.localhost',stripe_settings='Checkout Test',maximum_order_total=1000,allow_live_payments=0,webhook_endpoint='we_local_fixture',webhook_secret='whsec_local_fixture'));new.save()
    frappe.conf.host_name='http://checkout.localhost'
    for code in ['CHECKOUT-BASIL','CHECKOUT-EMPTY']:
        if not frappe.db.exists('Item',code):
            item=frappe.get_doc(dict(doctype='Item',item_code=code,item_name=code,item_group='All Item Groups',stock_uom='Nos',is_stock_item=1,is_sales_item=1,valuation_rate=1,
                item_defaults=[dict(company=COMPANY,default_warehouse=warehouse,income_account=company.default_income_account,expense_account=company.default_expense_account)]));item.insert()
            frappe.get_doc(dict(doctype='Item Price',item_code=code,price_list='Checkout Retail',price_list_rate=3.50,currency='EUR',uom='Nos')).insert()
            web=frappe.get_doc(dict(doctype='Website Item',item_code=code,web_item_name=code,published=1,website_warehouse=warehouse,route=code.lower()));web.insert()
    # One large fixture receipt so tests remain independent of earlier failed runs.
    from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
    make_stock_entry(item_code='CHECKOUT-BASIL',qty=100,target=warehouse,rate=1,company=COMPANY)
    frappe.db.commit()


class CheckoutIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures()
    def setUp(self):
        self.token=secrets.token_hex(32)
        self.buyer=dict(first_name='Guest',last_name='Test',email='buyer@example.com',phone='+35699990000',address='1 Garden Street',town='Siggiewi',postcode='SGW 2600',country='Malta',delivery='collection')
        self.sessions={};self.refunds={};self.calls=[]
        self.mock=patch.object(api,'_stripe',side_effect=self.stripe);self.stripe_mock=self.mock.start()
        self.network_guard=patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected external HTTP call'));self.network_guard.start()
        frappe.set_user('Administrator')
    def tearDown(self):
        frappe.db.rollback();self.mock.stop();self.network_guard.stop();frappe.set_user('Administrator')
    def stripe(self,doc,method,path,data=None,idempotency=None):
        self.calls.append((method,path,idempotency))
        if method=='POST' and path=='checkout/sessions':
            session=dict(id='cs_test_'+doc.name[:20],mode='payment',currency='eur',amount_total=doc.amount_minor,client_reference_id=doc.name,livemode=False,metadata={'callus_checkout':doc.name},status='open',payment_status='unpaid',url='https://checkout.stripe.com/c/pay/'+doc.name)
            self.sessions[session['id']]=session;return session
        if path.startswith('checkout/sessions/'):
            session=self.sessions[path.split('/')[2]]
            if path.endswith('/expire'):session['status']='expired'
            return session
        if method=='POST' and path=='refunds':
            refund=dict(id='re_'+doc.name[:20],status='succeeded',amount=doc.amount_minor,payment_intent=doc.payment_intent)
            self.refunds[refund['id']]=refund
            self.sessions[doc.stripe_session]['payment_intent']['latest_charge']['refunded']=True
            return refund
        if path=='refunds':return {'data':list(self.refunds.values())}
        if path.startswith('refunds/'):return self.refunds[path.split('/')[1]]
        raise AssertionError((method,path))
    def prepare(self,qty=2):
        return api.prepare(self.token,[dict(id='CHECKOUT-BASIL',qty=qty,rate=0.01)],self.buyer)
    def pay(self):
        result=self.prepare();api.pay(self.token);return result
    def mark_paid(self):
        doc=api._doc(self.token);session=self.sessions[doc.stripe_session]
        session.update(status='complete',payment_status='paid',payment_intent={'id':'pi_'+doc.name[:20],'latest_charge':{'id':'ch_test','refunded':False}})
    def test_guest_quote_uses_erp_prices_and_idempotency(self):
        frappe.set_user('Guest')
        result=self.prepare();again=self.prepare()
        self.assertEqual(result['order'],again['order']);self.assertEqual(result['summary']['total'],7)
        order=frappe.get_doc('Sales Order',result['order']);self.assertEqual(order.docstatus,0)
        self.assertFalse(frappe.has_permission('Callus Checkout','read'))
    def test_duplicate_callbacks_make_one_payment_and_full_refund_reverses_ledger(self):
        result=self.pay();self.mark_paid()
        paid=api.status(self.token);api.status(self.token)
        self.assertEqual(paid['status'],'Paid')
        doc=api._doc(self.token)
        self.assertEqual(frappe.db.count('Payment Entry',{'reference_no':doc.payment_intent,'docstatus':1}),1)
        self.assertEqual(frappe.db.get_value('Sales Invoice',doc.sales_invoice,'outstanding_amount'),0)
        refunded=api.refund(doc.name);api.refund(doc.name)
        self.assertEqual(refunded['status'],'Refunded')
        doc.reload();self.assertTrue(doc.refund_entry)
        self.assertEqual(frappe.db.get_value('Payment Entry',doc.refund_entry,'docstatus'),1)
        self.assertEqual(frappe.db.get_value('Sales Invoice',doc.credit_note,'outstanding_amount'),0)
        self.assertEqual(frappe.db.get_value('Sales Order',result['order'],'status'),'Closed')
        self.assertEqual(frappe.db.get_value('Sales Invoice',doc.credit_note,'is_return'),1)
        balances=frappe.db.sql('SELECT sum(debit-credit) FROM `tabGL Entry` WHERE voucher_no in (%s,%s) AND party=%s',(doc.payment_entry,doc.refund_entry,doc.customer))[0][0]
        self.assertEqual(balances,0)
    def test_cancel_releases_order_reservation(self):
        result=self.pay();self.assertEqual(api.cancel(self.token)['status'],'Expired')
        self.assertEqual(frappe.db.get_value('Sales Order',result['order'],'docstatus'),2)
    def test_unpaid_session_never_creates_payment(self):
        self.pay();self.assertEqual(api.status(self.token)['status'],'Pending');self.assertFalse(api._doc(self.token).payment_entry)
    def test_mismatched_stripe_amount_rejected(self):
        self.pay();self.mark_paid();doc=api._doc(self.token);self.sessions[doc.stripe_session]['amount_total']=1
        with self.assertRaises(frappe.ValidationError):api.status(self.token)
        self.assertFalse(api._doc(self.token).payment_entry)
    def test_stock_revalidated_after_quote(self):
        self.prepare();doc=api._doc(self.token);order=frappe.get_doc('Sales Order',doc.sales_order);warehouse=order.items[0].warehouse
        frappe.db.set_value('Bin',{'item_code':'CHECKOUT-BASIL','warehouse':warehouse},'actual_qty',0)
        with self.assertRaises(frappe.ValidationError):api.pay(self.token)
    def test_guest_cannot_refund_or_read_other_checkout(self):
        self.pay();self.mark_paid();api.status(self.token)
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):api.refund(checkout_id(self.token))
        with self.assertRaises(frappe.ValidationError):api.status(secrets.token_hex(32))
    def test_modified_payload_cannot_reuse_token(self):
        self.prepare()
        with self.assertRaises(frappe.ValidationError):self.prepare(qty=3)
    def test_entire_flow_as_guest_restores_identity(self):
        frappe.set_user('Guest')
        frappe.local.session.sid='guest-original-session'
        frappe.local.session.data.csrf_token='original-csrf-token'
        frappe.local.form_dict['cmd']='original-request'
        self.pay();self.mark_paid()
        self.assertEqual(api.status(self.token)['status'],'Paid')
        self.assertEqual(frappe.session.user,'Guest')
        self.assertEqual(frappe.session.sid,'guest-original-session')
        self.assertEqual(frappe.session.data.csrf_token,'original-csrf-token')
        self.assertEqual(frappe.form_dict.cmd,'original-request')
    def test_timeout_after_stripe_creation_reuses_order_and_idempotency(self):
        self.prepare();original=self.stripe;attempts=[]
        def timeout_once(*args,**kwargs):
            result=original(*args,**kwargs)
            if args[1:3]==('POST','checkout/sessions'):
                attempts.append(args[-1])
                if len(attempts)==1:raise TimeoutError('simulated lost response')
            return result
        self.stripe_mock.side_effect=timeout_once
        with self.assertRaises(TimeoutError):api.pay(self.token)
        order=api._doc(self.token).sales_order
        api.pay(self.token)
        self.assertEqual(api._doc(self.token).sales_order,order)
        self.assertEqual(attempts,['session-v1','session-v1'])
    def test_delivery_requires_configured_rule(self):
        self.buyer['delivery']='delivery'
        with self.assertRaises(frappe.ValidationError):self.prepare()
    def test_vat_inclusive_price_and_refund_preserve_tax(self):
        company=frappe.get_doc('Company',COMPANY)
        account=frappe.db.get_value('Account',{'company':COMPANY,'account_type':'Tax','is_group':0},'name')
        if not account:
            parent=frappe.db.get_value('Account',{'company':COMPANY,'account_name':'Duties and Taxes'},'name')
            account=frappe.get_doc(dict(doctype='Account',account_name='Checkout VAT',company=COMPANY,parent_account=parent,account_type='Tax',account_currency='EUR')).insert().name
        template=frappe.get_doc(dict(doctype='Sales Taxes and Charges Template',title='Checkout VAT '+self.token[:8],company=COMPANY,
            taxes=[dict(charge_type='On Net Total',account_head=account,description='VAT 18%',rate=18,included_in_print_rate=1,cost_center=company.cost_center)])).insert()
        with patch('erpnext.accounts.party.set_taxes',return_value=template.name):
            result=self.pay()
        self.assertEqual(result['summary']['total'],7)
        self.assertGreater(result['summary']['taxes_and_charges'],1)
        self.mark_paid();api.status(self.token);doc=api._doc(self.token)
        api.refund(doc.name);doc.reload()
        invoice=frappe.get_doc('Sales Invoice',doc.sales_invoice);credit=frappe.get_doc('Sales Invoice',doc.credit_note)
        self.assertAlmostEqual(invoice.total_taxes_and_charges,-credit.total_taxes_and_charges,places=2)
    def test_delivery_charge_is_calculated_by_erp(self):
        company=frappe.get_doc('Company',COMPANY)
        rule=frappe.get_doc(dict(doctype='Shipping Rule',label='Checkout Delivery '+self.token[:8],shipping_rule_type='Selling',company=COMPANY,
            calculate_based_on='Fixed',shipping_amount=5,account=company.default_income_account,cost_center=company.cost_center)).insert()
        settings=frappe.get_single('Callus Checkout Settings');settings.delivery_rule=rule.name;settings.save()
        self.buyer['delivery']='delivery'
        try:
            result=self.prepare()
            self.assertEqual(result['summary']['total'],12)
            self.assertEqual(result['summary']['delivery_fee'],5)
            self.pay();self.mark_paid();api.status(self.token)
            invoice=frappe.get_doc('Sales Invoice',api._doc(self.token).sales_invoice)
            from webshop.callus_storefront.notifications import email_template
            from pathlib import Path
            preview=Path(__file__).resolve().parents[2]/'outputs/storefront-build/sale-email-previews';preview.mkdir(exist_ok=True)
            for audience in ('customer','business'):
                html=frappe.render_template(email_template(audience),{'doc':invoice})
                self.assertIn('Delivery address',html)
                self.assertIn('1 Garden Street',html)
                self.assertNotIn('ready to collect',html)
                self.assertIn(frappe.utils.fmt_money(5,currency='EUR'),html)
                (preview/(audience+'-delivery.html')).write_text('<!doctype html><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+html)
        finally:
            settings.delivery_rule=None;settings.save();frappe.db.commit()
    def test_delivery_configuration_requires_manager_and_preserves_payments(self):
        from webshop.callus_storefront.notifications import configure_delivery
        settings=frappe.get_single('Callus Checkout Settings')
        original={key:settings.get(key) for key in ('enabled','site_url','stripe_settings','allow_live_payments','webhook_endpoint')}
        frappe.set_user('Guest')
        # Frappe bypasses only_for in test mode; exercise the real permission path.
        frappe.flags.in_test=False
        try:
            with self.assertRaises(frappe.PermissionError):configure_delivery('untrusted')
        finally:
            frappe.flags.in_test=True;frappe.set_user('Administrator')
        company=frappe.get_doc('Company',COMPANY)
        rule=frappe.get_doc(dict(doctype='Shipping Rule',label='Manager Delivery '+self.token[:8],shipping_rule_type='Selling',company=COMPANY,
            calculate_based_on='Fixed',shipping_amount=5,account=company.default_income_account,cost_center=company.cost_center,countries=[dict(country='Malta')])).insert()
        try:
            self.assertEqual(configure_delivery(rule.name)['delivery_rule'],rule.name)
            settings.reload()
            self.assertEqual(original,{key:settings.get(key) for key in original})
            rule.disabled=1;rule.save()
            with self.assertRaises(frappe.ValidationError):configure_delivery(rule.name)
        finally:
            settings.delivery_rule=None;settings.save();frappe.db.commit()

    def test_existing_malta_delivery_threshold_and_collection(self):
        company=frappe.get_doc('Company',COMPANY)
        rule=frappe.get_doc(dict(doctype='Shipping Rule',label='Malta Boundary '+self.token[:8],shipping_rule_type='Selling',company=COMPANY,
            calculate_based_on='Net Total',account=company.default_income_account,cost_center=company.cost_center,
            conditions=[dict(from_value=0.01,to_value=35,shipping_amount=5)],countries=[dict(country='Malta')])).insert()
        settings=frappe.get_single('Callus Checkout Settings');settings.delivery_rule=rule.name;settings.save()
        price=frappe.db.get_value('Item Price',{'item_code':'CHECKOUT-BASIL','price_list':'Checkout Retail'},'name')
        try:
            for value,expected in [(34.99,5),(35,5),(35.01,0)]:
                with self.subTest(net_total=value):
                    frappe.db.set_value('Item Price',price,'price_list_rate',value)
                    self.token=secrets.token_hex(32);self.buyer['delivery']='delivery'
                    result=api.prepare(self.token,[dict(id='CHECKOUT-BASIL',qty=1)],self.buyer)
                    self.assertEqual(result['summary']['delivery_fee'],expected)
                    self.assertAlmostEqual(result['summary']['total'],value+expected,places=2)
            account=frappe.db.get_value('Account',{'company':COMPANY,'account_type':'Tax','is_group':0},'name')
            template=frappe.get_doc(dict(doctype='Sales Taxes and Charges Template',title='Delivery VAT '+self.token[:8],company=COMPANY,
                taxes=[dict(charge_type='On Net Total',account_head=account,description='VAT 18%',rate=18,included_in_print_rate=1,cost_center=company.cost_center)])).insert()
            for value,expected in [(41.30,5),(41.31,0)]:
                frappe.db.set_value('Item Price',price,'price_list_rate',value)
                self.token=secrets.token_hex(32)
                with patch('erpnext.accounts.party.set_taxes',return_value=template.name):
                    result=api.prepare(self.token,[dict(id='CHECKOUT-BASIL',qty=1)],self.buyer)
                self.assertEqual(result['summary']['delivery_fee'],expected)
            self.token=secrets.token_hex(32);self.buyer['delivery']='collection'
            result=api.prepare(self.token,[dict(id='CHECKOUT-BASIL',qty=1)],self.buyer)
            self.assertEqual(result['summary']['delivery_fee'],0)
        finally:
            frappe.db.set_value('Item Price',price,'price_list_rate',3.5)
            settings.delivery_rule=None;settings.save();frappe.db.commit()

    def test_sale_notifications_once_not_on_refund(self):
        from webshop.callus_storefront.notifications import email_template,CONDITION
        notices=[]
        for audience in ('customer','business'):
            notice=frappe.get_doc(dict(doctype='Notification',name='Callus test '+audience+self.token[:8],enabled=1,channel='Email',
                document_type='Sales Invoice',event='Submit',condition=CONDITION.replace('Website','Checkout Retail'),
                subject='Callus '+audience+' {{ doc.name }}',message=email_template(audience),attach_print=0,
                recipients=[{'receiver_by_document_field':'contact_email'}] if audience=='customer' else [{'cc':'team@example.com'}])).insert()
            notices.append(notice)
        mails=[]
        try:
            with patch('frappe.sendmail',side_effect=lambda **kw:mails.append(kw)):
                self.pay();self.mark_paid();api.status(self.token);api.status(self.token)
                sale_mails=[m for m in mails if m.get('subject','').startswith('Callus ')]
                self.assertEqual(len(sale_mails),2)
                customer=next(m for m in sale_mails if 'customer' in m['subject'])
                self.assertEqual(customer['recipients'],['buyer@example.com'])
                self.assertNotIn('Administrator',customer['recipients'])
                self.assertIn('Logo-Transparent.png',customer['message'])
                self.assertIn('ready to collect',customer['message'])
                self.assertNotIn('2-3 Working Days',customer['message'])
                doc=api._doc(self.token);api.refund(doc.name)
                self.assertEqual(len([m for m in mails if m.get('subject','').startswith('Callus ')]),2)
                # Keep reviewable previews from real local ERP invoice data.
                from pathlib import Path
                preview=Path(__file__).resolve().parents[2]/'outputs/storefront-build/sale-email-previews';preview.mkdir(exist_ok=True)
                for m in sale_mails:
                    audience='customer' if 'customer' in m['subject'] else 'business'
                    (preview/(audience+'.html')).write_text('<!doctype html><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+m['message'])
        finally:
            for notice in notices:notice.enabled=0;notice.save()
            frappe.db.commit()

    def test_webhook_signature_rejects_tampering_and_accepts_verified_event(self):
        import hmac,hashlib,time
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request
        self.pay();self.mark_paid();doc=api._doc(self.token)
        payload=json.dumps({'id':'evt_checkout_test','object':'event','type':'checkout.session.completed','data':{'object':{'metadata':{'callus_checkout':doc.name}}}})
        stamp=int(time.time());secret='whsec_local_fixture'
        signature=hmac.new(secret.encode(),f'{stamp}.{payload}'.encode(),hashlib.sha256).hexdigest()
        original_request=getattr(frappe.local,"request",None)
        # Execute the endpoint body; separate HTTP testing covers the transport wrappers.
        handler=api.webhook.__wrapped__.__wrapped__
        settings=frappe._dict(get_password=lambda *a,**k:secret)
        try:
            with patch.object(api,'_settings',return_value=settings):
                for sig,expected in [('incorrect',False),(signature,True)]:
                    frappe.local.request=Request(EnvironBuilder(method='POST',data=payload,headers={'Stripe-Signature':f't={stamp},v1={sig}'}).get_environ())
                    result=handler();self.assertEqual(result['received'],expected)
        finally:frappe.local.request=original_request
        self.assertEqual(api._doc(self.token).status,'Paid')
    def test_configuration_registers_separate_webhook_without_exposing_secret(self):
        settings=frappe.get_single('Callus Checkout Settings')
        settings.webhook_endpoint=None;settings.webhook_secret=None;settings.save()
        def configured(doc,method,path,data=None,idempotency=None):
            if path=='account':return {'id':'acct_local_fixture','charges_enabled':True}
            if method=='POST' and path=='webhook_endpoints':
                self.assertEqual(data['url'],'http://checkout.localhost/api/method/webshop.callus_storefront.checkout.webhook')
                return {'id':'we_new_fixture','secret':'whsec_new_fixture'}
            raise AssertionError((method,path))
        with patch.object(api,'_stripe',side_effect=configured):
            result=api.configure_stripe('http://checkout.localhost',0)
        self.assertTrue(result['enabled']);self.assertFalse(result['is_live'])
        self.assertNotIn('secret',json.dumps(result));self.assertNotIn('whsec',json.dumps(result))
        saved=frappe.get_single('Callus Checkout Settings')
        self.assertEqual(saved.get_password('webhook_secret'),'whsec_new_fixture')
        saved.webhook_endpoint='we_local_fixture';saved.webhook_secret='whsec_local_fixture';saved.save();frappe.db.commit()
