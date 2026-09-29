"""Transport checks against Frappe's real WSGI application; Stripe is simulated."""
import hashlib
import hmac
import json
import secrets
import sys
import time
from pathlib import Path
from unittest.mock import patch

if len(sys.argv)!=2 or sys.argv[1] not in ('test_site','checkout.localhost'):
    raise SystemExit('Only an isolated test site is allowed.')
repo=Path(__file__).resolve().parents[1];sys.path.insert(0,str(repo));sys.path.insert(0,str(repo/'tests'))
import frappe
import frappe.app
from werkzeug.test import Client
from werkzeug.wrappers import Response
from checkout_integration import CheckoutIntegrationTests
from webshop.callus_storefront import checkout as api
site=sys.argv[1]
frappe.init(site=site,sites_path='.');frappe.connect();frappe.set_user('Administrator')
settings=frappe.get_single('Callus Checkout Settings');original=settings.site_url;settings.site_url='https://'+site;settings.save();frappe.db.commit();frappe.destroy()
frappe.app._site=site;frappe.app._sites_path='.'
case=CheckoutIntegrationTests();case.sessions={};case.refunds={};case.calls=[]
token=secrets.token_hex(32)
buyer=dict(first_name='HTTP',last_name='Guest',email='http-test@example.com',phone='+35699990000',address='1 Garden Street',town='Siggiewi',postcode='SGW 2600',country='Malta',delivery='collection')
client=Client(frappe.app.application,Response)
prefix='/api/method/webshop.callus_storefront.checkout.'
checks=[]
def call(method,body=None,verb='POST',headers=None):
    response=client.open(prefix+method,method=verb,base_url='https://'+site,json=body,headers={'X-Forwarded-Proto':'https'} | (headers or {}))
    data=response.get_json();response.close()
    return response.status_code,data
try:
    with patch.object(api,'_stripe',side_effect=case.stripe),patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected network call')):
        code,data=call('options',verb='GET');assert code==200 and data['message']['enabled'],(code,data);checks.append('guest options')
        code,data=call('pay',{'token':token},verb='GET');assert code>=400,(code,data);checks.append('GET cannot initiate payment')
        code,data=call('prepare',dict(token=token,items=[dict(id='CHECKOUT-BASIL',qty=2)],buyer=buyer));assert code==200,(code,data);order=data['message']['order'];checks.append('guest POST creates quote')
        code,data=call('pay',{'token':token});assert code==200 and data['message']['url'].startswith('https://checkout.stripe.com/'),(code,data);checks.append('guest POST creates session')
        code,data=call('status',{'token':token});assert code==200 and data['message']['status']=='Pending',(code,data);checks.append('unpaid remains pending')
        session=next(iter(case.sessions.values()));session.update(status='complete',payment_status='paid',payment_intent={'id':'pi_http_'+session['client_reference_id'][:16],'latest_charge':{'id':'ch_http','refunded':False}})
        event={'id':'evt_http','object':'event','type':'checkout.session.completed','data':{'object':{'metadata':session['metadata']}}}
        payload=json.dumps(event).encode();stamp=int(time.time());signature=hmac.new(b'whsec_local_fixture',str(stamp).encode()+b'.'+payload,hashlib.sha256).hexdigest()
        response=client.post(prefix+'webhook',base_url='https://'+site,data=payload,content_type='application/json',headers={'X-Forwarded-Proto':'https','Stripe-Signature':f't={stamp},v1={signature}'})
        assert response.status_code==200 and response.get_json()['message']['received'],response.get_json();response.close();checks.append('signed JSON webhook transport')
        code,data=call('status',{'token':token});assert code==200 and data['message']['status']=='Paid',(code,data);checks.append('guest sees reconciled payment')
        code,data=call('refund',{'checkout':session['client_reference_id']});assert code==403,(code,data);checks.append('guest refund denied')
        code,data=call('configure_stripe',{'site_url':'https://'+site});assert code==403,(code,data);checks.append('guest configuration denied')
    print(json.dumps({'passed':len(checks),'checks':checks},indent=2))
finally:
    frappe.init(site=site,sites_path='.');frappe.connect();frappe.set_user('Administrator')
    settings=frappe.get_single('Callus Checkout Settings');settings.site_url=original;settings.save();frappe.db.commit();frappe.destroy()
