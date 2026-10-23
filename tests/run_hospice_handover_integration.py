"""Only the isolated checkout database; all external delivery is intercepted."""
import sys
import unittest
from pathlib import Path

if len(sys.argv) != 2 or sys.argv[1] not in ('test_site', 'checkout.localhost'):
    raise SystemExit('Use the isolated checkout test site only.')
repo=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(repo),str(repo/'tests')]
import frappe
frappe.init(site=sys.argv[1],sites_path='.')
frappe.connect()
if frappe.conf.db_port != 13316:
    raise SystemExit('Use the isolated checkout database on port 13316.')
frappe.set_user('Administrator');frappe.flags.in_test=True;frappe.clear_cache()
from webshop.callus_storefront.hospice_receipts import setup
setup();frappe.db.commit()
from hospice_handover_integration import SignedHandoverTests
try:
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SignedHandoverTests))
finally:
    frappe.db.rollback();frappe.destroy()
sys.exit(not result.wasSuccessful())
