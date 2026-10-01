"""Permission boundary regression tests without needing a Frappe site."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

fake = types.ModuleType('frappe')
fake.session = types.SimpleNamespace(user='Administrator')
fake.db = types.SimpleNamespace(exists=Mock(return_value=False), escape=lambda s: "'"+s.replace("'", "''")+"'")
spec=importlib.util.spec_from_file_location('marketing_access',Path(__file__).parents[1]/'webshop/callus_storefront/marketing_access.py')
module=importlib.util.module_from_spec(spec)
old=sys.modules.get('frappe');sys.modules['frappe']=fake
try:spec.loader.exec_module(module)
finally:
 if old is None:sys.modules.pop('frappe',None)
 else:sys.modules['frappe']=old

class Doc(dict):
 def __getattr__(self,key):return self.get(key)
class Tests(unittest.TestCase):
 def check(self,dt,action='read',**values):
  return module.has_permission(Doc(doctype=dt,name='X',**values),action,module.MARKETING_USER)
 def test_other_users_unchanged(self):
  for user in ['Administrator','staff@example.com','Guest']:
   self.assertIsNone(module.has_permission(Doc(doctype='Sales Invoice'), 'write', user))
   self.assertIsNone(module.permission_query(user,'Sales Invoice'))
 def test_products_allow_only_requested_actions(self):
  for dt in ['Item','Website Item']:
   for action in ['read','select','write']:self.assertIsNone(self.check(dt,action))
   for action in ['delete','submit','cancel','share','export','import','print','email']:self.assertIs(self.check(dt,action),False)
  self.assertIs(self.check('Item','create'),False)
  self.assertIsNone(self.check('Website Item','create'))
 def test_business_data_denied_even_with_inherited_role(self):
  for dt in ['Sales Invoice','POS Invoice','Customer','Contact','Email Template','Builder Page','Item Price','Payment Entry','User Permission','Role','Employee','Callus Checkout','Callus Checkout Settings']:
   for action in ['read','write','create']:self.assertIs(self.check(dt,action),False)
   self.assertEqual(module.permission_query(module.MARKETING_USER,dt),'1=0')
 def test_nonwebsite_order_denied(self):
  fake.db.exists.return_value=False
  self.assertIs(self.check('Sales Order'),False)
 def test_website_order_read_only(self):
  fake.db.exists.return_value=True
  self.assertIsNone(self.check('Sales Order'))
  for action in ['write','create','submit','cancel','delete','share','print','email','export']:self.assertIs(self.check('Sales Order',action),False)
 def test_list_filters_by_actual_checkout_not_customer(self):
  result=module.permission_query(module.MARKETING_USER,'Sales Order')
  self.assertIn('tabCallus Checkout',result);self.assertNotIn('customer_group',result)
 def test_uploads_confined_to_product_files(self):
  for target in ['Item','Website Item',None]:
   self.assertIsNone(self.check('File','create',owner=module.MARKETING_USER,attached_to_doctype=target))
  self.assertIs(self.check('File','read',owner=module.MARKETING_USER,attached_to_doctype='Sales Invoice'),False)
  self.assertIs(self.check('File','write',owner='Administrator',attached_to_doctype='Item'),False)
 def test_self_user_read_only(self):
  self.assertIsNone(module.has_permission(Doc(doctype='User',name=module.MARKETING_USER),'read',module.MARKETING_USER))
  self.assertIs(self.check('User'),False)
 def test_help_tour_read_only(self):
  self.assertIsNone(self.check('Form Tour'))
  self.assertIsNone(module.permission_query(module.MARKETING_USER,'Form Tour'))
  self.assertIs(self.check('Form Tour','write'),False)
 def test_references_read_only(self):
  for dt in module.REFERENCE_TYPES:
   self.assertIsNone(self.check(dt));self.assertIs(self.check(dt,'write'),False)
if __name__=='__main__':unittest.main()
