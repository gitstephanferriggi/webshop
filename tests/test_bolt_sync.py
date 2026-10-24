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
if __name__=='__main__':unittest.main()
