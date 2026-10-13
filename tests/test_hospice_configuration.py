import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from webshop.callus_storefront import hospice


class HospiceWarehouseConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            hospice_customer='CASH-HOSPICE', hospice_items=[SimpleNamespace(item_code='ITEM')],
            hospice_warehouse='Stores - BGL', save=Mock(),
        )
        self.source = SimpleNamespace(customer='HOSPICE', company='Company',
                                      allowed_items=[SimpleNamespace(item_code='ITEM')],
                                      default_warehouse='Stores - BGL')
        self.warehouse = SimpleNamespace(name='Garden Center - BGL', disabled=0,
                                         is_group=0, company='Company')
        self.frappe = Mock()
        self.frappe.get_single.return_value = self.source
        self.frappe.get_cached_doc.return_value = SimpleNamespace(company='Company')
        self.frappe.db.get_value.return_value = 'Hospice Malta'
        self.frappe.get_doc.return_value = self.warehouse
        self.frappe.throw.side_effect = ValueError
        for target, kwargs in [
            ('frappe', {'new': self.frappe}),
            ('checkout._settings', {'return_value': self.settings}),
        ]:
            p = patch('webshop.callus_storefront.hospice.' + target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_manager_can_change_warehouse(self):
        hospice.configure.__wrapped__(warehouse='Garden Center - BGL')
        self.frappe.only_for.assert_called_once_with('System Manager')
        self.assertEqual(self.settings.hospice_warehouse, 'Garden Center - BGL')
        self.settings.save.assert_called_once()

    def test_omitting_warehouse_keeps_existing_selection(self):
        hospice.configure.__wrapped__()
        self.assertEqual(self.settings.hospice_warehouse, 'Stores - BGL')

    def test_invalid_warehouses_do_not_save(self):
        for field, value in [('disabled', 1), ('is_group', 1), ('company', 'Other')]:
            original = getattr(self.warehouse, field)
            setattr(self.warehouse, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                hospice.configure.__wrapped__(warehouse='Garden Center - BGL')
            setattr(self.warehouse, field, original)
        self.settings.save.assert_not_called()

    def test_non_manager_cannot_change_warehouse(self):
        self.frappe.only_for.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            hospice.configure.__wrapped__(warehouse='Garden Center - BGL')
        self.settings.save.assert_not_called()

    def test_enable_still_validates_campaign_and_gateway(self):
        with patch.object(hospice, 'campaign_settings') as campaign, \
             patch.object(hospice.checkout, '_gateway', return_value=(None, None, True)) as gateway:
            result = hospice.configure.__wrapped__(enable=1, warehouse='Garden Center - BGL')
        campaign.assert_called_once()
        gateway.assert_called_once_with(self.settings)
        self.assertTrue(result['enabled'])
