"""Actual Frappe account lifecycle over WSGI; outgoing email intercepted locally."""
import json,secrets,sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
if len(sys.argv)!=2 or sys.argv[1] not in ('test_site','checkout.localhost'):
    raise SystemExit('Use an isolated test site only.')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import frappe,frappe.app
from werkzeug.test import Client
from werkzeug.wrappers import Response
site=sys.argv[1]
frappe.init(site=site,sites_path='.');frappe.connect();frappe.set_user('Administrator')
assert site=='test_site' or frappe.conf.db_port==13316
for dt,key,value in [('Website Settings','disable_signup',0),('Portal Settings','default_role','Customer'),('System Settings','enable_password_policy',1),('System Settings','minimum_password_score',2)]:
    frappe.db.set_single_value(dt,key,value)
frappe.db.commit();frappe.destroy()
frappe.app._site=site;frappe.app._sites_path='.'
client=Client(frappe.app.application,Response)
email='account-'+secrets.token_hex(5)+'@example.com';password=secrets.token_urlsafe(24)
checks=[];mails=[]
def call(method,data=None):
    r=client.open('/api/method/'+method,method='POST' if data is not None else 'GET',base_url='https://'+site,json=data,headers={'X-Forwarded-Proto':'https'})
    status=r.status_code;result=r.get_json();r.close();return status,result

def check(label,test):
    assert test,label
    checks.append(label)
with patch('frappe.sendmail',side_effect=lambda **kw:mails.append(kw)),patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected outbound request')):
    code,r=call('frappe.core.doctype.user.user.sign_up',dict(email=email,full_name='Account Fixture',redirect_to='/account-callus'))
    check('signup creates website account',code==200 and r['message'][0]==1)
    check('verification email uses original reset endpoint',bool(mails) and '/update-password?' in mails[-1]['args']['link'])
    key=parse_qs(urlsplit(mails[-1]['args']['link']).query)['key'][0]
    code,r=call('frappe.core.doctype.user.user.sign_up',dict(email=email,full_name='Other Name',redirect_to='/account-callus'))
    check('duplicate signup does not create another account',code==200 and r['message'][0]==0)
    code,r=call('login',dict(usr=email,pwd='incorrect-password'))
    check('wrong password is rejected',code==401)
    code,r=call('frappe.core.doctype.user.user.update_password',dict(key=key,new_password='123',logout_all_sessions=1))
    check('weak password is rejected',code==417)
    code,r=call('frappe.core.doctype.user.user.update_password',dict(key=key,new_password=password,logout_all_sessions=1))
    check('verification link sets password',code==200)
    code,r=call('frappe.auth.get_logged_user')
    check('verification establishes authenticated session',code==200 and r['message']==email)
    client=Client(frappe.app.application,Response)
    code,r=call('frappe.core.doctype.user.user.update_password',dict(key=key,new_password=secrets.token_urlsafe(24)))
    check('verification link cannot be reused',code==410)
    code,r=call('login',dict(usr=email,pwd=password))
    check('new password signs in',code==200 and r['message'] in ('Logged In','No App'))
    code,r=call('logout',{})
    check('logout succeeds',code==200)
    code,r=call('frappe.auth.get_logged_user')
    check('logout removes authenticated access',code in (401,403))
    code,r=call('frappe.core.doctype.user.user.reset_password',dict(user=email))
    check('password recovery issues email',code==200 and len(mails)>=2)
    resetkey=parse_qs(urlsplit(mails[-1]['args']['link']).query)['key'][0]
    code,r=call('frappe.core.doctype.user.user.reset_password',dict(user='missing-'+email))
    check('unknown recovery has same success status',code==200)
    code,r=call('frappe.core.doctype.user.user.update_password',dict(key=resetkey,new_password=secrets.token_urlsafe(24),logout_all_sessions=1))
    check('recovery link sets replacement password',code==200)
print(json.dumps({'passed':len(checks),'checks':checks,'email_delivery':'intercepted locally; no email sent'},indent=2))
