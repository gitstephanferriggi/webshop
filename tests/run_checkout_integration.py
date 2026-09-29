"""Run from a bench's sites folder: ../env/bin/python ../apps/webshop/tests/run_checkout_integration.py test_site.

Only explicitly designated test sites are accepted. Stripe requests are simulated.
"""
import sys
import unittest
from pathlib import Path

if len(sys.argv) != 2 or sys.argv[1] not in ('test_site','checkout.localhost'):
    raise SystemExit('Use an isolated test_site or checkout.localhost only.')
repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo));sys.path.insert(0,str(repo/'tests'))
import frappe
frappe.init(site=sys.argv[1],sites_path='.');frappe.connect();frappe.set_user('Administrator');frappe.flags.in_test=True
import checkout_integration
try:
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(checkout_integration))
finally:
    frappe.db.rollback();frappe.destroy()
sys.exit(not result.wasSuccessful())
