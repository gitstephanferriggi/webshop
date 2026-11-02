import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

class ClientTests(unittest.TestCase):
 def setUp(self):
  self.requests=MagicMock()
  self.modules=patch.dict(sys.modules,{'requests':self.requests,'frappe':MagicMock()});self.modules.start()
  sys.modules.pop('webshop.bolt_integration.client',None)
  self.client=importlib.import_module('webshop.bolt_integration.client')
  self.settings=SimpleNamespace(integrator_id='test',get_password=lambda _: 'test-secret')
  self.response=self.requests.post.return_value
  self.response.status_code=200;self.response.content=b''
  self.response.json.side_effect=ValueError('No JSON')
 def tearDown(self):
  self.modules.stop();sys.modules.pop('webshop.bolt_integration.client',None)
 def test_documented_empty_success(self):
  for path in self.client.EMPTY_OK_PATHS:
   self.assertEqual(self.client.request(self.settings,path,{'provider_id':'test'}),{})
  self.response.json.assert_not_called()
 def test_adjusted_ready_empty_success(self):
  self.assertEqual(self.client.request(self.settings,'/genericClient/markOrderWithItemsAsReadyForPickUp',{}),{})
 def test_already_in_requested_state(self):
  self.response.status_code=304
  for path in self.client.EMPTY_OK_PATHS:
   self.assertEqual(self.client.request(self.settings,path,{}),{'unchanged':True})
 def test_empty_basket_is_not_success(self):
  with self.assertRaises(ValueError):self.client.request(self.settings,'/genericClient/getOrderBasket',{})
 def test_http_error_is_never_accepted(self):
  self.response.status_code=403;self.response.raise_for_status.side_effect=RuntimeError('Forbidden')
  with self.assertRaises(RuntimeError):self.client.request(self.settings,'/genericClient/acceptOrder',{})
 def test_json_business_error_not_accepted(self):
  self.response.content=b'{"code":1006}';self.response.json.side_effect=None;self.response.json.return_value={'code':1006,'message':'Forbidden'}
  with self.assertRaises(ValueError):self.client.request(self.settings,'/genericClient/acceptOrder',{})
 def test_json_data_preserved(self):
  self.response.content=b'{}';self.response.json.side_effect=None;self.response.json.return_value={'order_id':42,'items':[]}
  self.assertEqual(self.client.request(self.settings,'/genericClient/getOrderBasket',{})['order_id'],42)

 def import_response(self, warnings, errors=None):
  self.settings.vat_tag='bm_vat_0'
  self.response.content=b'{}';self.response.json.side_effect=None
  self.response.json.return_value={'data':{'state':'waiting_for_apply','warnings':warnings,'errors':errors or []}}
 def test_confirmed_tag_warning_is_acknowledged(self):
  self.import_response([{'message':'VAT tag "bm_vat_0" not found for SKU ITE-1'}])
  result=self.client.request(self.settings,'/pim/v1/products/import/status/retrieve',{})
  self.assertEqual(result['warnings'],[])
  self.assertEqual(result['acknowledged_vat_warning_count'],1)
 def test_unrelated_nested_warnings_are_retained(self):
  warning={'message':'Image download failed'}
  self.import_response([{'message':'VAT tag "bm_vat_0" not found for SKU ITE-1'},warning])
  result=self.client.request(self.settings,'/pim/v1/products/import/status/retrieve',{})
  self.assertEqual(result['warnings'],[warning])
 def test_import_errors_survive_tag_acknowledgement(self):
  error={'error_type':'invalid_url','skus':['ITE-1']}
  self.import_response([{'message':'VAT tag "bm_vat_0" not found for SKU ITE-1'}],[error])
  result=self.client.request(self.settings,'/pim/v1/products/import/status/retrieve',{})
  self.assertEqual(result['errors'],[error])
 def test_other_configured_tag_does_not_acknowledge_warning(self):
  warning={'message':'VAT tag "bm_vat_0" not found for SKU ITE-1'}
  self.import_response([warning]);self.settings.vat_tag='different'
  self.assertEqual(self.client.request(self.settings,'/pim/v1/products/import/status/retrieve',{})['warnings'],[warning])
 def test_warning_on_other_endpoint_is_still_rejected(self):
  self.import_response([])
  self.response.json.return_value={'warnings':[{'message':'VAT tag "bm_vat_0" not found for SKU ITE-1'}]}
  with self.assertRaises(ValueError):self.client.request(self.settings,'/genericClient/getMenu',{})

if __name__=='__main__':unittest.main()
