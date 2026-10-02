"""Pure validation and receipt identities for Bolt Stores API webhooks."""
import hashlib
import json
import math

MAX_BYTES = 512 * 1024
EVENTS = ('new_order', 'cancel_order', 'order_update', 'provider_status', 'courier_details')


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def identifier(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('Invalid identifier')
    value = str(value)
    if not value.strip() or len(value) > 140 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid identifier')
    return value


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid non-negative number')


def validate(event, payload):
    if event not in EVENTS or not isinstance(payload, dict):
        raise ValueError('Expected a JSON object')
    if 'cmd' in payload:
        raise ValueError('Reserved field')
    provider = identifier(payload.get('provider_id'))
    order = ''
    if event != 'provider_status':
        order = identifier(payload.get('main_order_id' if event == 'order_update' else 'order_id'))
    if event in ('new_order', 'cancel_order', 'courier_details'):
        identifier(payload.get('order_reference_id'))
    if event == 'new_order':
        if payload.get('order_type') not in ('delivery', 'pickup', 'own_delivery'):
            raise ValueError('Invalid order type')
        if payload.get('payment_type') not in ('cash', 'card_online'):
            raise ValueError('Invalid payment type')
        for key in ('created_ts', 'due_ts'):
            number(payload.get(key))
        for key in ('created_datetime', 'due_datetime'):
            if not isinstance(payload.get(key), str) or not payload[key].strip():
                raise ValueError('Missing order datetime')
        if not isinstance(payload.get('customer'), dict):
            raise ValueError('Missing customer object')
        items = payload.get('items')
        if not isinstance(items, list) or not items or len(items) > 1000:
            raise ValueError('Invalid items')
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('Invalid item')
            identifier(item.get('sku'))
            number(item.get('qty'))
        price = payload.get('total_order_price')
        if not isinstance(price, dict):
            raise ValueError('Missing total price')
        number(price.get('value'))
        if not isinstance(price.get('currency'), str) or len(price['currency']) != 3:
            raise ValueError('Invalid currency')
    elif event == 'order_update':
        # Preserve new future event types, without interpreting them as sales instructions.
        identifier(payload.get('request_type'))
    elif event == 'provider_status':
        if payload.get('new_status') not in ('active', 'inactive'):
            raise ValueError('Invalid provider status')
    elif event == 'courier_details':
        if not isinstance(payload.get('courier'), dict):
            raise ValueError('Missing courier object')
    body = canonical(payload)
    return provider, order, body, hashlib.sha256(body.encode()).hexdigest()


def receipt_key(event, provider, order, digest):
    # Store-status messages have no event ID/timestamp. Preserve active->inactive->active.
    if event == 'provider_status':
        return None
    return hashlib.sha256(canonical([event, provider, order, digest]).encode()).hexdigest()
