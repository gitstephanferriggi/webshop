"""Run from an isolated bench's sites directory, after migration.

Usage: ../env/bin/python /path/to/webshop/tests/run_hospice_integration.py checkout.localhost
Stripe HTTP and email delivery are intercepted by the tests.
"""
import sys
import unittest
from pathlib import Path

if len(sys.argv) != 2 or sys.argv[1] not in ('test_site', 'checkout.localhost'):
    raise SystemExit('Use an isolated test_site or checkout.localhost only.')
repo = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(repo), str(repo / 'tests')]
import frappe
frappe.init(site=sys.argv[1], sites_path='.')
frappe.connect()
if frappe.conf.db_port != 13316:
    raise SystemExit('Use the isolated checkout database on port 13316.')
frappe.set_user('Administrator')
frappe.flags.in_test = True
from hospice_integration import HospiceIntegrationTests
try:
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(HospiceIntegrationTests))
finally:
    frappe.db.rollback()
    frappe.destroy()
sys.exit(not result.wasSuccessful())
