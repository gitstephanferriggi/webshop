import importlib
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch
from webshop.bolt_integration import entitlement


class EntitlementTests(unittest.TestCase):
    def setUp(self):
        self.f=MagicMock()
        self.f.throw.side_effect=ValueError
        self.agent=MagicMock()
        self.modules=patch.dict(sys.modules, {'frappe':self.f,'integration_hub.licence_agent':self.agent})
        self.modules.start();self.addCleanup(self.modules.stop)
        self.f.get_installed_apps.return_value=['integration_hub']
        self.f.get_single.return_value.get.return_value=1
        self.s=NS(provider_id='provider',environment='Staging')

    def test_missing_app_or_disabled_enforcement_preserves_existing_behavior(self):
        self.f.get_installed_apps.return_value=[]
        self.assertTrue(entitlement.new_work_allowed(self.s))
        self.f.get_single.assert_not_called()
        self.f.get_installed_apps.return_value=['integration_hub']
        self.f.get_single.return_value.get.return_value=0
        self.assertTrue(entitlement.new_work_allowed(self.s))
        self.agent.new_work_allowed.assert_not_called()

    def test_active_lease_must_match_provider_and_environment(self):
        self.agent.new_work_allowed.return_value=True
        self.assertTrue(entitlement.new_work_allowed(self.s))
        self.agent.new_work_allowed.assert_called_once_with('provider','Staging')

    def test_denied_or_broken_agent_stops_new_work(self):
        self.agent.new_work_allowed.return_value=False
        with self.assertRaises(ValueError): entitlement.require_new_work(self.s)
        self.agent.new_work_allowed.side_effect=ImportError('broken module')
        self.assertFalse(entitlement.new_work_allowed(self.s))


class EntryPointTests(unittest.TestCase):
    def harness(self,module,classname):
        fixture=getattr(importlib.import_module(module),classname)()
        fixture.setUp();self.addCleanup(fixture.tearDown)
        return fixture

    def test_suspension_blocks_accept_before_erp_submission_or_bolt(self):
        h=self.harness('test_bolt_operations','OperationsTests')
        with patch.object(entitlement,'new_work_allowed',return_value=False):
            with self.assertRaises(ValueError): h.act('accept')
        h.so.submit.assert_not_called();h.ops.client.request.assert_not_called()

    def test_suspension_still_allows_store_pause(self):
        h=self.harness('test_bolt_operations','OperationsTests')
        with patch.object(entitlement,'new_work_allowed',return_value=False):
            h.test_pause_store_endpoint_and_durable_state()

    def test_suspension_blocks_store_open_before_network(self):
        h=self.harness('test_bolt_operations','OperationsTests')
        with patch.object(h.ops,'require_manager'), patch.object(entitlement,'new_work_allowed',return_value=False):
            with self.assertRaises(ValueError): h.ops.store_status('profile','open')
        h.ops.client.request.assert_not_called()

    def test_suspension_skips_scheduled_sync_without_marking_review(self):
        h=self.harness('test_bolt_sync','SyncTests')
        h.f.get_single.return_value=NS(enabled=1,sync_catalogue=1,site_hostname='uat.example')
        h.m.get_url.return_value='https://uat.example'
        with patch.object(entitlement,'new_work_allowed',return_value=False), patch.object(h.m,'step') as step:
            h.m.tick();step.assert_not_called()
        h.f.db.set_single_value.assert_not_called()

    def test_suspension_stops_sale_creation_but_retains_inbox_event(self):
        h=self.harness('test_bolt_processing','ProcessingTests')
        h.f.throw.side_effect=ValueError
        h.f.db.exists.return_value=True
        h.f.get_doc.return_value=NS(status='Received',sales_order=None)
        event=h.event()
        with patch.object(entitlement,'new_work_allowed',return_value=False), patch.object(h.p,'create_sale') as create:
            with self.assertRaises(ValueError): h.p.process_event(event,NS(provider_id='P'))
            create.assert_not_called()
        event.db_set.assert_not_called()

    def test_suspension_does_not_interrupt_existing_cancellation_or_pickup_receipts(self):
        h=self.harness('test_bolt_processing','ProcessingTests')
        with patch.object(entitlement,'new_work_allowed',return_value=False):
            h.test_cancel_before_create_does_not_resurrect()
            h.test_pickup_receipt_does_not_create_another_sale()

    def test_outbound_guard_blocks_stock_and_accept_but_allows_fulfilment(self):
        h=self.harness('test_bolt_client','ClientTests')
        with patch.object(entitlement,'require_new_work',side_effect=ValueError('licence inactive')):
            for path in ('/genericClient/updateMenuQuantity','/genericClient/acceptOrder','/genericClient/startAcceptingOrders','/pim/v1/menu/drafts/publish'):
                with self.assertRaises(ValueError): h.client.request(h.settings,path,{})
            h.requests.post.assert_not_called()
            for name in ('pauseOrders','rejectOrder','markOrderAsReadyForPickup','markOrderAsPickedUp','markOrderAsDelivered'):
                self.assertEqual(h.client.request(h.settings,'/genericClient/'+name,{}),{})
