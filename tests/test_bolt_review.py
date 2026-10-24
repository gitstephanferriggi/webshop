import importlib
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.f = MagicMock()
        self.f.whitelist = lambda **kw: lambda fn: fn
        def fail(message): raise ValueError(message)
        self.f.throw.side_effect = fail
        self.utils = MagicMock()
        self.utils.get_url.return_value = 'https://uat.example'
        self.modules = patch.dict(sys.modules, {'frappe': self.f, 'frappe.utils': self.utils})
        self.modules.start()
        sys.modules.pop('webshop.bolt_integration.review', None)
        self.m = importlib.import_module('webshop.bolt_integration.review')
        self.s = NS(site_hostname='uat.example', provider_id='P', environment='Staging')
        self.f.get_single.return_value = self.s
        self.f.session.user = 'manager'

    def tearDown(self):
        self.modules.stop()
        sys.modules.pop('webshop.bolt_integration.review', None)

    def sale(self, qty=1, total=5, **kwargs):
        d = dict(name='original', docstatus=1, company='C', customer='Buyer', currency='EUR',
                 payments=[], is_return=0, return_against=None, outstanding_amount=0, grand_total=total,
                 items=[NS(item_code='A', warehouse='W', stock_uom='Pcs', stock_qty=qty)])
        d.update(kwargs)
        return NS(**d)

    def event(self):
        return NS(provider_id='P', status='Review', is_test=0, bolt_order_id='BOLT-UAT-123',
                  add_comment=MagicMock(), db_set=MagicMock())

    def test_role_checked_before_document_access(self):
        self.f.only_for.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.m.resolve_review('Callus Bolt Event', 'e', 'Reviewed test')
        self.f.get_doc.assert_not_called()

    def test_reason_and_site_binding_required(self):
        for reason in ['', 'x']:
            with self.assertRaises(ValueError): self.m.context(reason)
        self.s.site_hostname = 'production.example'
        with self.assertRaises(ValueError): self.m.context('Reviewed test')

    def test_full_return_and_amount_required(self):
        original = self.sale()
        good = self.sale(-1, -5, name='return', is_return=1, return_against='original')
        self.m.fully_reversed(original, [good])
        for ret in [self.sale(-.5, -5, is_return=1, return_against='original'),
                    self.sale(-1, -4, is_return=1, return_against='original'),
                    self.sale(-1, -5, is_return=1, return_against='other'),
                    self.sale(-1, -5, is_return=1, return_against='original', outstanding_amount=-5)]:
            with self.assertRaises(ValueError): self.m.fully_reversed(original, [ret])
        with self.assertRaises(ValueError): self.m.fully_reversed(original, [])

    def test_unconsolidated_pos_return_cannot_resolve(self):
        source = self.sale(consolidated_invoice='SI')
        ret = self.sale(-1, -5, is_return=1, return_against='original', consolidated_invoice=None)
        self.f.get_all.return_value = ['return']
        self.f.get_doc.side_effect = [source, ret, self.sale()]
        with self.assertRaisesRegex(ValueError, 'Close the return POS shift'):
            self.m.verify_sale(NS(pos_invoice='original', sales_invoice=None))

    def test_synthetic_event_archived_with_original_error_retained(self):
        event = self.event(); self.f.get_doc.return_value = event
        self.f.get_all.return_value = []
        self.m.resolve_review('Callus Bolt Event', 'e', 'Historical synthetic test')
        event.db_set.assert_called_once_with({'status': 'Ignored'})
        event.add_comment.assert_called_once()

    def test_unlinked_live_or_nonterminal_event_not_dismissible(self):
        event = self.event(); self.f.get_doc.return_value = event
        self.s.environment = 'Production'; self.f.get_all.return_value = []
        with self.assertRaises(ValueError): self.m.resolve_review('Callus Bolt Event','e','Historical test')
        self.s.environment = 'Staging'
        self.f.get_all.return_value = [NS(status='Recorded', environment='Staging')]
        with self.assertRaises(ValueError): self.m.resolve_review('Callus Bolt Event','e','Historical test')
        event.db_set.assert_not_called()

    def test_foreign_provider_rejected(self):
        event = self.event(); event.provider_id='other'; self.f.get_doc.return_value=event
        with self.assertRaises(ValueError): self.m.resolve_review('Callus Bolt Event','e','Historical test')
        event.db_set.assert_not_called()

    def test_order_resolution_requires_verified_cancellation(self):
        order = NS(provider_id='P', environment='Staging', workflow_state='Needs attention', bolt_order_id='42')
        self.f.get_doc.return_value=order; self.f.db.exists.return_value=False
        with self.assertRaisesRegex(ValueError, 'verified Bolt cancellation'):
            self.m.resolve_review('Callus Bolt Order','o','Cancellation reviewed')

    def test_reversed_sale_closes_linked_order_without_cancelling(self):
        order = NS(provider_id='P', environment='Staging', workflow_state='Needs attention',
                   bolt_order_id='42', sales_order='SO', add_comment=MagicMock(), db_set=MagicMock())
        so = NS(per_delivered=0, per_billed=0, docstatus=1, check_permission=MagicMock(), cancel=MagicMock(), update_status=MagicMock())
        self.f.get_doc.side_effect=[order, so]; self.f.db.exists.return_value=True
        with patch.object(self.m, 'verify_sale', return_value=['RETURN', 'CREDIT']):
            result=self.m.resolve_review('Callus Bolt Order','o','Cancellation and full return reviewed')
        so.check_permission.assert_called_once_with('submit')
        so.update_status.assert_called_once_with('Closed')
        so.cancel.assert_not_called()
        order.add_comment.assert_called_once()
        order.db_set.assert_called_once_with({'status':'Cancelled','workflow_state':'Cancelled','operation_error':''})
        self.assertEqual(result['references'], ['RETURN','CREDIT'])

    def test_uninvoiced_cancellation_still_cancels_sales_order(self):
        order = NS(provider_id='P', environment='Staging', workflow_state='Needs attention',
                   bolt_order_id='42', sales_order='SO', add_comment=MagicMock(), db_set=MagicMock())
        so = NS(per_delivered=0, per_billed=0, docstatus=1, check_permission=MagicMock(),
                cancel=MagicMock(), update_status=MagicMock())
        self.f.get_doc.side_effect=[order, so]; self.f.db.exists.return_value=True
        with patch.object(self.m, 'verify_sale', return_value=[]):
            self.m.resolve_review('Callus Bolt Order','o','Unfulfilled cancellation reviewed')
        so.check_permission.assert_called_once_with('cancel')
        so.cancel.assert_called_once()
        so.update_status.assert_not_called()
