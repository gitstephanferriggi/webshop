import unittest
from types import SimpleNamespace
from webshop.callus_storefront.checkout_validation import checkout_id, normalise_request, cents, validate_session

class PaymentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.buyer=dict(first_name='Test',last_name='Buyer',email='BUYER@example.com',phone='+35699990000',address='1 Garden Street',town='Siggiewi',postcode='SGW 2600',country='Malta',delivery='collection')
    def test_client_prices_are_discarded(self):
        items,buyer=normalise_request([{'id':'BASIL','qty':2,'rate':0.01,'total':0.02}],self.buyer)
        self.assertEqual(items,[{'id':'BASIL','qty':2}]);self.assertEqual(buyer['email'],'buyer@example.com')
    def test_invalid_quantities(self):
        for qty in [0,-1,1.1,True,'2',100,float('nan')]:
            with self.subTest(qty=qty),self.assertRaises(ValueError):normalise_request([{'id':'A','qty':qty}],self.buyer)
    def test_duplicate_items_and_empty_basket(self):
        for items in [[],[{'id':'A','qty':1}]*2]:
            with self.assertRaises(ValueError):normalise_request(items,self.buyer)
    def test_address_and_country_are_required(self):
        for override in [{'country':'Italy'},{'address':''},{'email':'bad'},{'delivery':'free'},{'first_name':'Bad\nName'}]:
            with self.assertRaises(ValueError):normalise_request([{'id':'A','qty':1}],self.buyer|override)
    def test_capability_is_hashed_and_strict(self):
        self.assertNotEqual(checkout_id('a'*64),'a'*64)
        for token in [None,'a'*63,'../etc/passwd','G'*64]:
            with self.assertRaises(ValueError):checkout_id(token)
    def test_decimal_rounding(self):
        self.assertEqual(cents('10.005'),1001)
        for bad in [0,-1,'NaN','Infinity','not a number']:
            with self.assertRaises(ValueError):cents(bad)
    def test_redirect_and_mismatched_payment_not_authoritative(self):
        doc=SimpleNamespace(name='ref',stripe_session='cs_test_123',is_live=False,amount_minor=700)
        session=dict(id=doc.stripe_session,mode='payment',currency='eur',amount_total=700,client_reference_id='ref',livemode=False,metadata={'callus_checkout':'ref'},status='complete',payment_status='paid')
        self.assertTrue(validate_session(session,doc))
        for change in [{'amount_total':1},{'livemode':True},{'currency':'usd'},{'client_reference_id':'another'},{'metadata':{}},{'id':'other'}]:
            with self.assertRaises(ValueError):validate_session(session|change,doc)
        self.assertFalse(validate_session(session|{'payment_status':'unpaid'},doc))

    def test_webhook_hmac_requires_exact_payload_and_recent_timestamp(self):
        import hmac,hashlib
        from webshop.callus_storefront.checkout_validation import verify_webhook
        body=b'{"data":{"object":{"id":"cs_test"}}}'
        digest=hmac.new(b'whsec_fixture',b'1000.'+body,hashlib.sha256).hexdigest()
        signature='t=1000,v1='+digest
        self.assertEqual(verify_webhook(body,signature,'whsec_fixture',1001)['data']['object']['id'],'cs_test')
        for payload,header,now in [(body+b' ',signature,1001),(body,signature,1400),(body,'t=1000,v1=no',1001),(body,'bad',1001),(body,signature,600)]:
            with self.assertRaises(ValueError):verify_webhook(payload,header,'whsec_fixture',now)

if __name__=='__main__':unittest.main()
