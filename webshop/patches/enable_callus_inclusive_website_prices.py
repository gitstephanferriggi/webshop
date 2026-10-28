"""Initialise the new VAT policy without overwriting an explicit site choice."""
import frappe


def execute():
    existing = frappe.db.sql(
        "SELECT value FROM `tabSingles` WHERE doctype=%s AND field=%s",
        ("Callus Checkout Settings", "prices_include_vat"),
    )
    if not existing:
        frappe.db.set_single_value("Callus Checkout Settings", "prices_include_vat", 1)
        frappe.clear_document_cache("Callus Checkout Settings", "Callus Checkout Settings")
