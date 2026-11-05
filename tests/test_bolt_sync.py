import importlib,json,sys,unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock,patch
def raise_error(message):
 raise ValueError(message)
class SyncTests(unittest.TestCase):
 def setUp(self):
  self.f=MagicMock();self.f.whitelist=lambda **kw:lambda fn:fn;self.modules=patch.dict(sys.modules,{'frappe':self.f,'frappe.utils':MagicMock(),'requests':MagicMock()});self.modules.start()
  sys.modules.pop('webshop.bolt_integration.sync',None);self.m=importlib.import_module('webshop.bolt_integration.sync')
 def tearDown(self):self.modules.stop();sys.modules.pop('webshop.bolt_integration.sync',None)
 def settings(self,phase):return NS(region_id=1,provider_id='test',integrator_id='id',secret_key='hidden',vat_tag='standard',price_list='POS',sync_phase=phase,sync_snapshot=json.dumps({'products':[{'sku':'A'}],'stocks':[{'sku':'A','quantity':2}],'prices':[{'sku':'A','base_selling_price':3}],'removed':[]}),last_synced_skus='[]')
 def test_dont_apply_while_preparing(self):
  with patch.object(self.m,'request',return_value={'state':'preparing'}) as req:self.m.step(self.settings('Product validation'));self.assertEqual(req.call_count,1)
  self.f.db.set_single_value.assert_not_called()
 def test_ready_import_applied_then_waited(self):
  with patch.object(self.m,'request',side_effect=[{'state':'waiting_for_apply'},{'state':'success'}]) as req:self.m.step(self.settings('Product validation'));self.assertEqual(req.call_args.args[1],'/pim/v1/products/import/apply')
  self.assertEqual(self.f.db.set_single_value.call_args.args[1]['sync_phase'],'Product applying')
 def test_removal_withdraws_provider_assignment(self):
  s=self.settings('Remove products');s.sync_snapshot=json.dumps({'removed':['A']})
  with patch.object(self.m,'request',return_value={'state':'success'}) as req:self.m.step(s);self.assertEqual(req.call_args.args[2]['products'],[{'sku':'A','provider_ids':[]}])
 def test_ready_menu_is_only_stage_that_publishes(self):
  with patch.object(self.m,'request',side_effect=[{'state':'waiting_for_review'},{'menus':[]},{'state':'success'}]) as req:self.m.step(self.settings('Menu validation'));self.assertEqual(req.call_args.args[1],'/pim/v1/menu/drafts/publish')
 def test_scheduled_publication_is_not_completion(self):
  with patch.object(self.m,'request',return_value={'menus':[{'id':1,'state':'scheduled'}]}) as req:self.m.step(self.settings('Publishing'));self.assertEqual(req.call_count,1)
  self.f.db.set_single_value.assert_not_called()
 def test_review_pauses_sync(self):
  with patch.object(self.m,'request') as req:self.m.step(self.settings('Review'));req.assert_not_called()
 def test_invalid_published_selection_is_zeroed_before_review(self):
  s=self.settings('Idle');s.last_synced_skus=json.dumps(['A','B','C'])
  data={'products':[{'sku':'C'}],'excluded':[{'item_code':'A','reason':'disabled'}]}
  self.f.throw.side_effect=raise_error
  with patch.object(self.m,'snapshot',return_value=data),patch.object(self.m,'request',return_value={'affected_skus':2}) as req:
   with self.assertRaisesRegex(ValueError,'mapping review'):self.m.step(s)
  req.assert_called_once_with(s,'/genericClient/updateMenuQuantity',{'provider_id':'test','sku_quantities':[{'sku':'A','quantity':0},{'sku':'B','quantity':0}]})
  self.f.db.set_single_value.assert_not_called()
 def test_invalid_unpublished_selection_does_not_send_quantity(self):
  s=self.settings('Idle');self.f.throw.side_effect=raise_error
  with patch.object(self.m,'snapshot',return_value={'products':[],'excluded':[{'item_code':'A'}]}),patch.object(self.m,'request') as req:
   with self.assertRaisesRegex(ValueError,'mapping review'):self.m.step(s)
  req.assert_not_called()
 def test_incomplete_withdrawal_requires_explicit_review(self):
  s=self.settings('Idle');s.last_synced_skus=json.dumps(['A']);self.f.throw.side_effect=raise_error
  with patch.object(self.m,'snapshot',return_value={'products':[],'excluded':[{'item_code':'A'}]}),patch.object(self.m,'request',return_value={'affected_skus':0}):
   with self.assertRaisesRegex(ValueError,'verify Bolt availability'):self.m.step(s)
  self.f.db.set_single_value.assert_not_called()
 def scheduled_tick(self):
  self.f.get_single.return_value=NS(enabled=1,sync_catalogue=1,site_hostname='uat.example')
  self.m.get_url.return_value='https://uat.example'
  return patch('webshop.bolt_integration.entitlement.new_work_allowed',return_value=True)
 def test_scheduled_lock_is_scoped_to_the_site(self):
  cache=self.f.cache.return_value
  cache.make_key.return_value=b'uat_db|callus-bolt-catalogue'
  with self.scheduled_tick(),patch.object(self.m,'step') as step:
   self.m.tick()
  cache.make_key.assert_called_once_with('callus-bolt-catalogue')
  cache.lock.assert_called_once_with(b'uat_db|callus-bolt-catalogue',timeout=240)
  cache.lock.return_value.acquire.assert_called_once_with(blocking=False)
  cache.lock.return_value.release.assert_called_once_with()
  step.assert_called_once_with(self.f.get_single.return_value)
  self.f.db.commit.assert_called_once_with()
 def test_busy_site_skips_without_changing_sync_state(self):
  lock=self.f.cache.return_value.lock.return_value
  lock.acquire.return_value=False
  with self.scheduled_tick(),patch.object(self.m,'step') as step:
   self.m.tick()
  step.assert_not_called();lock.release.assert_not_called()
  self.f.db.commit.assert_not_called();self.f.db.rollback.assert_not_called()
  self.f.db.set_single_value.assert_not_called();self.f.log_error.assert_not_called()
 def test_sync_error_marks_review_and_releases_lock(self):
  lock=self.f.cache.return_value.lock.return_value
  with self.scheduled_tick(),patch.object(self.m,'step',side_effect=ValueError('Bolt request failed')):
   self.m.tick()
  self.f.db.rollback.assert_called_once_with()
  self.f.db.set_single_value.assert_called_once_with('Callus Bolt Settings',{'sync_phase':'Review','sync_error':'Bolt request failed'})
  lock.release.assert_called_once_with()
 def test_other_site_can_sync_while_this_site_is_busy(self):
  from threading import Lock
  locks={}
  class Cache:
   def __init__(self,site):self.site=site
   def make_key(self,key):return (self.site+'|'+key).encode()
   def lock(self,key,**kwargs):return locks.setdefault(key,Lock())
  uat=Cache('uat_db');production=Cache('production_db')
  busy=uat.lock(uat.make_key('callus-bolt-catalogue'));busy.acquire()
  with self.scheduled_tick(),patch.object(self.m,'step') as step:
   self.f.cache.return_value=uat;self.m.tick();step.assert_not_called()
   self.f.cache.return_value=production
   self.f.get_single.return_value.site_hostname='production.example'
   self.m.get_url.return_value='https://production.example'
   self.m.tick();step.assert_called_once()
  self.assertTrue(busy.locked());busy.release()
  self.assertFalse(production.lock(production.make_key('callus-bolt-catalogue')).locked())
 def test_cache_failure_is_not_hidden_as_a_busy_job(self):
  self.f.cache.return_value.lock.return_value.acquire.side_effect=ConnectionError('Redis unavailable')
  with self.scheduled_tick(),patch.object(self.m,'step') as step:
   with self.assertRaisesRegex(ConnectionError,'Redis unavailable'):self.m.tick()
  step.assert_not_called();self.f.db.set_single_value.assert_not_called()
if __name__=='__main__':unittest.main()
