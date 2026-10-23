import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bloominggarden.bloominggarden.delivery import notifications


class CustomerPODAdapterTests(unittest.TestCase):
    def execution(self):
        doc=SimpleNamespace(docstatus=1,execution_status='Delivered',pod_pdf_status='Generated',
            pod_pdf='/private/files/POD.pdf',delivery_note='DN',customer='CUST',db_set=Mock())
        doc.get=lambda key:getattr(doc,key,None)
        return doc

    def test_campaign_handler_prevents_shared_customer_fallback(self):
        with patch.object(notifications,'_settings',return_value=SimpleNamespace(auto_email_pod_to_customer=1)), \
             patch.object(notifications,'frappe',new=Mock()) as runtime, \
             patch.object(notifications,'_customer_email') as fallback:
            runtime.get_hooks.return_value=['campaign.handler'];runtime.get_attr.return_value.return_value=True
            self.assertEqual(notifications.maybe_email_pod_to_customer(self.execution()),'handled')
            fallback.assert_not_called();runtime.sendmail.assert_not_called()

    def test_unrelated_customer_still_uses_the_existing_email_workflow(self):
        with patch.object(notifications,'_settings',return_value=SimpleNamespace(auto_email_pod_to_customer=1)), \
             patch.object(notifications,'frappe',new=Mock()) as runtime, \
             patch.object(notifications,'_customer_email',return_value=None) as fallback:
            runtime.get_hooks.return_value=['campaign.handler'];runtime.get_attr.return_value.return_value=False
            runtime.db.exists.return_value=True;runtime.db.get_value.return_value='CUST'
            self.assertEqual(notifications.maybe_email_pod_to_customer(self.execution()),'no-email')
            fallback.assert_called_once()

    def test_handler_failure_does_not_fall_back_to_a_shared_email(self):
        with patch.object(notifications,'_settings',return_value=SimpleNamespace(auto_email_pod_to_customer=1)), \
             patch.object(notifications,'frappe',new=Mock()) as runtime, \
             patch.object(notifications,'_customer_email') as fallback:
            runtime.get_hooks.return_value=['campaign.handler'];runtime.get_attr.return_value.side_effect=RuntimeError('Retry needed')
            with self.assertRaises(RuntimeError):notifications.maybe_email_pod_to_customer(self.execution())
            fallback.assert_not_called()
