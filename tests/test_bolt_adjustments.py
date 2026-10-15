import unittest
from webshop.bolt_integration.adjustments import build_adjustment, confirmed_basket

class AdjustmentTests(unittest.TestCase):
 def setUp(self):
  self.lines=[{'id':'a','code':'A','qty':3,'rate':5},{'id':'b','code':'B','qty':1,'rate':10}]
 def test_quantity_reduction_and_zero_removal(self):
  p=build_adjustment(self.lines,{'a':2,'b':0},{},{})
  self.assertEqual(p['items'],[{'sku':'A','amount':2}]);self.assertEqual(p['expected_total'],10)
 def test_cheaper_replacement(self):
  p=build_adjustment(self.lines,{'a':2,'b':1},{'a':'C'},{'C':4})
  self.assertEqual(p['expected_total'],18)
  self.assertEqual(p['items'][0]['replacement_for'],[{'replaced_sku':'A','replaced_quantity':2,'picked_quantity':2}])
 def test_unknown_or_more_expensive_replacement(self):
  for catalogue in ({},{'C':6}):
   with self.assertRaises(ValueError):build_adjustment(self.lines,{'a':2,'b':1},{'a':'C'},catalogue)
 def test_no_empty_no_unchanged_no_fraction(self):
  for quantities in ({'a':0,'b':0},{'a':3,'b':1},{'a':1.5,'b':1}):
   with self.assertRaises(ValueError):build_adjustment(self.lines,quantities,{},{})
 def test_duplicate_sku_aggregated(self):
  rows=[{'id':'a','code':'A','qty':2,'rate':5},{'id':'b','code':'A','qty':2,'rate':5}]
  self.assertEqual(build_adjustment(rows,{'a':1,'b':2},{},{})['items'],[{'sku':'A','amount':3}])
 def basket(self):
  return {'order_id':42,'total_price':10,'items':[{'sku':'A','picked_amount':2,'price':5,'total_price':10,'selling_unit':'piece'}]}
 def test_confirmed_exact_basket(self):
  result=confirmed_basket(self.basket(),'42',{'A':{'qty':2,'rate':5}},25)
  self.assertEqual(result['total_order_price']['value'],10)
 def test_unexpected_order_quantity_price_total_or_unit_blocked(self):
  for key,value in [('sku','B'),('picked_amount',3),('price',4),('total_price',9),('selling_unit','kg')]:
   p=self.basket();p['items'][0][key]=value
   with self.assertRaises(ValueError):confirmed_basket(p,42,{'A':{'qty':2,'rate':5}},25)
  for key,value in [('order_id',43),('total_price',11)]:
   p=self.basket();p[key]=value
   with self.assertRaises(ValueError):confirmed_basket(p,42,{'A':{'qty':2,'rate':5}},25)
 def test_actual_bolt_money_object_and_null_piece_quantity(self):
  p=self.basket();p['total_price']={'value':10,'currency':'eur'};p['items'][0]['picked_amount']=None
  self.assertEqual(confirmed_basket(p,42,{'A':{'qty':2,'rate':5}},25)['items'][0]['qty'],2)
  p['total_price']['currency']='usd'
  with self.assertRaises(ValueError):confirmed_basket(p,42,{'A':{'qty':2,'rate':5}},25)
 def test_null_quantity_does_not_bypass_expected_basket(self):
  for rate,amount in [(5,11),(0,0),(5,15)]:
   p=self.basket();p['items'][0].update(picked_amount=None,price=rate,total_price=amount)
   with self.assertRaises(ValueError):confirmed_basket(p,42,{'A':{'qty':2,'rate':5}},25)
 def test_no_increased_charge(self):
  with self.assertRaises(ValueError):confirmed_basket(self.basket(),42,{'A':{'qty':2,'rate':5}},9)
 def test_duplicate_lines_blocked(self):
  p=self.basket();p['items']*=2;p['total_price']=20
  with self.assertRaises(ValueError):confirmed_basket(p,42,{'A':{'qty':4,'rate':5}},25)
 def test_removed_zero_line_allowed(self):
  p=self.basket();p['items'].append({'sku':'B','picked_amount':0,'price':10,'total_price':0,'selling_unit':'piece'})
  self.assertEqual(confirmed_basket(p,42,{'A':{'qty':2,'rate':5}},25)['total_order_price']['value'],10)

if __name__=='__main__':unittest.main()
