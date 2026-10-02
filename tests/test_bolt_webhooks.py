"""Run without a bench: python3 -m unittest discover -s tests -p test_bolt_webhooks.py."""
import importlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from webshop.bolt_integration.validation import validate, receipt_key, EVENTS, MAX_BYTES


def fixture(event):
    p = dict(provider_id='store-1', order_id=123, order_reference_id='REF1')
    if event == 'new_order':
        p.update(order_type='delivery', payment_type='card_online', created_ts=1, due_ts=2,
                 created_datetime='2026-10-02T10:00:00Z', due_datetime='2026-10-02T10:15:00Z',
                 customer={}, items=[dict(sku='SKU1', qty=1)], total_order_price=dict(value=10,currency='eur'))
    if event == 'order_update':p.update(main_order_id=123, request_type='order_preparing')
    if event == 'provider_status':p['new_status']='active'
    if event == 'courier_details':p['courier']={'partial_name':'Test'}
    return p


class ValidationTests(unittest.TestCase):
    def test_all_five_events(self):
        for event in EVENTS:
            with self.subTest(event=event):self.assertEqual(validate(event,fixture(event))[0],'store-1')
    def test_invalid_fields(self):
        for event in EVENTS:
            for value in (None, '', {}, True, 'x'*141):
                p=fixture(event);p['provider_id']=value
                with self.subTest(event=event,value=value),self.assertRaises(ValueError):validate(event,p)
    def test_incomplete_new_order(self):
        for key in fixture('new_order'):
            p=fixture('new_order');del p[key]
            with self.subTest(key=key),self.assertRaises(ValueError):validate('new_order',p)
    def test_reject_bad_items_and_prices(self):
        for items in ([], [None], [{'sku':'a','qty':-1}], [{'sku':'a','qty':float('nan')}], [{'sku':'a','qty':True}]):
            p=fixture('new_order');p['items']=items
            with self.assertRaises(ValueError):validate('new_order',p)
    def test_canonical_duplicates_and_changed_payload(self):
        p=fixture('new_order'); a=validate('new_order',p)
        b=validate('new_order',dict(reversed(list(p.items()))))
        self.assertEqual(a,b)
        key=receipt_key('new_order',a[0],a[1],a[3])
        p['order_state']='ACCEPTED';c=validate('new_order',p)
        self.assertNotEqual(key,receipt_key('new_order',c[0],c[1],c[3]))
        self.assertNotEqual(key,receipt_key('cancel_order',a[0],a[1],a[3]))
    def test_status_transitions_are_not_deduplicated(self):
        self.assertIsNone(receipt_key('provider_status','store-1','','hash'))
    def test_future_fields_retained(self):
        p=fixture('order_update');p.update(request_type='future_event',future_data={'extra':1})
        self.assertIn('future_data',validate('order_update',p)[2])
    def test_cmd_rejected(self):
        p=fixture('provider_status');p['cmd']='frappe.client.get'
        with self.assertRaises(ValueError):validate('provider_status',p)


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.f=MagicMock();self.f.whitelist=lambda **kw:lambda fn:fn
        self.f.PermissionError=PermissionError
        self.f.DuplicateEntryError=type('DuplicateEntryError',(Exception,),{})
        self.f.session=NS(user='bolt-webhook@callusgardencentre.com')
        self.f.local=NS(response=NS(http_status_code=200))
        self.f.form_dict={}
        self.headers={'Authorization':'Basic fixture'}
        self.f.get_request_header=lambda key,default=None:self.headers.get(key,default)
        self.f.request=NS(path='/api/method/webshop.bolt_integration.webhooks.new_order',method='POST',host='uat.example',mimetype='application/json',content_length=1,get_data=lambda:json.dumps(fixture('new_order')).encode())
        self.settings=NS(enabled=1,environment='Staging',site_hostname='uat.example',provider_id='store-1')
        self.f.get_single.return_value=self.settings
        self.f.db.exists.return_value=False
        self.modules=patch.dict(sys.modules,{'frappe':self.f});self.modules.start()
        sys.modules.pop('webshop.bolt_integration.webhooks',None)
        self.w=importlib.import_module('webshop.bolt_integration.webhooks')
    def tearDown(self):
        self.modules.stop();sys.modules.pop('webshop.bolt_integration.webhooks',None)
    def test_persist_success(self):
        r=self.w.new_order();self.assertTrue(r['received']);self.assertFalse(r['duplicate'])
        self.f.get_doc.return_value.insert.assert_called_once_with(ignore_permissions=True)
        self.assertEqual(self.f.get_doc.call_args.args[0]['provider_verified'],1)
        self.f.enqueue.assert_not_called()
    def test_duplicate_no_insert(self):
        self.f.db.exists.return_value=True
        self.assertTrue(self.w.new_order()['duplicate']);self.f.get_doc.assert_not_called()
    def test_concurrent_duplicate(self):
        self.f.db.exists.side_effect=[False,True]
        self.f.get_doc.return_value.insert.side_effect=self.f.DuplicateEntryError()
        self.assertTrue(self.w.new_order()['duplicate'])
        self.f.db.rollback.assert_called_once_with(save_point='bolt_receipt')
    def test_database_error_not_acknowledged(self):
        self.f.get_doc.return_value.insert.side_effect=RuntimeError('database unavailable')
        with self.assertRaises(RuntimeError):self.w.new_order()
    def test_disabled_and_clone_fail_closed(self):
        self.settings.enabled=0;self.assertEqual(self.w.new_order()['error'],'receiver_disabled')
        self.settings.enabled=1;self.settings.site_hostname='production.example'
        self.assertEqual(self.w.new_order()['error'],'site_binding_mismatch')
        self.f.get_doc.assert_not_called()
    def test_provider_mismatch(self):
        self.settings.provider_id='other';self.assertEqual(self.w.new_order()['error'],'provider_not_allowed')
        self.f.get_doc.assert_not_called()
    def test_onboarding_captures_unverified(self):
        self.settings.provider_id='';self.w.new_order()
        self.assertEqual(self.f.get_doc.call_args.args[0]['provider_verified'],0)
    def test_wrong_user(self):
        self.f.session.user='Administrator'
        with self.assertRaises(PermissionError):self.w.new_order()
    def test_service_user_other_routes_forbidden(self):
        for path in ('/api/resource/Item','/api/method/frappe.auth.get_logged_user','/api/v1/method/webshop.bolt_integration.webhooks.new_order','/app','/'):
            self.f.request.path=path
            with self.subTest(path=path),self.assertRaises(PermissionError):self.w.restrict_service_user()
    def test_normal_users_unaffected(self):
        self.f.session.user='staff@example.com';self.f.request.path='/app';self.w.restrict_service_user()
    def test_method_and_auth_restrictions(self):
        self.f.request.method='GET'
        with self.assertRaises(PermissionError):self.w.restrict_service_user()
        self.f.request.method='POST'
        for authorization in ('','token fixture','Bearer fixture'):
            self.headers['Authorization']=authorization
            with self.assertRaises(PermissionError):self.w.restrict_service_user()
    def test_cmd_and_alternate_auth_source(self):
        self.f.form_dict={'cmd':'frappe.client.get'}
        with self.assertRaises(PermissionError):self.w.restrict_service_user()
        self.f.form_dict={};self.headers['Frappe-Authorization-Source']='Other'
        with self.assertRaises(PermissionError):self.w.restrict_service_user()
    def test_bad_payloads(self):
        for raw in (b'[]',b'{',b'{"provider_id":NaN}',b'\xff'):
            self.f.request.get_data=lambda:raw
            self.assertEqual(self.w.new_order()['error'],'invalid_payload')
        self.f.get_doc.assert_not_called()
    def test_size_and_content_type(self):
        self.f.request.content_length=MAX_BYTES+1
        self.assertEqual(self.w.new_order()['error'],'payload_too_large')
        self.f.request.content_length=None;self.f.request.get_data=lambda:b' '* (MAX_BYTES+1)
        self.assertEqual(self.w.new_order()['error'],'payload_too_large')
        self.f.request.mimetype='text/plain'
        self.assertEqual(self.w.new_order()['error'],'json_required')
    def test_all_routes(self):
        for event in EVENTS:
            self.f.request.path=self.w.PREFIX+event
            self.f.request.get_data=lambda:json.dumps(fixture(event)).encode()
            with self.subTest(event=event):self.assertTrue(getattr(self.w,event)()['received'])
    def test_health_no_secrets(self):
        self.f.request.path=self.w.PREFIX+'health';self.f.request.method='GET'
        r=self.w.health();self.assertEqual(r['mode'],'capture_only')
        self.assertEqual(set(r),{'ok','release','enabled','environment','mode','provider_configured'})

if __name__=='__main__':unittest.main()
