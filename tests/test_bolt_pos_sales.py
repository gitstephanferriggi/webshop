import importlib
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

class PosSalesTests(unittest.TestCase):
    def setUp(self):
        self.f=MagicMock()
        self.f.throw.side_effect=lambda message: (_ for _ in ()).throw(ValueError(message))
        self.f.session.user='cashier'
        self.profile=NS(payments=[NS(mode_of_payment='Bolt Food')],get=lambda key: 'Cash')
        self.mode=NS(enabled=1,type='General',accounts=[NS(company='Company',default_account='Clearing')])
        self.account=NS(name='Clearing',company='Company',is_group=0,disabled=0,account_type='',root_type='Asset',account_currency='EUR')
        self.shift=NS(name='SHIFT',status='Open',docstatus=1,user='cashier',pos_profile='Profile',company='Company',pos_closing_shift=None)
        self.f.get_doc.side_effect=lambda dt,*args,**kwargs: {'POS Profile':self.profile,'Mode of Payment':self.mode,'Account':self.account,'POS Opening Shift':self.shift}[dt]
        self.f.get_all.return_value=['SHIFT']
        self.patcher=patch.dict(sys.modules,{'frappe':self.f});self.patcher.start()
        sys.modules.pop('webshop.bolt_integration.pos_sales',None)
        self.p=importlib.import_module('webshop.bolt_integration.pos_sales')
        self.settings=NS(pos_profile='Profile',company='Company',payment_method='Bolt Food')
    def tearDown(self):
        self.patcher.stop();sys.modules.pop('webshop.bolt_integration.pos_sales',None)
    def test_valid_cashier_tender_and_lock(self):
        self.assertEqual(self.p.context(self.settings)[1:],(self.shift,'Bolt Food','Clearing'))
        self.f.get_doc.assert_any_call('POS Opening Shift','SHIFT',for_update=True)
    def test_missing_or_ambiguous_shift(self):
        for names in ([],['A','B']):
            self.f.get_all.return_value=names
            with self.assertRaises(ValueError): self.p.context(self.settings)
    def test_wrong_cashier_or_closed_shift(self):
        self.shift.user='other'
        with self.assertRaises(ValueError):self.p.context(self.settings)
        self.shift.user='cashier';self.shift.status='Closed'
        with self.assertRaises(ValueError):self.p.context(self.settings)
    def test_cash_payment_forbidden(self):
        self.mode.type='Cash'
        with self.assertRaises(ValueError):self.p.context(self.settings)
    def test_wrong_company_or_party_account_forbidden(self):
        self.account.company='Other'
        with self.assertRaises(ValueError):self.p.context(self.settings)
        self.account.company='Company';self.account.account_type='Receivable'
        with self.assertRaises(ValueError):self.p.context(self.settings)
    def test_missing_configuration_never_falls_back_to_cash(self):
        self.settings.payment_method=None
        with self.assertRaises(ValueError):self.p.context(self.settings)
    def test_unlisted_tender_forbidden(self):
        self.profile.payments=[]
        with self.assertRaises(ValueError):self.p.context(self.settings)

    def test_stale_closing_rejected(self):
        self.f.get_single.return_value=NS(enabled=1,pos_profile='Profile',get=lambda key:1)
        self.f.db.get_value.return_value=1
        self.f.db.sql.return_value=[('POS-NEW',)]
        doc=NS(pos_profile='Profile',pos_opening_shift='SHIFT',pos_transactions=[])
        with self.assertRaises(ValueError):self.p.validate_closing(doc)
        doc.pos_transactions=[{'pos_invoice':'POS-NEW'}]
        self.p.validate_closing(doc)
