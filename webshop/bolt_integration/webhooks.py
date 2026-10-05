"""Authenticated, durable Bolt webhook inbox. No sales/stock side effects.

Frappe validates dedicated API key/secret credentials using HTTP Basic before
calling the auth hook. The hook confines that identity to these exact routes.
"""
import json

import frappe
from webshop.bolt_integration.validation import EVENTS, MAX_BYTES, receipt_key, validate

SERVICE_USER = 'bolt-webhook@callusgardencentre.com'
PREFIX = '/api/method/webshop.bolt_integration.webhooks.'
PATHS = {PREFIX + name for name in (*EVENTS, 'health')}
RELEASE = 'bolt-inbox-v1'


def restrict_service_user():
    """Never allow the webhook API identity to use generic REST/RPC/Desk routes."""
    if frappe.session.user != SERVICE_USER:
        return
    request = frappe.request
    path = request.path
    authorization = frappe.get_request_header('Authorization', '')
    expected_method = 'GET' if path == PREFIX + 'health' else 'POST'
    cmd = frappe.form_dict.get('cmd')
    if (path not in PATHS or request.method != expected_method
            or not authorization.lower().startswith('basic ')
            or frappe.get_request_header('Frappe-Authorization-Source')
            or (cmd and cmd != path.removeprefix('/api/method/'))):
        raise frappe.PermissionError('This account is restricted to Bolt webhook receipt.')


def _response(code, error):
    frappe.local.response.http_status_code = code
    return {'ok': False, 'error': error}


def _settings():
    return frappe.get_single('Callus Bolt Settings')


def _authorize():
    if frappe.session.user != SERVICE_USER:
        raise frappe.PermissionError('Dedicated Bolt credentials are required.')
    restrict_service_user()


@frappe.whitelist(methods=['GET'])
def health():
    _authorize()
    settings = _settings()
    return {'ok': True, 'release': RELEASE, 'enabled': bool(settings.enabled),
            'environment': settings.environment, 'mode': 'sales_processing' if getattr(settings, 'process_orders', False) else 'capture_only',
            'provider_configured': bool((settings.provider_id or '').strip())}


def _receive(event):
    _authorize()
    settings = _settings()
    if not settings.enabled:
        return _response(503, 'receiver_disabled')
    if not settings.site_hostname or frappe.request.host.split(':')[0].lower() != settings.site_hostname.lower():
        return _response(503, 'site_binding_mismatch')
    request = frappe.request
    if request.mimetype != 'application/json':
        return _response(415, 'json_required')
    if request.content_length is not None and request.content_length > MAX_BYTES:
        return _response(413, 'payload_too_large')
    raw = request.get_data()
    if len(raw) > MAX_BYTES:
        return _response(413, 'payload_too_large')
    try:
        payload = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        provider, order, body, digest = validate(event, payload)
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        return _response(400, 'invalid_payload')
    configured = (settings.provider_id or '').strip()
    if configured and configured != provider:
        return _response(403, 'provider_not_allowed')
    key = receipt_key(event, provider, order, digest)
    if key and frappe.db.exists('Callus Bolt Event', key):
        return {'ok': True, 'received': True, 'duplicate': True, 'mode': 'capture_only'}
    doc = frappe.get_doc({
        'doctype': 'Callus Bolt Event', 'event_type': event, 'provider_id': provider,
        'bolt_order_id': order, 'order_reference': str(payload.get('order_reference_id') or ''),
        'payload': body, 'payload_hash': digest, 'environment': settings.environment,
        'provider_verified': int(bool(configured)), 'status': 'Captured',
        'is_test': int(provider == 'CALLUS-INTEGRATION-TEST'),
        'receipt_key': key,
    })
    frappe.db.savepoint('bolt_receipt')
    try:
        doc.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        frappe.db.rollback(save_point='bolt_receipt')
        if not key:
            raise
        return {'ok': True, 'received': True, 'duplicate': True, 'mode': 'capture_only'}
    # Frappe commits successful POST requests before returning HTTP 200. No enqueue
    # dependency: the receipt is durable even when workers are unavailable.
    return {'ok': True, 'received': True, 'duplicate': False, 'mode': 'capture_only'}


@frappe.whitelist(methods=['POST'])
def new_order(**kwargs):
    return _receive('new_order')


@frappe.whitelist(methods=['POST'])
def cancel_order(**kwargs):
    return _receive('cancel_order')


@frappe.whitelist(methods=['POST'])
def order_update(**kwargs):
    return _receive('order_update')


@frappe.whitelist(methods=['POST'])
def provider_status(**kwargs):
    return _receive('provider_status')


@frappe.whitelist(methods=['POST'])
def courier_details(**kwargs):
    return _receive('courier_details')
