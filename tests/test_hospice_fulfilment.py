import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import frappe
from webshop.callus_storefront.hospice_fulfilment import preparation_state, operational_facts


class HospiceProgressTests(unittest.TestCase):
    def test_ready_states_follow_fulfilment_method(self):
        for pickup, ready in [(True,'Ready for pickup'),(False,'Ready for dispatch')]:
            for picked, dispatched in [(True,False),(False,True)]:
                self.assertEqual(preparation_state(None,pickup,True,picked,dispatched),ready)
            self.assertEqual(preparation_state(None,pickup,True,False,False),'Preparing')
            self.assertEqual(preparation_state(None,pickup,False,False,False),'Awaiting preparation')

    def test_pickup_requires_explicit_collection(self):
        self.assertEqual(preparation_state(None,True,True,True,True),'Ready for pickup')
        self.assertEqual(preparation_state('Collected',True,True,True,True),'Collected')

    def test_manual_readiness_does_not_cross_fulfilment_methods(self):
        self.assertEqual(preparation_state('Ready for dispatch',True,False,False,False),'Awaiting preparation')
        self.assertEqual(preparation_state('Ready for pickup',False,False,False,False),'Awaiting preparation')

    def test_picking_uses_stock_uom_and_excludes_delivery_service(self):
        order=SimpleNamespace(name='SO',items=[
            SimpleNamespace(name='LINE',item_code='PRODUCT',qty=2,conversion_factor=6),
            SimpleNamespace(name='FEE',item_code='DELIVERY',qty=1,conversion_factor=1)])
        with patch('webshop.callus_storefront.hospice.delivery_item',return_value='DELIVERY'), \
             patch('webshop.callus_storefront.hospice_fulfilment.checkout._settings'), \
             patch('webshop.callus_storefront.hospice_fulfilment.frappe',new=Mock()) as framework:
            framework.get_cached_value.return_value=True
            db=framework.db
            db.sql.side_effect=[[
                frappe._dict(sales_order_item='LINE',picked_qty=6,docstatus=1),
                frappe._dict(sales_order_item='LINE',picked_qty=6,docstatus=1)],[]]
            self.assertEqual(operational_facts(order),(True,True,False))
            db.sql.side_effect=[[
                frappe._dict(sales_order_item='LINE',picked_qty=12,docstatus=0)],[]]
            self.assertEqual(operational_facts(order),(True,False,False))
            db.sql.side_effect=[[],[
                frappe._dict(so_detail='LINE',qty=2,conversion_factor=6),
                frappe._dict(so_detail='LINE',qty=-1,conversion_factor=6)]]
            self.assertEqual(operational_facts(order),(True,False,False))
