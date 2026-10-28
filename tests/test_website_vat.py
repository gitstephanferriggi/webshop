"""Isolated policy tests; real tax calculations are in checkout_integration.py."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class Doc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class WebsiteVATTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / 'webshop/callus_storefront/vat.py'
        tree = ast.parse(path.read_text())
        env = {'cint': lambda x: int(x or 0)}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[]), str(path), 'exec'), env)
        self.apply = env['apply_website_vat']
        self.settings = Doc(enabled=1, prices_include_vat=1)
        self.shop = Doc(company='Shop', price_list='Shelf')
        self.order = Doc(company='Shop', selling_price_list='Shelf', taxes=[
            Doc(charge_type='On Net Total', included_in_print_rate=0, rate=18),
            Doc(charge_type='On Net Total', included_in_print_rate=0, rate=5),
            Doc(charge_type='On Net Total', included_in_print_rate=0, rate=0),
            Doc(charge_type='Actual', included_in_print_rate=1, tax_amount=5),
        ])

    def test_item_vat_is_extracted_shipping_fee_is_separate(self):
        self.assertTrue(self.apply(self.order, self.settings, self.shop))
        self.assertEqual([t.included_in_print_rate for t in self.order.taxes], [1, 1, 1, 0])
        self.assertEqual([t.rate for t in self.order.taxes[:3]], [18, 5, 0])
        self.assertEqual(self.order.taxes[3].tax_amount, 5)

    def test_existing_single_without_new_field_uses_inclusive_policy(self):
        del self.settings.prices_include_vat
        self.apply(self.order, self.settings, self.shop)
        self.assertEqual(self.order.taxes[0].included_in_print_rate, 1)

    def test_explicit_exclusive_configuration_is_respected(self):
        self.settings.prices_include_vat = 0
        self.apply(self.order, self.settings, self.shop)
        self.assertEqual(self.order.taxes[0].included_in_print_rate, 0)

    def test_other_company_is_not_overridden(self):
        self.order.company = 'Other'
        self.assertFalse(self.apply(self.order, self.settings, self.shop))
        self.assertEqual(self.order.taxes[0].included_in_print_rate, 0)

    def test_customer_specific_price_list_keeps_website_vat_policy(self):
        self.order.selling_price_list = 'Customer negotiated prices'
        self.assertTrue(self.apply(self.order, self.settings, self.shop))
        self.assertEqual(self.order.taxes[0].included_in_print_rate, 1)

    def test_disabled_callus_checkout_does_not_change_community_webshop(self):
        self.settings.enabled = 0
        self.assertFalse(self.apply(self.order, self.settings, self.shop))
        self.assertEqual(self.order.taxes[0].included_in_print_rate, 0)


class WebsiteVATMigrationTests(unittest.TestCase):
    def test_initialises_missing_setting_but_preserves_an_explicit_zero(self):
        path = Path(__file__).parents[1] / 'webshop/patches/enable_callus_inclusive_website_prices.py'
        tree = ast.parse(path.read_text())
        for rows in ([], [('0',)], [('1',)]):
            with self.subTest(rows=rows):
                frappe = Mock()
                frappe.db.sql.return_value = rows
                env = {'frappe': frappe}
                exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[]), str(path), 'exec'), env)
                env['execute']()
                if rows:
                    frappe.db.set_single_value.assert_not_called()
                else:
                    frappe.db.set_single_value.assert_called_once_with('Callus Checkout Settings', 'prices_include_vat', 1)


if __name__ == '__main__':
    unittest.main()
