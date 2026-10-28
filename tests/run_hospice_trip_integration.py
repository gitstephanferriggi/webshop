"""Only the isolated checkout database; no external network calls."""
import sys, unittest
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(repo),str(repo/'tests'),str(Path.home()/'.openclaw/workspace/bloominggarden-app')]
import frappe
frappe.init(site='checkout.localhost',sites_path='.')
frappe.connect()
if frappe.conf.db_port != 13316:raise SystemExit('Use the isolated checkout database on port 13316.')
frappe.set_user('Administrator');frappe.flags.in_test=True;frappe.clear_cache()
from hospice_trip_integration import HospiceTripTests
try:
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HospiceTripTests))
 raise SystemExit(0 if result.wasSuccessful() else 1)
finally:frappe.db.rollback();frappe.destroy()
