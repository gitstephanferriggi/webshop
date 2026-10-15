import importlib,sys,unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock,patch

class ProcessingTests(unittest.TestCase):
 def setUp(self):
  self.f=MagicMock();self.f.whitelist=lambda **kw:lambda fn:fn;self.f.DuplicateEntryError=type('Duplicate', (Exception,), {})
  utils=MagicMock();utils.nowdate.return_value='2026-10-05';utils.get_url.return_value='https://uat.example'
  self.modules=patch.dict(sys.modules,{'frappe':self.f,'frappe.utils':utils});self.modules.start()
  sys.modules.pop('webshop.bolt_integration.processing',None)
  self.p=importlib.import_module('webshop.bolt_integration.processing')
 def tearDown(self):self.modules.stop();sys.modules.pop('webshop.bolt_integration.processing',None)
 def event(self,kind='new_order'):
  import json
  return NS(is_test=0,provider_verified=1,provider_id='P',bolt_order_id='42',event_type=kind,payload=json.dumps({'items':[],'total_order_price':{'value':0,'currency':'EUR'}}),db_set=MagicMock())
 def test_completed_event_is_skipped_after_lock(self):
  self.f.get_all.return_value=['event1']
  self.f.get_doc.return_value=NS(status='Processed')
  with patch.object(self.p,'enabled_settings',return_value=NS()), patch.object(self.p,'process_event') as process:
   self.p.process_pending()
  self.f.get_doc.assert_called_once_with('Callus Bolt Event','event1',for_update=True)
  process.assert_not_called()
  self.f.db.commit.assert_called_once()
 def test_pending_event_is_processed_under_lock(self):
  self.f.get_all.return_value=['event1']
  event=NS(status='Captured');self.f.get_doc.return_value=event
  settings=NS()
  with patch.object(self.p,'enabled_settings',return_value=settings), patch.object(self.p,'process_event') as process:
   self.p.process_pending()
  self.f.get_doc.assert_called_once_with('Callus Bolt Event','event1',for_update=True)
  process.assert_called_once_with(event,settings)
  self.f.db.commit.assert_called_once()
 def test_worker_uses_internal_identity_and_restores_webhook_user(self):
  self.f.session.user='bolt-webhook@example.com'
  self.f.local.session={'user':'bolt-webhook@example.com','sid':'original'}
  form={'original':True};self.f.local.form_dict=form
  def set_user(user):
   self.f.session.user=user
   self.f.local.session={'user':user}
  self.f.set_user.side_effect=set_user
  for fail in [False,True]:
   with self.subTest(failure=fail):
    try:
     with self.p._processing_user():
      self.assertEqual(self.f.session.user,'Administrator')
      if fail:raise RuntimeError('ERP validation failed')
    except RuntimeError:pass
    self.assertEqual(self.f.session.user,'bolt-webhook@example.com')
    self.assertEqual(self.f.local.session,{'user':'bolt-webhook@example.com','sid':'original'})
    self.assertIs(self.f.local.form_dict,form)
 def test_retry_requires_manager_before_reading_event(self):
  self.f.only_for.side_effect=PermissionError
  with self.assertRaises(PermissionError):self.p.retry_event('event1')
  self.f.get_doc.assert_not_called()
 def test_retry_refuses_processed_events(self):
  self.f.get_doc.return_value=NS(status='Processed')
  self.f.throw.side_effect=ValueError
  with self.assertRaises(ValueError):self.p.retry_event('event1')

 def test_due_time_is_site_local_without_timezone_for_mariadb(self):
  from datetime import datetime, timezone
  from zoneinfo import ZoneInfo
  converter=sys.modules['frappe.utils'].convert_utc_to_system_timezone
  converter.side_effect=lambda value:value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Malta'))
  for month,hour in [(7,14),(12,13)]:
   utc=datetime(2026,month,14,12,0,tzinfo=timezone.utc)
   result=self.p.site_due_at(utc.timestamp())
   self.assertIsNone(result.tzinfo)
   self.assertEqual(result,datetime(2026,month,14,hour,0))
 def test_disabled_processing_returns_without_work(self):
  self.f.get_single.return_value=NS(enabled=1,process_orders=0)
  self.assertIsNone(self.p.enabled_settings())
 def test_synthetic_fixture_never_creates_sale(self):
  e=self.event();e.is_test=1;self.p.process_event(e,NS(provider_id='P'))
  self.f.get_doc.assert_not_called();e.db_set.assert_called_once_with('status','Ignored')
 def test_wrong_provider_never_creates_sale(self):
  e=self.event();self.p.process_event(e,NS(provider_id='OTHER'))
  self.f.get_doc.assert_not_called()
 def test_cancel_before_create_does_not_resurrect(self):
  order=NS(status='Cancelled',sales_order=None,save=MagicMock());self.f.get_doc.return_value=order;self.f.db.exists.return_value=True
  with patch.object(self.p,'create_sale') as create:self.p.process_event(self.event(),NS(provider_id='P'));create.assert_not_called()
 def test_exact_duplicate_does_not_create_second_sale(self):
  import json
  e=self.event();order=NS(status='Recorded',sales_order='SO1',source_hash=self.p.basket_hash(json.loads(e.payload)),save=MagicMock())
  self.f.get_doc.return_value=order;self.f.db.exists.return_value=True
  with patch.object(self.p,'create_sale') as create:self.p.process_event(e,NS(provider_id='P'));create.assert_not_called()
 def test_cancel_draft_without_remarks_field(self):
  so=NS(docstatus=0,per_delivered=0,add_comment=MagicMock())
  link=NS(sales_invoice=None,sales_order='SO1',status='Draft Sale')
  self.f.get_doc.return_value=so
  self.p.cancel_sale(link)
  so.add_comment.assert_called_once_with('Comment','Cancelled by Bolt; do not fulfil.')
  self.assertEqual(link.status,'Cancelled')
 def test_pickup_receipt_does_not_create_another_sale(self):
  import json
  e=self.event('courier_picked_up');e.payload=json.dumps({'pickup_ts':100})
  order=NS(status='Recorded',sales_order='SO1',workflow_state='Collected',get=lambda key:0,save=MagicMock())
  self.f.get_doc.return_value=order;self.f.db.exists.return_value=True
  with patch.object(self.p,'create_sale') as create:
   self.p.process_event(e,NS(provider_id='P'));create.assert_not_called()
  self.assertEqual(order.courier_pickup_ts,100);self.assertEqual(order.workflow_state,'Collected')
 def test_basket_content_change_detected_even_same_total(self):
  self.assertNotEqual(self.p.basket_hash({'items':[{'sku':'A'}],'total_order_price':{'value':10}}),self.p.basket_hash({'items':[{'sku':'B'}],'total_order_price':{'value':10}}))
if __name__=='__main__':unittest.main()
