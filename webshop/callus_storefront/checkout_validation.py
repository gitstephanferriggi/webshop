"""Pure validation shared by the payment boundary and regression tests."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def checkout_id(token):
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
        raise ValueError("Invalid checkout reference. Please return to your basket.")
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_request(items, buyer):
    if not isinstance(items, list) or not 1 <= len(items) <= 30:
        raise ValueError("Choose between 1 and 30 different products.")
    result = []
    seen = set()
    for row in items:
        if not isinstance(row, dict):
            raise ValueError("Invalid basket.")
        code, qty = row.get("id"), row.get("qty")
        if not isinstance(code, str) or not code or len(code) > 140 or code in seen:
            raise ValueError("Invalid or duplicate product in basket.")
        if type(qty) is not int or not 1 <= qty <= 99:
            raise ValueError("Quantities must be whole numbers between 1 and 99.")
        seen.add(code)
        result.append({"id": code, "qty": qty})
    if not isinstance(buyer, dict):
        raise ValueError("Enter your contact details.")
    clean = {}
    for field, maximum in {"first_name":80,"last_name":80,"email":140,"phone":25,
                           "address":140,"town":80,"postcode":12}.items():
        value = buyer.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c)<32 for c in value):
            raise ValueError("Please check your " + field.replace("_", " ") + ".")
        clean[field] = value.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean["email"]):
        raise ValueError("Enter a valid email address.")
    if not re.fullmatch(r"[+()0-9 .-]{8,25}", clean["phone"]):
        raise ValueError("Enter a valid phone number.")
    clean["email"] = clean["email"].lower()
    clean["country"] = "Malta"
    if buyer.get("country") != "Malta" or buyer.get("delivery") not in ("collection", "delivery"):
        raise ValueError("Choose collection or delivery in Malta.")
    clean["delivery"] = buyer["delivery"]
    return sorted(result, key=lambda x:x["id"]), clean


def fingerprint(items, buyer):
    return hashlib.sha256(json.dumps([items, buyer], sort_keys=True).encode()).hexdigest()


def cents(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise ValueError("The order total must be positive.")
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid order total.") from None


def validate_session(session, checkout):
    """Never trust a redirect, webhook body or client-supplied paid flag."""
    expected = {
        "id": checkout.stripe_session,
        "mode": "payment",
        "currency": "eur",
        "amount_total": checkout.amount_minor,
        "client_reference_id": checkout.name,
        "livemode": bool(checkout.is_live),
    }
    if any(session.get(k) != v for k,v in expected.items()):
        raise ValueError("Stripe session does not match this order.")
    if session.get("metadata", {}).get("callus_checkout") != checkout.name:
        raise ValueError("Stripe order reference does not match.")
    return session.get("payment_status") == "paid" and session.get("status") == "complete"


def verify_webhook(payload, signature, secret, now):
    """Verify Stripe's timestamp + v1 HMAC over the unmodified request bytes."""
    import hmac
    if not isinstance(payload, bytes) or len(payload) > 1_048_576 or not signature or not secret:
        raise ValueError("Invalid webhook.")
    try:
        parts = [part.split("=", 1) for part in signature.split(",")]
        stamps = [value for key,value in parts if key == "t"]
        signatures = [value for key,value in parts if key == "v1"]
        if len(stamps) != 1 or abs(now - int(stamps[0])) > 300:
            raise ValueError("Expired webhook.")
        digest = hmac.new(secret.encode(), stamps[0].encode() + b"." + payload, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(digest, value) for value in signatures):
            raise ValueError("Invalid webhook signature.")
        event = json.loads(payload)
        if not isinstance(event, dict) or not isinstance(event.get("data", {}).get("object"), dict):
            raise ValueError("Invalid event.")
        return event
    except (TypeError, KeyError, AttributeError, UnicodeError):
        raise ValueError("Invalid webhook.") from None
