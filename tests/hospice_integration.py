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
from webshop.callus_storefront import hospice_fulfilment as fulfilment


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
        if not frappe.db.exists('Item', 'CHECKOUT-DELIVERY'):
            frappe.get_doc(dict(doctype='Item', item_code='CHECKOUT-DELIVERY', item_name='Delivery charge',
                item_group='All Item Groups', stock_uom='Nos', is_stock_item=0, is_sales_item=1)).insert()
            frappe.get_doc(dict(doctype='Item Price', item_code='CHECKOUT-DELIVERY',
                price_list='Checkout Retail', price_list_rate=5, currency='EUR', uom='Nos')).insert()
        service = frappe.get_doc('Item', 'CHECKOUT-DELIVERY');service.set('taxes', []);service.save()
        product = frappe.get_doc('Item', 'CHECKOUT-BASIL');product.set('taxes', []);product.save()
        rule=frappe.get_doc(dict(doctype='Shipping Rule',label='Hospice Test '+self.token[:8],shipping_rule_type='Selling',company=COMPANY,
            calculate_based_on='Net Total',account=company.default_income_account,cost_center=company.cost_center,
            conditions=[dict(from_value=0.01,to_value=35,shipping_amount=5)],countries=[dict(country='Malta')])).insert()
        settings=api._settings()
        settings.update(dict(hospice_enabled=1,hospice_customer=frappe.db.get_value('Customer',{'customer_name':hospice.CUSTOMER_NAME},'name'),
            hospice_warehouse=frappe.db.get_value('Website Item',{'item_code':'CHECKOUT-BASIL'},'website_warehouse'),
            hospice_test_email='tester@example.com',delivery_rule=rule.name,
            hospice_delivery_item='CHECKOUT-DELIVERY', hospice_free_delivery_from=35))
        settings.set('hospice_items',[dict(item_code='CHECKOUT-BASIL')]);settings.save();frappe.db.commit()
        self.mail=patch('frappe.sendmail');self.sent=self.mail.start()
        # The isolated checkout bench has no delivery-module tables. Model the
        # absence of a POD while retaining real DN, stock and preparation queries.
        self.no_pod=patch('bloominggarden.bloominggarden.delivery.status.get_latest_valid_execution',return_value=None)
        self.no_pod.start()

    def tearDown(self):
        self.no_pod.stop()
        self.mail.stop()
        frappe.set_user('Administrator')
        frappe.db.rollback()
        for code in ('CHECKOUT-BASIL','CHECKOUT-DELIVERY'):
            item=frappe.get_doc('Item',code);item.set('taxes',[]);item.save()
        frappe.db.set_value('Item Price',{'item_code':'CHECKOUT-BASIL','price_list':'Checkout Retail'},'price_list_rate',3.5)
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

    def test_forbidden_product_rejected(self):
        with self.assertRaises(frappe.ValidationError):hospice.prepare(self.token,[dict(id='CHECKOUT-EMPTY',qty=1)],self.buyer)

    def test_pickup_needs_no_address_and_has_no_delivery_fee(self):
        self.buyer.update(delivery='collection')
        for key in ('address','town','postcode'):self.buyer.pop(key)
        frappe.set_user('Guest')
        result = self.prepare()
        order = frappe.get_doc('Sales Order', result['order'])
        self.assertEqual(result['summary']['total'],7)
        self.assertEqual(result['summary']['delivery_fee'],0)
        self.assertEqual(order.custom_hospice_fulfilment,'Pickup')
        self.assertFalse(order.customer_address)
        self.assertFalse(order.shipping_address_name)
        self.assertEqual(len(order.items),1)
        self.assertTrue(order.contact_person)

    def test_delivery_still_requires_address(self):
        self.buyer.pop('address')
        with self.assertRaises(frappe.ValidationError):self.prepare()

    def test_free_delivery_at_gross_threshold(self):
        result=hospice.prepare(self.token,[dict(id='CHECKOUT-BASIL',qty=10)],self.buyer)
        self.assertEqual(result['summary']['total'],35)
        self.assertEqual(result['summary']['delivery_fee'],0)

    def test_delivery_item_added_once_and_not_exposed_as_a_product(self):
        a=self.prepare();b=self.prepare()
        order=frappe.get_doc('Sales Order',a['order'])
        self.assertEqual(a,b)
        self.assertEqual([r.item_code for r in order.items].count('CHECKOUT-DELIVERY'),1)
        self.assertEqual(len(a['summary']['items']),1)

    def test_vat_is_extracted_from_shelf_and_delivery_prices(self):
        company=frappe.get_doc('Company',COMPANY)
        account=frappe.db.get_value('Account',{'company':COMPANY,'account_type':'Tax','is_group':0},'name')
        if not account:
            parent=frappe.db.get_value('Account',{'company':COMPANY,'account_name':'Duties and Taxes','is_group':1},'name')
            account=frappe.get_doc(dict(doctype='Account',account_name='Hospice Test VAT',parent_account=parent,
                company=COMPANY,account_type='Tax')).insert().name
        item_tax=frappe.get_doc(dict(doctype='Item Tax Template',title='Hospice Item VAT '+self.token[:8],
            company=COMPANY,taxes=[dict(tax_type=account,tax_rate=18)])).insert()
        for code in ['CHECKOUT-BASIL','CHECKOUT-DELIVERY']:
            item=frappe.get_doc('Item',code);item.set('taxes',[dict(item_tax_template=item_tax.name)]);item.save()
        template=frappe.get_doc(dict(doctype='Sales Taxes and Charges Template',title='Hospice VAT '+self.token[:8],
            company=COMPANY,taxes=[dict(charge_type='On Net Total',account_head=account,rate=0,
                description='VAT 18%',included_in_print_rate=0,cost_center=company.cost_center)])).insert()
        with patch('erpnext.accounts.party.set_taxes',return_value=template.name):
            self.pay();self.mark_paid();api.status(self.token)
        doc=api._doc(self.token)
        order=frappe.get_doc('Sales Order',doc.sales_order)
        invoice=frappe.get_doc('Sales Invoice',doc.sales_invoice)
        self.assertEqual(order.grand_total,12)
        self.assertEqual(invoice.grand_total,12)
        self.assertAlmostEqual(order.total_taxes_and_charges,1.83,places=2)
        self.assertAlmostEqual(sum(r.net_amount for r in order.items),10.17,places=2)
        self.assertTrue(all(r.included_in_print_rate for r in order.taxes))
        self.assertTrue(all(r.item_tax_template==item_tax.name for r in order.items))
        self.assertEqual(frappe.get_doc('Sales Taxes and Charges Template',template.name).taxes[0].included_in_print_rate,0)
        self.token=secrets.token_hex(32)
        with patch('erpnext.accounts.party.set_taxes',return_value=template.name):
            at_threshold=hospice.prepare(self.token,[dict(id='CHECKOUT-BASIL',qty=10)],self.buyer)
        self.assertEqual(at_threshold['summary']['total'],35)
        self.assertEqual(at_threshold['summary']['delivery_fee'],0)
        frappe.db.set_value('Item Price',{'item_code':'CHECKOUT-BASIL','price_list':'Checkout Retail'},'price_list_rate',0.5)
        self.token=secrets.token_hex(32)
        with patch('erpnext.accounts.party.set_taxes',return_value=template.name):
            two_saucers=self.prepare()
        self.assertEqual(two_saucers['summary']['total'],6)
        self.assertAlmostEqual(two_saucers['summary']['taxes_and_charges'],0.92,places=2)

    def test_ready_pickup_email_is_paid_only_and_idempotent(self):
        self.buyer['delivery']='collection'
        self.pay();doc=api._doc(self.token)
        with self.assertRaises(frappe.ValidationError):
            fulfilment.set_preparation(doc.sales_order,'Ready for pickup')
        self.mark_paid();api.status(self.token)
        self.sent.reset_mock()
        with patch('frappe.enqueue'):
            fulfilment.set_preparation(doc.sales_order,'Ready for pickup')
        fulfilment.queue_pickup_ready_email(doc.name)
        fulfilment.queue_pickup_ready_email(doc.name)
        self.assertEqual(self.sent.call_count,1)
        self.assertEqual(self.sent.call_args.kwargs['recipients'],['tester@example.com'])
        self.assertIn('ready for pickup',self.sent.call_args.kwargs['subject'])
        self.assertNotIn('Delivery to',self.sent.call_args.kwargs['message'])
        order=frappe.get_doc('Sales Order',doc.sales_order)
        self.assertEqual(order.custom_hospice_status,'Ready for pickup')
        self.assertTrue(frappe.get_doc('Callus Checkout',doc.name).pickup_ready_notified)
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):
            fulfilment.set_preparation(doc.sales_order,'Collected')

    def test_pickup_confirmation_has_no_delivery_address(self):
        self.buyer['delivery']='collection'
        self.pay();self.mark_paid();api.status(self.token)
        self.sent.reset_mock();hospice.queue_emails(api._doc(self.token).name)
        invoice=frappe.get_doc('Sales Invoice',api._doc(self.token).sales_invoice)
        self.assertFalse(invoice.customer_address)
        self.assertFalse(invoice.shipping_address_name)
        message=self.sent.call_args_list[0].kwargs['message']
        self.assertIn('Pickup from Callus Garden Centre',message)
        self.assertNotIn('Delivery to',message)
        self.assertNotIn('1 Garden Street',message)

    def delivery_note(self, qty=2):
        from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
        note=make_delivery_note(api._doc(self.token).sales_order)
        note.set('items',[row for row in note.items if row.item_code=='CHECKOUT-BASIL'])
        note.items[0].qty=qty
        note.insert();note.submit()
        return note

    def test_dispatch_note_advances_preparation_but_not_physical_delivery(self):
        self.pay();self.mark_paid();api.status(self.token)
        doc=api._doc(self.token)
        note=self.delivery_note()
        order=frappe.get_doc('Sales Order',doc.sales_order)
        self.assertEqual(order.custom_hospice_status,'Ready for dispatch')
        progress=fulfilment.progress_for(order,doc)
        self.assertEqual(progress['delivery_state'],'Ready for dispatch')
        self.assertEqual(progress['quantities'][0]['delivered_qty'],0)
        note.cancel()
        self.assertEqual(frappe.get_doc('Sales Order',doc.sales_order).custom_hospice_status,'Awaiting preparation')

    def test_partial_dispatch_remains_preparing(self):
        self.pay();self.mark_paid();api.status(self.token)
        self.delivery_note(qty=1)
        order=frappe.get_doc('Sales Order',api._doc(self.token).sales_order)
        self.assertEqual(order.custom_hospice_status,'Preparing')

    def test_pickup_dispatch_requires_explicit_handover(self):
        self.buyer['delivery']='collection'
        self.pay();self.mark_paid();api.status(self.token)
        doc=api._doc(self.token)
        with patch('frappe.enqueue'):
            note=self.delivery_note()
        self.assertFalse(note.customer_address)
        self.assertFalse(note.shipping_address_name)
        self.assertEqual(frappe.get_doc('Sales Order',doc.sales_order).custom_hospice_status,'Ready for pickup')
        with self.assertRaises(frappe.ValidationError):
            fulfilment.set_preparation(doc.sales_order,'Collected')
        self.assertEqual(frappe.get_doc('Sales Order',doc.sales_order).custom_hospice_status,'Ready for pickup')

    def test_collection_requires_stock_handover_document(self):
        self.buyer['delivery']='collection'
        self.pay();self.mark_paid();api.status(self.token)
        with patch('frappe.enqueue'):
            fulfilment.set_preparation(api._doc(self.token).sales_order,'Ready for pickup')
        with self.assertRaises(frappe.ValidationError):
            fulfilment.set_preparation(api._doc(self.token).sales_order,'Collected')

    def test_delivery_execution_overrides_preparation_and_excludes_service(self):
        self.pay();self.mark_paid();api.status(self.token)
        doc=api._doc(self.token);order=frappe.get_doc('Sales Order',doc.sales_order)
        for state in ['Scheduled','Out for delivery','Partially delivered','Delivered','Delivery needs attention']:
            with patch('bloominggarden.bloominggarden.customer_ordering.progress.order_progress',
                       return_value={'delivery_state':state,'quantities':[]}) as provider:
                self.assertEqual(fulfilment.progress_for(order,doc)['delivery_state'],state)
                self.assertEqual([row.item_code for row in provider.call_args.args[0].items],['CHECKOUT-BASIL'])

    def test_picking_automatically_advances_pickup_and_cancellation_reverts_it(self):
        self.buyer['delivery']='collection'
        self.pay();self.mark_paid();api.status(self.token)
        doc=api._doc(self.token);order=frappe.get_doc('Sales Order',doc.sales_order);row=order.items[0]
        picking=frappe.get_doc(dict(doctype='Pick List',company=COMPANY,customer=order.customer,
            purpose='Delivery',items_based_on='Sales Order',pick_manually=1,
            locations=[dict(item_code=row.item_code,warehouse=row.warehouse,uom=row.uom,stock_uom=row.stock_uom,
                qty=2,stock_qty=2,conversion_factor=1,picked_qty=2,
                sales_order=order.name,sales_order_item=row.name)]))
        with patch('frappe.enqueue'):
            picking.insert()
            self.assertEqual(frappe.get_doc('Sales Order',order.name).custom_hospice_status,'Preparing')
            picking.submit()
            self.assertEqual(frappe.get_doc('Sales Order',order.name).custom_hospice_status,'Ready for pickup')
            picking.cancel()
            self.assertEqual(frappe.get_doc('Sales Order',order.name).custom_hospice_status,'Awaiting preparation')

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
