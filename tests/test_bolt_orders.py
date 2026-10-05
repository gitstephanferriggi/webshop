import copy, unittest
from webshop.bolt_integration.orders import sales_lines,order_key
class OrderTests(unittest.TestCase):
 def fixture(self):
  return {'total_order_price':{'value':25,'currency':'eur'},'items':[{'sku':'SKU1','qty':2,'unit_item_price':{'value':12.5,'currency':'eur'},'total_item_price':{'value':25,'currency':'eur'}}]}
 def item(self,sku):return {'stock_uom':'Pcs','is_sales_item':1}
 def test_piece_basket(self):self.assertEqual(sales_lines(self.fixture(),self.item)[0]['qty'],2)
 def test_identity_stable_across_changed_payloads(self):
  self.assertEqual(order_key('p',123),order_key('p','123'));self.assertNotEqual(order_key('p',123),order_key('q',123))
 def test_reject_inconsistent_basket(self):
  p=self.fixture();p['total_order_price']['value']=24
  with self.assertRaises(ValueError):sales_lines(p,self.item)
 def test_reject_unsupported_or_nonfinite_line(self):
  for key,value in [('qty',0),('qty',1.5),('qty',float('nan')),('options',[{'sku':'other'}]),('measure',{'unit':'kg'})]:
   p=self.fixture();p['items'][0][key]=value
   with self.subTest(key=key,value=value),self.assertRaises(ValueError):sales_lines(p,self.item)
 def test_reject_unknown_sku(self):
  with self.assertRaises(ValueError):sales_lines(self.fixture(),lambda sku:None)
 def test_reject_missing_item_price(self):
  p=self.fixture();del p['items'][0]['unit_item_price']
  with self.assertRaises(ValueError):sales_lines(p,self.item)
if __name__=='__main__':unittest.main()
