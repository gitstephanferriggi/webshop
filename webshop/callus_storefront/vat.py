"""Shared VAT policy for Callus checkout and the standard website cart."""
import frappe
from frappe.utils import cint


def apply_website_vat(doc, settings=None, shop=None):
    """Mark website shelf prices as inclusive without changing their gross rates.

    Tax templates and Item Tax Templates still choose accounts/rates. Actual
    charges (e.g. a fixed shipping fee) remain outside the item price.
    """
    settings = settings or frappe.get_cached_doc("Callus Checkout Settings")
    shop = shop or frappe.get_cached_doc("Webshop Settings")
    if not cint(settings.get("enabled")):
        return False
    if doc.company != shop.company:
        return False
    value = settings.get("prices_include_vat")
    inclusive = 1 if value is None else cint(value)
    for tax in doc.get("taxes") or []:
        tax.included_in_print_rate = inclusive if tax.charge_type != "Actual" else 0
    return True


def validate_unpaid_checkout_vat(checkout, settings=None):
    """An older draft must not start a new payment using an obsolete VAT quote."""
    if checkout.status != "Draft" or checkout.stripe_session or checkout.stripe_request:
        return
    from copy import deepcopy
    order = frappe.get_doc("Sales Order", checkout.sales_order)
    expected = deepcopy(order)
    if not apply_website_vat(expected, settings=settings):
        return
    current = order.get("taxes") or []
    desired = expected.get("taxes") or []
    if any(tax.included_in_print_rate != target.included_in_print_rate
           and tax.charge_type != "Actual" and tax.tax_amount
           for tax, target in zip(current, desired)):
        frappe.throw("VAT settings changed since this basket was prepared. Please start a new checkout.")
