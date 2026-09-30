"""Guest checkout. Browser totals and Stripe redirect parameters are never authoritative.

Each attempt has a 256-bit browser-held capability. Only its hash is stored.
ERPNext prices the order; Stripe hosts all card entry. Payment reconciliation uses
Stripe's authenticated API, including when a signed webhook requests a refresh.
"""
import json
import hashlib
import time
from contextlib import contextmanager
from functools import wraps
from urllib.parse import urlparse

import frappe
import requests
from frappe.rate_limiter import rate_limit
from frappe.utils import get_url, nowdate

from webshop.callus_storefront.checkout_validation import (
    cents, checkout_id, fingerprint, normalise_request, validate_session, verify_webhook,
)

PREFIX = "webshop.callus_storefront.checkout."


def fail(message):
    frappe.throw(message)


def _internal_erp(fn):
    """Elevate only private, server-constructed ERP operations; restore the caller.

    ERPNext's pricing internals check Item permissions even when the parent
    order ignores permissions. No user-provided document is accepted here.
    """
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = frappe.session.user
        original_session = frappe._dict(frappe.local.session)
        original_form = frappe.local.form_dict
        try:
            frappe.set_user("Administrator")
            return fn(*args, **kwargs)
        finally:
            frappe.set_user(user)
            frappe.local.session.update(original_session)
            frappe.local.form_dict = original_form
    return wrapped


def _settings():
    return frappe.get_single("Callus Checkout Settings")


def _gateway(settings, verify_webhook=True):
    shop = frappe.get_cached_doc("Webshop Settings")
    if not shop.enabled or not settings.enabled:
        fail("Online payment is not available yet. Please contact the shop.")
    if not settings.site_url or settings.site_url.rstrip("/") != get_url().rstrip("/"):
        fail("Checkout is not configured for this website.")
    if urlparse(settings.site_url).scheme != "https" and not frappe.flags.in_test:
        fail("Checkout requires a secure website address.")
    if shop.login_required_to_view_products or shop.hide_price_for_guest or not shop.show_price:
        fail("Guest checkout is not enabled for this catalogue.")
    account = frappe.get_doc("Payment Gateway Account", shop.payment_gateway_account)
    gateway = frappe.get_doc("Payment Gateway", account.payment_gateway)
    if (gateway.gateway_settings != "Stripe Settings"
            or gateway.gateway_controller != settings.stripe_settings or account.currency != "EUR"):
        fail("A matching Stripe EUR payment gateway must be configured.")
    ledger = frappe.get_doc("Account", account.payment_account)
    if ledger.company != shop.company or ledger.account_currency != "EUR" or ledger.is_group or ledger.disabled:
        fail("The Stripe clearing account must belong to the shop and use EUR.")
    stripe_doc = frappe.get_doc("Stripe Settings", settings.stripe_settings)
    key = stripe_doc.get_password("secret_key")
    live = key.startswith(("sk_live_", "rk_live_"))
    if not (live or key.startswith(("sk_test_", "rk_test_"))):
        fail("Stripe credentials are not configured.")
    if live and not settings.allow_live_payments:
        fail("Live payments have not been enabled for this site.")
    if bool(stripe_doc.publishable_key.startswith("pk_live_")) != live:
        fail("Stripe public and secret keys use different modes.")
    if verify_webhook and (not settings.webhook_endpoint or not settings.get_password("webhook_secret", raise_exception=False)):
        fail("Stripe payment confirmation is not configured yet.")
    return shop, account, live


def _stripe(checkout, method, path, data=None, idempotency=None):
    key = frappe.get_doc("Stripe Settings", checkout.stripe_settings).get_password("secret_key")
    if key.startswith(("sk_live_", "rk_live_")) != bool(checkout.is_live):
        fail("Stripe mode changed. Restore the original mode to reconcile this order.")
    headers = {"Stripe-Version": "2024-06-20"}
    if idempotency:
        headers["Idempotency-Key"] = "callus-" + checkout.name + "-" + idempotency
    try:
        response = requests.request(method, "https://api.stripe.com/v1/" + path,
            auth=(key, ""), headers=headers, data=data if method == "POST" else None,
            params=data if method == "GET" else None, timeout=(5, 30), allow_redirects=False)
        if response.status_code >= 300:
            fail("Stripe could not complete this request. Please retry or contact the shop with your order reference.")
        return response.json()
    except requests.RequestException:
        fail("Stripe is temporarily unavailable. Please retry; your checkout reference is preserved.")


@contextmanager
def _locked(name):
    # A lock extends across deliberate commits around remote API calls. Database
    # transactions alone cannot protect an external Stripe side effect.
    with frappe.cache.lock("callus-checkout:" + name, timeout=180, blocking_timeout=5):
        yield


def _save(doc):
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()


def _doc(token):
    try:
        name = checkout_id(token)
    except ValueError as e:
        fail(str(e))
    if not frappe.db.exists("Callus Checkout", name):
        fail("This checkout could not be found. Please return to your basket.")
    return frappe.get_doc("Callus Checkout", name)


def _public(doc):
    return {"status": doc.status, "order": doc.sales_order,
            "summary": json.loads(doc.summary), "is_live": bool(doc.is_live),
            "expires_at": doc.expires_at}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def options():
    try:
        settings = _settings()
        _, _, live = _gateway(settings)
        return {"enabled": True, "delivery": bool(settings.delivery_rule), "is_live": live}
    except frappe.ValidationError:
        frappe.clear_messages()
        return {"enabled": False, "delivery": False}


def _stock(items, lock=False):
    """Recheck publication, sale eligibility and stock at both quote and submit."""
    result = []
    for row in items:
        item = frappe.get_cached_doc("Item", row["id"])
        web = frappe.db.get_value("Website Item", {"item_code":item.name,"published":1},
                                  ["name","website_warehouse"], as_dict=True)
        if not web or item.disabled or not item.is_sales_item or item.has_variants:
            fail("An item is no longer available. Please review your basket.")
        warehouse = web.website_warehouse
        if item.is_stock_item:
            stock = frappe.db.sql("SELECT actual_qty, reserved_qty FROM `tabBin` WHERE item_code=%s AND warehouse=%s"
                + (" FOR UPDATE" if lock else ""), (item.name, warehouse), as_dict=True)
            available = (stock[0].actual_qty - stock[0].reserved_qty) if stock else 0
            if available < row["qty"]:
                fail("There is not enough stock for " + item.item_name + ". Please review your basket.")
        result.append({"item_code":item.name,"qty":row["qty"],"uom":item.stock_uom,
                       "conversion_factor":1,"warehouse":warehouse,"delivery_date":nowdate()})
    return result


@_internal_erp
def _new_order(doc, items, buyer, shop, settings):
    from frappe.utils.nestedset import get_root_of
    from erpnext.accounts.party import set_taxes
    name = buyer["first_name"] + " " + buyer["last_name"]
    customer = frappe.get_doc({"doctype":"Customer","customer_name":name,
        "customer_type":"Individual","customer_group":shop.default_customer_group,
        "territory":get_root_of("Territory")}).insert(ignore_permissions=True, set_name="WEB-" + doc.name[:20])
    # Never attach an anonymous checkout to a customer/account based only on email.
    address = frappe.get_doc({"doctype":"Address","address_title":name,"address_type":"Billing",
        "address_line1":buyer["address"],"city":buyer["town"],"pincode":buyer["postcode"],
        "country":"Malta","email_id":buyer["email"],"phone":buyer["phone"],
        "links":[{"link_doctype":"Customer","link_name":customer.name}]}).insert(ignore_permissions=True)
    contact = frappe.get_doc({"doctype":"Contact","first_name":buyer["first_name"],"last_name":buyer["last_name"],
        "email_ids":[{"email_id":buyer["email"],"is_primary":1}],
        "phone_nos":[{"phone":buyer["phone"],"is_primary_mobile_no":1}],
        "links":[{"link_doctype":"Customer","link_name":customer.name}]}).insert(ignore_permissions=True)
    order = frappe.get_doc({"doctype":"Sales Order","company":shop.company,"customer":customer.name,
        "order_type":"Sales","transaction_date":nowdate(),"delivery_date":nowdate(),
        "selling_price_list":shop.price_list,"currency":"EUR","customer_address":address.name,
        "shipping_address_name":address.name if buyer["delivery"] == "delivery" else None,
        "contact_person":contact.name,"contact_email":buyer["email"],"contact_mobile":buyer["phone"],
        "items":_stock(items),"remarks":"Website " + buyer["delivery"] + "; checkout " + doc.name[:12]})
    order.flags.ignore_permissions = True
    order.run_method("set_missing_values")
    order.taxes_and_charges = set_taxes(customer.name, "Customer", nowdate(), shop.company,
        customer_group=shop.default_customer_group, tax_category=order.tax_category,
        billing_address=address.name, shipping_address=order.shipping_address_name, use_for_shopping_cart=1)
    order.set("taxes", [])
    order.append_taxes_from_master()
    order.append_taxes_from_item_tax_template()
    if buyer["delivery"] == "delivery":
        if not settings.delivery_rule:
            fail("Delivery is not available online yet. Please choose collection.")
        order.shipping_rule = settings.delivery_rule
    order.run_method("calculate_taxes_and_totals")
    order.insert(ignore_permissions=True)
    if order.currency != "EUR" or any(x.rate <= 0 for x in order.items):
        fail("One of these products needs a price confirmed by the shop.")
    total = order.rounded_total or order.grand_total
    amount = cents(total)
    if amount < 50 or amount > cents(settings.maximum_order_total):
        fail("This order is outside the online payment limit. Please contact the shop.")
    doc.customer, doc.sales_order, doc.amount_minor = customer.name, order.name, amount
    delivery_fee = 0
    if order.shipping_rule:
        rule = frappe.get_cached_doc("Shipping Rule", order.shipping_rule)
        delivery_fee = sum(row.tax_amount for row in order.taxes
            if row.charge_type == "Actual" and row.account_head == rule.account and row.description == rule.label)
    doc.summary = json.dumps({"currency":"EUR","total":amount/100,"delivery_fee":delivery_fee,
        "net_total":order.net_total,"taxes_and_charges":order.total_taxes_and_charges,
        "fulfilment":buyer["delivery"],
        "items":[{"id":x.item_code,"name":x.item_name,"qty":x.qty,"amount":x.amount} for x in order.items]})


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=60)
def prepare(token, items, buyer):
    try:
        name = checkout_id(token)
        items, buyer = normalise_request(frappe.parse_json(items), frappe.parse_json(buyer))
    except (ValueError, TypeError) as e:
        fail(str(e))
    digest = fingerprint(items, buyer)
    with _locked(name):
        if frappe.db.exists("Callus Checkout", name):
            doc = frappe.get_doc("Callus Checkout", name)
            if doc.request_hash != digest:
                fail("Your basket changed. Please start a new checkout.")
            return _public(doc)
        settings = _settings()
        shop, account, live = _gateway(settings)
        if buyer["delivery"] == "delivery" and not settings.delivery_rule:
            fail("Please choose collection; delivery is not configured yet.")
        doc = frappe.get_doc({"doctype":"Callus Checkout","status":"Draft","request_hash":digest,
            "buyer":json.dumps(buyer),"basket":json.dumps(items),"expires_at":int(time.time())+1800,
            "stripe_settings":settings.stripe_settings,"payment_account":account.payment_account,"is_live":int(live)})
        doc.name = name
        _new_order(doc, items, buyer, shop, settings)
        doc.insert(ignore_permissions=True, set_name=name)
        frappe.db.commit()
        return _public(doc)


@_internal_erp
def _submit_order(doc, order):
    if order.docstatus == 0:
        _stock(json.loads(doc.basket), lock=True)
        order.flags.ignore_permissions = True
        order.submit()
        if cents(order.rounded_total or order.grand_total) != doc.amount_minor:
            fail("The order total changed. Please review your basket again.")
    elif order.docstatus != 1:
        fail("This order is no longer payable.")


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=60)
def pay(token):
    doc = _doc(token)
    with _locked(doc.name):
        doc.reload()
        settings = _settings()
        _gateway(settings)
        if doc.stripe_session:
            _sync(doc)
            if doc.status == "Pending":
                return {"url":doc.checkout_url}
            return _public(doc)
        if doc.status not in ("Draft", "Pending") or (doc.status == "Draft" and doc.expires_at < time.time()):
            fail("This checkout expired. Please return to your basket.")
        order = frappe.get_doc("Sales Order", doc.sales_order)
        _submit_order(doc, order)
        doc.status = "Pending"
        # Persist the order before creating a remotely payable session. A timeout
        # can be retried with exactly the same Stripe idempotency key and data.
        _save(doc)
        body = {"mode":"payment","payment_method_types[0]":"card",
            "client_reference_id":doc.name,"metadata[callus_checkout]":doc.name,
            "payment_intent_data[metadata][callus_checkout]":doc.name,
            "customer_email":json.loads(doc.buyer)["email"],
            "line_items[0][price_data][currency]":"eur",
            "line_items[0][price_data][unit_amount]":doc.amount_minor,
            "line_items[0][price_data][product_data][name]":"Callus order " + doc.sales_order,
            "line_items[0][quantity]":1,
            "success_url":settings.site_url.rstrip("/")+"/checkout?payment=returned",
            "cancel_url":settings.site_url.rstrip("/")+"/checkout?payment=cancelled",
            "expires_at":doc.expires_at + 1800}
        if doc.stripe_request:
            body = json.loads(doc.stripe_request)
        else:
            doc.stripe_request = json.dumps(body)
            _save(doc)
        session = _stripe(doc,"POST","checkout/sessions",body,"session-v1")
        doc.stripe_session = session["id"]
        validate_session(session, doc)
        if urlparse(session.get("url", "")).hostname != "checkout.stripe.com":
            fail("Stripe returned an unexpected payment address.")
        doc.checkout_url = session["url"]
        _save(doc)
        return {"url":doc.checkout_url}


@_internal_erp
def _record_payment(doc, session):
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
    from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
    if doc.payment_entry:
        return
    order = frappe.get_doc("Sales Order", doc.sales_order)
    if order.docstatus != 1 or cents(order.rounded_total or order.grand_total) != doc.amount_minor:
        fail("The paid order needs a staff review before reconciliation.")
    intent = session["payment_intent"]
    intent = intent["id"] if isinstance(intent, dict) else intent
    if not intent or (doc.payment_intent and intent != doc.payment_intent):
        fail("Payment reference mismatch.")
    invoice = make_sales_invoice(order.name, ignore_permissions=True)
    invoice.update_stock = 0  # Fulfilment is a separate staff action.
    invoice.insert(ignore_permissions=True)
    if cents(invoice.rounded_total or invoice.grand_total) != doc.amount_minor:
        fail("The paid invoice total needs a staff review.")
    # Set only after Stripe session/payment validation, never from a customer group.
    invoice.flags.callus_verified_checkout = doc.name
    invoice.submit()
    pe = get_payment_entry("Sales Invoice", invoice.name, bank_account=doc.payment_account,
        bank_amount=doc.amount_minor/100)
    if pe.paid_from_account_currency != "EUR" or pe.paid_to_account_currency != "EUR":
        fail("Payment reconciliation requires EUR accounts.")
    pe.reference_no, pe.reference_date = intent, nowdate()
    pe.flags.ignore_permissions = True
    pe.insert(ignore_permissions=True)
    pe.submit()
    doc.sales_invoice = invoice.name
    doc.payment_entry, doc.payment_intent, doc.status = pe.name, intent, "Paid"


def _can_refund(doc):
    order = frappe.get_doc("Sales Order", doc.sales_order)
    if order.per_delivered:
        fail("A fulfilled order requires the normal product-return workflow.")
    invoice = frappe.get_doc("Sales Invoice", doc.sales_invoice)
    if invoice.docstatus != 1 or invoice.outstanding_amount or invoice.update_stock:
        fail("This invoice needs a staff review before refunding.")
    if frappe.db.exists("Sales Invoice", {"return_against":invoice.name,"docstatus":1}):
        fail("A credit note already exists; reconcile it before refunding.")
    return order, invoice


@_internal_erp
def _record_refund(doc, refund_id):
    """Credit note + outward Payment Entry preserve the original payment trail."""
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
    if doc.refund_entry:
        return
    order, invoice = _can_refund(doc)
    credit = make_sales_return(invoice.name)
    credit.update_stock = 0
    credit.insert(ignore_permissions=True)
    if cents(abs(credit.rounded_total or credit.grand_total)) != doc.amount_minor:
        fail("The credit note total needs a staff review.")
    credit.submit()
    refund = get_payment_entry("Sales Invoice", credit.name,
        bank_account=doc.payment_account, bank_amount=doc.amount_minor/100)
    refund.reference_no, refund.reference_date = refund_id, nowdate()
    refund.insert(ignore_permissions=True)
    refund.submit()
    order.reload()
    order.update_status("Closed")
    doc.credit_note, doc.refund_entry = credit.name, refund.name
    doc.stripe_refund, doc.status = refund_id, "Refunded"


def _sync(doc):
    if not doc.stripe_session:
        if doc.status == "Pending" and doc.stripe_request:
            session = _stripe(doc,"POST","checkout/sessions",json.loads(doc.stripe_request),"session-v1")
            doc.stripe_session = session["id"]
            validate_session(session, doc)
            if session.get("url"):
                doc.checkout_url = session["url"]
            _save(doc)
        else:
            return
    session = _stripe(doc,"GET","checkout/sessions/" + doc.stripe_session,
                      {"expand[]":"payment_intent.latest_charge"})
    try:
        paid = validate_session(session, doc)
    except ValueError as e:
        fail(str(e))
    if paid:
        _record_payment(doc, session)
        intent = session.get("payment_intent")
        charge = intent.get("latest_charge") if isinstance(intent,dict) else None
        if isinstance(charge, dict) and charge.get("refunded"):
            refunds = _stripe(doc,"GET","refunds",{"payment_intent":doc.payment_intent,"limit":100})["data"]
            complete = [r for r in refunds if r["status"] == "succeeded"]
            if sum(r["amount"] for r in complete) == doc.amount_minor:
                _record_refund(doc, complete[0]["id"])
        if doc.stripe_refund and doc.status == "Refund Pending":
            refund = _stripe(doc,"GET","refunds/" + doc.stripe_refund)
            if refund["status"] == "succeeded" and refund["amount"] == doc.amount_minor and refund["payment_intent"] == doc.payment_intent:
                _record_refund(doc, refund["id"])
            elif refund["status"] in ("failed","canceled"):
                doc.status = "Paid"
    elif session.get("status") == "expired" and doc.status == "Pending":
        order = frappe.get_doc("Sales Order", doc.sales_order)
        order.flags.ignore_permissions = True
        if order.docstatus == 1:
            order.cancel()
        doc.status = "Expired"
    _save(doc)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=40, seconds=60)
def status(token):
    doc = _doc(token)
    with _locked(doc.name):
        doc.reload()
        _sync(doc)
        return _public(doc)


@frappe.whitelist(methods=["POST"])
def refund(checkout):
    if frappe.session.user == "Guest" or "System Manager" not in frappe.get_roles():
        frappe.throw("Only a System Manager can refund an order.", frappe.PermissionError)
    with _locked(checkout):
        doc = frappe.get_doc("Callus Checkout", checkout)
        _sync(doc)
        if doc.status == "Refunded":
            return _public(doc)
        if doc.status != "Paid":
            fail("Only a confirmed paid order can be refunded.")
        _can_refund(doc)
        result = _stripe(doc,"POST","refunds",{"payment_intent":doc.payment_intent,
            "amount":doc.amount_minor,"metadata[callus_checkout]":doc.name},"full-refund-v1")
        doc.stripe_refund, doc.status = result["id"], "Refund Pending"
        _save(doc)
        _sync(doc)
        return _public(doc)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=120, seconds=60)
def webhook():
    settings = _settings()
    secret = settings.get_password("webhook_secret", raise_exception=False)
    if not secret:
        fail("Webhook signing is not configured.")
    try:
        event = verify_webhook(frappe.request.get_data(),
            frappe.get_request_header("Stripe-Signature"), secret, time.time())
    except ValueError:
        frappe.local.response.http_status_code = 400
        return {"received":False}
    obj = event["data"]["object"]
    name = obj.get("metadata", {}).get("callus_checkout")
    if not name and obj.get("payment_intent"):
        name = frappe.db.get_value("Callus Checkout", {"payment_intent":obj["payment_intent"]}, "name")
    if name and frappe.db.exists("Callus Checkout", name):
        with _locked(name):
            _sync(frappe.get_doc("Callus Checkout", name))
    return {"received":True}


def reconcile_pending():
    """Recovery for closed tabs, missed webhooks, and pending refunds."""
    for name in frappe.get_all("Callus Checkout", filters={"status":["in",["Pending","Refund Pending"]]},
                               pluck="name", limit_page_length=100, order_by="modified asc"):
        try:
            with _locked(name):
                _sync(frappe.get_doc("Callus Checkout", name))
        except Exception:
            frappe.db.rollback()
            # Never log Stripe HTTP objects, keys, or buyer payloads.
            frappe.log_error(title="Callus payment reconciliation requires review", message="Checkout " + name)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=15, seconds=60)
def cancel(token):
    doc = _doc(token)
    with _locked(doc.name):
        doc.reload()
        if doc.stripe_session:
            _sync(doc)
            if doc.status == "Pending":
                _stripe(doc,"POST","checkout/sessions/" + doc.stripe_session + "/expire",{},"expire-v1")
                _sync(doc)
        elif doc.status in ("Draft","Pending"):
            if doc.status == "Pending":
                # A timed-out creation might already be payable at Stripe.
                fail("Payment setup is still being recovered. Resume payment before starting a new order.")
            doc.status = "Expired"
            _save(doc)
        return _public(doc)


@frappe.whitelist(methods=["POST"])
def configure_stripe(site_url, allow_live_payments=0):
    """Explicit site-admin action; never called by migrations or public pages.

    Reuses this site's protected Stripe Settings. Adds a separate webhook for
    this origin without editing any other site's endpoint or exposing secrets.
    """
    if frappe.session.user == "Guest" or "System Manager" not in frappe.get_roles():
        frappe.throw("Only a System Manager can configure checkout.", frappe.PermissionError)
    if site_url.rstrip("/") != get_url().rstrip("/"):
        fail("Use this site's exact URL.")
    settings = _settings()
    shop = frappe.get_cached_doc("Webshop Settings")
    account = frappe.get_doc("Payment Gateway Account", shop.payment_gateway_account)
    gateway = frappe.get_doc("Payment Gateway", account.payment_gateway)
    settings.update({"site_url":site_url.rstrip("/"),"stripe_settings":gateway.gateway_controller,
        "allow_live_payments":int(str(allow_live_payments) == "1"),"enabled":1})
    _, _, live = _gateway(settings, verify_webhook=False)
    remote = frappe._dict(name=hashlib.sha256((site_url+str(live)).encode()).hexdigest(),
        stripe_settings=settings.stripe_settings, is_live=int(live))
    stripe_account = _stripe(remote,"GET","account")
    if live and not stripe_account.get("charges_enabled"):
        fail("Stripe has not enabled charges for this account.")
    url = site_url.rstrip("/") + "/api/method/" + PREFIX + "webhook"
    if settings.webhook_endpoint and settings.get_password("webhook_secret",raise_exception=False):
        endpoint = _stripe(remote,"GET","webhook_endpoints/" + settings.webhook_endpoint)
        if endpoint.get("url") != url or endpoint.get("status") != "enabled" or bool(endpoint.get("livemode")) != live:
            fail("The saved Stripe webhook belongs to another URL or mode, or is disabled. Configure a separate endpoint for this site.")
    else:
        body={"url":url,"api_version":"2024-06-20","description":"Callus checkout at "+site_url}
        for i,event in enumerate(["checkout.session.completed","checkout.session.expired","charge.refunded","refund.updated"]):
            body[f"enabled_events[{i}]"]=event
        endpoint = _stripe(remote,"POST","webhook_endpoints",body,"webhook-v1")
        settings.webhook_endpoint, settings.webhook_secret = endpoint["id"], endpoint["secret"]
    settings.save(ignore_permissions=True)
    frappe.db.commit()
    return {"enabled":True,"is_live":live,"webhook_endpoint":settings.webhook_endpoint,
            "delivery":bool(settings.delivery_rule),"site_url":settings.site_url}
