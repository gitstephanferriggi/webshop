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

if __name__=='__main__':unittest.main()
