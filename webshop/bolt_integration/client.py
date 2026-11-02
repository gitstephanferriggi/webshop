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
    if path.startswith('/pim/') or path in ('/genericClient/updateMenuQuantity', '/genericClient/acceptOrder', '/genericClient/startAcceptingOrders'):
        from webshop.bolt_integration.entitlement import require_new_work
        require_new_work(settings)
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
    # Callus explicitly approved this metadata tag; ERP item groups own VAT.
    # Retain every other warning and error as a publication blocker.
    if (path == '/pim/v1/products/import/status/retrieve'
            and getattr(settings, 'vat_tag', None) == 'bm_vat_0'):
        for scope in (data, data.get('data')):
            if not isinstance(scope, dict):
                continue
            warnings = scope.get('warnings') or []
            retained = [warning for warning in warnings if not (
                isinstance(warning, dict)
                and warning.get('message', '').startswith('VAT tag "bm_vat_0" not found for SKU ')
                and '\n' not in warning['message'] and '\r' not in warning['message'])]
            if len(retained) != len(warnings):
                scope['warnings'] = retained
                scope['acknowledged_vat_warning_count'] = len(warnings) - len(retained)
    if data.get('code',0)!=0 or data.get('errors') or data.get('warnings'):
        # Do not dump raw requests, auth headers, or customer baskets.
        raise ValueError('Bolt rejected '+path+': '+str(data.get('message') or data.get('errors') or data.get('warnings'))[:500])
    return data.get('data',data)
