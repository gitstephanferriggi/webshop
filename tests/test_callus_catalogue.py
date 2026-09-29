"""Read-only catalogue regression tests; no database, network or transactions."""
import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=(ROOT/'webshop/callus_storefront/data_script.py').read_text()
class Row(dict):
    __getattr__=dict.get
    __setattr__=dict.__setitem__

def run_catalogue(*,enabled=True,prices=None,stock=None,items=None,guest_hidden=False,product_code='A',login_required=False):
    today=datetime.date(2026,9,29)
    rows={
        'Website Item':[Row(name='W-A',item_code='A',web_item_name='Basil',item_group='Herbs',website_warehouse='Shop',website_image='/files/basil.jpg',description='Basil details',creation='2026-01-01')],
        'Item':items if items is not None else [Row(name='A',is_stock_item=1,stock_uom='Pcs')],
        'Item Price':prices if prices is not None else [Row(item_code='A',price_list_rate=3.5,currency='EUR',valid_from=None,valid_upto=None,uom='Pcs')],
        'Bin':stock if stock is not None else [Row(item_code='A',warehouse='Shop',actual_qty=10,reserved_qty=3)],
        'Item Group':[Row(name='Herbs',parent_item_group='Herbs & Vegetables')],
        'Sales Invoice':[Row(item_code='A',units=4)]}
    calls=[]
    def get_all(dt,**kw):
        calls.append((dt,kw))
        if dt=='Website Item':assert kw['filters']=={'published':1}
        if dt=='Item':assert kw['filters']['disabled']==0
        if dt=='Sales Invoice':assert kw['filters']['docstatus']==1 and kw['filters']['is_return']==0
        return rows[dt]
    utils=SimpleNamespace(getdate=lambda v=None:datetime.date.fromisoformat(str(v)) if v else today,add_days=lambda d,n:d+datetime.timedelta(days=n))
    frappe=SimpleNamespace(get_doc=lambda *args:Row(enabled=enabled,price_list='Retail',show_price=True,hide_price_for_guest=guest_hidden,login_required_to_view_products=login_required),get_all=get_all,utils=utils,form_dict=Row(item_code=product_code),session=Row(user='Guest'))
    data=Row();exec(SCRIPT,{'frappe':frappe,'data':data})
    return data,calls

class CatalogueTests(unittest.TestCase):
    def test_published_active_only_and_correct_warehouse(self):
        data,_=run_catalogue(stock=[Row(item_code='A',warehouse='Shop',actual_qty=4,reserved_qty=2),Row(item_code='A',warehouse='Other',actual_qty=999,reserved_qty=0)])
        self.assertEqual(data.catalogue[0]['quantity'],2)
        self.assertEqual(data.catalogue[0]['category'],'grow')
    def test_disabled_items_excluded(self):
        self.assertEqual(run_catalogue(items=[])[0].catalogue,[])
    def test_private_future_expired_and_wrong_uom_prices_ignored(self):
        def price(**kw):return Row(item_code='A',price_list_rate=99,currency='EUR',uom='Pcs',**kw)
        rows=[price(customer='Private Customer'),price(supplier='Supplier'),price(batch_no='Batch'),price(valid_from='2026-10-01'),price(valid_upto='2026-09-01'),Row(item_code='A',price_list_rate=25,currency='EUR',uom='Box'),Row(item_code='A',price_list_rate=3.5,currency='EUR',uom='Pcs')]
        p=run_catalogue(prices=rows)[0].catalogue[0]
        self.assertEqual(p['price'],3.5)
        self.assertNotIn('customer',p)
    def test_missing_price_is_not_free(self):
        self.assertIsNone(run_catalogue(prices=[])[0].catalogue[0]['price'])
    def test_guest_price_setting_respected(self):
        self.assertIsNone(run_catalogue(guest_hidden=True)[0].catalogue[0]['price'])
    def test_unavailable_when_reservations_exceed_stock(self):
        p=run_catalogue(stock=[Row(item_code='A',warehouse='Shop',actual_qty=2,reserved_qty=5)])[0].catalogue[0]
        self.assertFalse(p['available']);self.assertEqual(p['quantity'],0)
    def test_disabled_shop_returns_no_products(self):
        data,calls=run_catalogue(enabled=False)
        self.assertEqual(data.catalogue,[]);self.assertEqual(calls,[])
    def test_login_required_catalogue_is_not_public(self):
        self.assertEqual(run_catalogue(login_required=True)[0].catalogue,[])
    def test_sales_volume_not_exposed(self):
        p=run_catalogue()[0].catalogue[0]
        self.assertEqual(p['rank'],1);self.assertNotIn('units',p);self.assertNotIn('net_sales',p)
    def test_description_only_sent_for_requested_product(self):
        self.assertEqual(run_catalogue(product_code='')[0].catalogue[0]['description'],'')
        self.assertEqual(run_catalogue()[0].catalogue[0]['description'],'Basil details')
    def test_checkout_fails_closed(self):
        self.assertFalse(run_catalogue()[0].checkout_enabled)
    def test_all_page_exports_include_data_script_and_body(self):
        pages=list((ROOT/'webshop/builder_files/pages').glob('*/*.json'))
        count=0
        for path in pages:
            doc=json.loads(path.read_text())
            if not any(x.get('builder_script')=='callus-storefront-js' for x in doc.get('client_scripts',[])):continue
            count+=1
            self.assertEqual(doc['blocks'][0]['element'],'body')
            self.assertEqual(doc['page_data_script'],SCRIPT)
            self.assertNotIn('callusuat',path.read_text())
        self.assertEqual(count,15)
    def test_builder_script_types_and_no_legacy_transaction_calls(self):
        for suffix,kind in [('css','CSS'),('js','JavaScript')]:
            path=ROOT/f'webshop/builder_files/client_scripts/callus_storefront_{suffix}/callus_storefront_{suffix}.json'
            self.assertEqual(json.loads(path.read_text())['script_type'],kind)
        js=(ROOT/'webshop/public/callus/storefront.js').read_text()
        self.assertNotIn('get_item_price',js)  # Upstream helper calls get_party(), which may write records.
        self.assertNotIn('place_order',js)
        self.assertNotIn('Authorization',js)

if __name__=='__main__':unittest.main()
