import unittest
from webshop.bolt_integration.workflow import check_action, validate_picks, all_picked, numeric_order_id

class WorkflowTests(unittest.TestCase):
    def test_acknowledgement_is_possible_during_uncertain_operation(self):
        check_action('Needs attention', 'acknowledge', 'Review')
    def test_accept_only_new(self):
        check_action('New', 'accept')
        for state in ('Picking','Ready','Collected','Cancelled','Rejected','Needs attention'):
            with self.assertRaises(ValueError): check_action(state, 'accept')
    def test_rejection_after_acceptance_forbidden(self):
        with self.assertRaises(ValueError): check_action('Picking', 'reject')
    def test_uncertain_actions_never_retried(self):
        for state in ('Sending','Review'):
            with self.assertRaises(ValueError): check_action('New', 'accept', state)
    def test_cash_cannot_be_accepted(self):
        with self.assertRaises(ValueError): check_action('New', 'accept', payment_type='cash')
    def test_wrong_or_missing_rows_rejected(self):
        rows=[{'id':'a','qty':2}]
        for picks in ({}, {'b':2}, {'a':2,'b':0}, []):
            with self.assertRaises(ValueError):validate_picks(rows,picks)
    def test_invalid_quantities(self):
        for qty in (-1,3,float('nan'),float('inf'),True,None,'abc'):
            with self.assertRaises(ValueError):validate_picks([{'id':'a','qty':2}],{'a':qty})
    def test_duplicate_skus_keep_distinct_rows(self):
        rows=[{'id':'a','qty':1,'code':'SKU'},{'id':'b','qty':2,'code':'SKU'}]
        self.assertFalse(all_picked(rows, {'a':1,'b':1}))
        self.assertTrue(all_picked(rows,validate_picks(rows,{'a':1,'b':2})))
    def test_no_empty_ready(self): self.assertFalse(all_picked([],{}))
    def test_numeric_remote_ids(self):
        self.assertEqual(numeric_order_id('123'),123)
        for value in ('test','0','-1','1.5','１２',None):
            with self.assertRaises(ValueError):numeric_order_id(value)
    def test_handover_requires_ready(self):
        check_action('Ready','handover')
        with self.assertRaises(ValueError):check_action('Collected','handover')

if __name__=='__main__': unittest.main()
