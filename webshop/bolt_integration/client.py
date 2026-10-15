"""Bolt's documented HMAC authentication; credentials never enter logs."""
import base64
import hashlib
import hmac
import json
import requests

BASE='https://node.bolt.eu/delivery-provider-pos'
# These commands document HTTP 200 without a JSON body and HTTP 304 when
# already in the requested state. Data-returning endpoints still require JSON.
EMPTY_OK_PATHS = {
    '/genericClient/' + name for name in (
        'acceptOrder', 'rejectOrder', 'markOrderAsReadyForPickup',
        'markOrderAsPickedUp', 'markOrderAsDelivered',
        'startAcceptingOrders', 'pauseOrders', 'updateProviderSchedule',
    )
}

def request(settings,path,payload):
    raw=json.dumps(payload,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    signature=base64.b64encode(hmac.new(settings.get_password('secret_key').encode(),raw,hashlib.sha256).digest()).decode()
    response=requests.post(BASE+path,data=raw,headers={'Content-Type':'application/json',
        'x-external-integrator-id':settings.integrator_id,'x-server-authorization-hmac-sha256':signature},timeout=45)
    if response.status_code == 304 and path in EMPTY_OK_PATHS:
        return {'unchanged': True}
    response.raise_for_status()
    if response.status_code == 200 and not response.content.strip() and (path in EMPTY_OK_PATHS or path == '/genericClient/markOrderWithItemsAsReadyForPickUp'):
        # Adjusted readiness still requires an independent final-basket readback.
        return {}
    data=response.json()
    if not isinstance(data, dict):
        raise ValueError('Unexpected Bolt response for ' + path)
    if data.get('code',0)!=0 or data.get('errors') or data.get('warnings'):
        # Do not dump raw requests, auth headers, or customer baskets.
        raise ValueError('Bolt rejected '+path+': '+str(data.get('message') or data.get('errors') or data.get('warnings'))[:500])
    return data.get('data',data)
