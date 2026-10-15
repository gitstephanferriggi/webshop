import unittest
from webshop.bolt_integration.pricing import selling_price, markup_percentage
from webshop.bolt_integration.catalogue import build
from webshop.bolt_integration.orders import sales_lines

class BoltPricingTests(unittest.TestCase):
 def test_markup_and_decimal_rounding(self):
  for base, expected in [(5,6),(2.5,3),(0.500000001,0.6),(4.99,5.99),(1.025,1.23)]:
   self.assertEqual(selling_price(base,20),expected)
  self.assertEqual(selling_price(5,0),5)
 def test_invalid_markup(self):
  for value in [-1,'NaN','Infinity','bad',True]:
   with self.assertRaises(ValueError):markup_percentage(value)
 def test_repeated_catalogue_build_never_compounds_or_changes_source_price(self):
  prices={'A':5}
  args=({'A':dict(item_name='Plant',item_group='Plants',stock_uom='Pcs',is_sales_item=1)},[dict(item_code='A',custom_bolt_enabled=1)],prices,{},'provider','https://example.com')
  for _ in range(2):
   self.assertEqual(build(*args,price_markup_percent=20)['prices'],[{'sku':'A','base_selling_price':6}])
  self.assertEqual(prices,{'A':5})
 def test_imported_order_uses_bolt_price_without_another_markup(self):
  payload={'items':[{'sku':'A','qty':1,'unit_item_price':{'value':6,'currency':'EUR'},'total_item_price':{'value':6,'currency':'EUR'}}],'total_order_price':{'value':6,'currency':'EUR'}}
  rows=sales_lines(payload,lambda _:dict(stock_uom='Pcs',disabled=0,is_sales_item=1))
  self.assertEqual(rows[0]['rate'],6)
