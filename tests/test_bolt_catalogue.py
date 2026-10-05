import unittest
from webshop.bolt_integration.catalogue import build, available_stock

class CatalogueTests(unittest.TestCase):
    def data(self,published=0,flag=1):
        return build({'A':dict(name='A',item_name='Plant',item_group='Shrubs',stock_uom='Pcs',is_sales_item=1)},
                     [dict(item_code='A',published=published,custom_bolt_enabled=flag)],{'A':12.5},
                     {'A':dict(actual_qty=5,reserved_qty=2)},'test-store','https://example.com')
    def test_unpublished_website_item_can_be_on_bolt(self):
        self.assertEqual(self.data()['products'][0]['sku'],'A')
    def test_published_website_item_is_not_implicitly_on_bolt(self):
        self.assertEqual(self.data(published=1,flag=0)['products'],[])
    def test_reserved_stock_and_nonnegative_clamp(self):
        self.assertEqual(self.data()['stocks'][0]['quantity'],3)
        self.assertEqual(available_stock(1,3),0)
        self.assertEqual(available_stock(2.9,0),2)
        self.assertEqual(available_stock(20000,0),10000)
    def test_provider_scoping(self):
        self.assertEqual(self.data()['products'][0]['provider_ids'],['test-store'])
    def test_unpriced_selection_is_reported_not_sent(self):
        d=build({'A':dict(item_group='Shrubs',stock_uom='Pcs',is_sales_item=1)},[dict(item_code='A',custom_bolt_enabled=1)],{}, {},'p','https://example.com')
        self.assertFalse(d['products']);self.assertEqual(len(d['excluded']),1)
if __name__=='__main__':unittest.main()
