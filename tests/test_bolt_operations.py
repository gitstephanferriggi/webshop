import importlib
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.f=MagicMock(); self.f.whitelist=lambda **kw: lambda fn:fn
        self.f.PermissionError=type('PermissionError',(Exception,),{})
        self.f.throw.side_effect=lambda message,*args: (_ for _ in ()).throw(ValueError(message))
        self.f.db.exists.return_value=False
        self.f.session.user='picker'; self.f.get_roles.return_value=['Bolt Order Operator']
        modules={'frappe':self.f,'frappe.utils':MagicMock(),'webshop.bolt_integration.client':MagicMock()}
        self.patch=patch.dict(sys.modules,modules); self.patch.start()
        sys.modules.pop('webshop.bolt_integration.operations',None)
        self.ops=importlib.import_module('webshop.bolt_integration.operations')
        self.pos_context=patch('webshop.bolt_integration.pos_sales.context',return_value=None);self.pos_context.start()
        self.order=MagicMock(); self.order.pos_invoice=None; self.order.modified='v1'; self.order.workflow_state='New'
        self.order.operation_state=''; self.order.payment_type='card_online'; self.order.order_type='delivery'
        self.order.acceptance_deadline=0; self.order.bolt_order_id='42'; self.order.status='Draft Sale'
        self.order.assigned_to='picker'; self.order.picking='{}'; self.order.order_reference='REF'
        self.s=NS(provider_id='provider',company='Company',customer='Customer',warehouse='Garden')
        self.so=MagicMock();self.so.docstatus=1;self.so.company='Company';self.so.customer='Customer'
        self.f.get_doc.return_value=self.so
        self.real_settings = self.ops.settings
        self.patches=[patch.object(self.ops,'settings',return_value=self.s),patch.object(self.ops,'locked_order',return_value=self.order),patch.object(self.ops,'dto',return_value={}),patch.object(self.ops,'client')]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.pos_context.stop();sys.modules.pop('webshop.bolt_integration.pos_sales',None)
        self.patch.stop();sys.modules.pop('webshop.bolt_integration.operations',None)
    def act(self,action,**kw):return self.ops.act('profile','order',action,'v1',**kw)
    def test_guest_denied(self):
        self.f.session.user='Guest'
        with self.assertRaises(ValueError): self.real_settings('profile')
    def test_disabled_is_inert(self):
        self.f.get_single.return_value=NS(enabled=0)
        self.assertIsNone(self.real_settings('profile'))
    def configured_settings(self):
        self.f.get_single.return_value=NS(enabled=1,two_way_enabled=1,process_orders=1,
            site_hostname='uat.example',pos_profile='profile',company='Company',warehouse='Garden')
        self.ops.get_url.return_value='https://uat.example'
        self.f.get_doc.return_value=NS(company='Company',warehouse='Garden',applicable_for_users=[NS(user='picker')])
        self.f.db.get_value.return_value='Company'
    def test_wrong_role_denied(self):
        self.configured_settings(); self.f.get_roles.return_value=['Sales User']
        with self.assertRaises(ValueError): self.real_settings('profile')
    def test_wrong_profile_denied(self):
        self.configured_settings()
        with self.assertRaises(ValueError): self.real_settings('another')
    def test_profile_membership_required(self):
        self.configured_settings(); self.f.get_doc.return_value.applicable_for_users=[]
        with self.assertRaises(ValueError): self.real_settings('profile')
    def test_hostname_binding_enforced(self):
        self.configured_settings(); self.ops.get_url.return_value='https://production.example'
        with self.assertRaises(ValueError): self.real_settings('profile')
    def test_valid_scoped_operator(self):
        self.configured_settings(); self.assertEqual(self.real_settings('profile').warehouse,'Garden')
    def test_store_controls_manager_only(self):
        with self.assertRaises(ValueError): self.ops.store_status('profile','open')
        self.ops.client.request.assert_not_called()
    def test_pause_store_endpoint_and_durable_state(self):
        self.f.get_roles.return_value=['Bolt Order Manager']
        self.s.store_action_state=''; self.s.reload=MagicMock()
        self.ops.store_status('profile','pause')
        self.ops.client.request.assert_called_once_with(self.s,'/genericClient/pauseOrders',{'provider_id':'provider'})
        self.f.db.commit.assert_called_once()
    def test_store_uncertain_outcome_not_repeated(self):
        self.f.get_roles.return_value=['Bolt Order Manager']
        self.s.store_action_state='Sending'; self.s.reload=MagicMock()
        with self.assertRaises(ValueError): self.ops.store_status('profile','open')
        self.ops.client.request.assert_not_called()
    def test_adjustment_requires_manager_and_reviewed_token(self):
        self.order.workflow_state='Picking'
        with self.assertRaises(ValueError): self.act('ready_adjusted')
        self.f.get_roles.return_value=['Bolt Order Manager']
        with patch.object(self.ops,'adjustment',return_value={'token':'current','items':[]}):
            with self.assertRaises(ValueError):self.act('ready_adjusted',note='Out of stock',preview_token='stale')
        self.ops.client.request.assert_not_called()
    def test_ready_adjusted_uses_item_endpoint_and_separate_reconcile(self):
        self.order.workflow_state='Picking';self.f.get_roles.return_value=['Bolt Order Manager']
        with patch.object(self.ops,'adjustment',return_value={'token':'current','items':[{'sku':'A','amount':1}]}), patch.object(self.ops,'reconcile_adjustment') as reconcile:
            self.act('ready_adjusted',note='Out of stock',preview_token='current')
            reconcile.assert_called_once_with('profile','order')
        self.assertEqual(self.ops.client.request.call_args.args[1],'/genericClient/markOrderWithItemsAsReadyForPickUp')
        self.assertEqual(self.order.operation_state,'Confirmed')
    def test_unconfirmed_adjustment_cannot_be_reconciled_to_ready(self):
        self.f.get_roles.return_value=['Bolt Order Manager'];self.order.operation='ready_adjusted';self.order.operation_state='Review'
        with self.assertRaises(ValueError):self.ops.reconcile_adjustment('profile','order')
        self.ops.client.request.assert_not_called()
    def test_received_cancellation_blocks_handover(self):
        self.order.workflow_state='Ready';self.f.db.exists.return_value=True
        with patch.object(self.ops,'record_sale') as record:
            with self.assertRaises(ValueError):self.act('handover',note='REF')
            record.assert_not_called()
    def test_stale_version_never_dispatches(self):
        self.order.modified='v2'
        with self.assertRaises(ValueError):self.act('accept')
        self.ops.client.request.assert_not_called()
    def test_durable_sending_before_network(self):
        def call(*args):
            self.assertEqual(self.order.operation_state,'Sending')
            self.f.db.commit.assert_called_once()
        self.ops.client.request.side_effect=call
        self.act('accept')
        self.assertEqual(self.order.workflow_state,'Picking')
        self.assertEqual(self.order.operation_state,'Confirmed')
    def test_ambiguous_remote_failure_never_retries(self):
        self.ops.client.request.side_effect=TimeoutError()
        self.act('accept')
        self.assertEqual(self.order.operation_state,'Review')
        self.assertEqual(self.order.workflow_state,'Needs attention')
        with self.assertRaises(ValueError):self.act('accept')
        self.ops.client.request.assert_called_once()
    def test_operator_cannot_reject(self):
        with self.assertRaises(ValueError):self.act('reject',note='Out of stock')
        self.ops.client.request.assert_not_called()
    def test_ack_does_not_accept(self):
        self.act('acknowledge');self.ops.client.request.assert_not_called()
        self.assertEqual(self.order.workflow_state,'New')
    def test_wrong_picker_blocked(self):
        self.order.workflow_state='Picking';self.order.assigned_to='someoneelse'
        with self.assertRaises(ValueError):self.act('pick',quantities={})
    def test_unpicked_order_cannot_be_ready(self):
        self.order.workflow_state='Picking'
        with patch.object(self.ops,'lines',return_value=[{'id':'line','qty':2}]):
            with self.assertRaises(ValueError):self.act('ready')
        self.ops.client.request.assert_not_called()
    def test_bolt_courier_handover_never_calls_remote_pickedup(self):
        self.order.workflow_state='Ready'
        with patch.object(self.ops,'record_sale') as record:
            self.act('handover',note='REF');record.assert_called_once()
        self.ops.client.request.assert_not_called()
        self.assertEqual(self.order.workflow_state,'Collected')
    def test_duplicate_invoice_prevented(self):
        self.order.sales_invoice='INV'; self.so.docstatus=1
        self.ops.record_sale(self.order,self.s)
        self.f.get_doc.assert_called_once_with('Sales Invoice','INV')
    def test_cancel_racing_acceptance_requires_review(self):
        self.order.status='Cancelled'
        self.act('accept')
        self.assertEqual(self.order.workflow_state,'Needs attention')

if __name__=='__main__':unittest.main()
