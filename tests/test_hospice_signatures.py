import base64
from io import BytesIO
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
from webshop.callus_storefront.hospice_signature import clean_name, clean_signature
from webshop.callus_storefront import hospice_receipts as receipts


def png(image):
    output=BytesIO();image.save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()


class SignatureValidationTests(unittest.TestCase):
    def test_rejects_missing_malformed_external_and_oversized_images(self):
        for value in [None,'','https://example.test/signature.png','data:image/svg+xml;base64,abc',
                      'data:image/png;base64,@@@','data:image/png;base64,'+'a'*350001]:
            with self.subTest(value=str(value)[:25]),self.assertRaises(ValueError):clean_signature(value)

    def test_rejects_blank_and_transparent_signatures(self):
        for image in [Image.new('RGB',(500,160),'white'),Image.new('RGBA',(500,160),(0,0,0,0))]:
            with self.assertRaises(ValueError):clean_signature(png(image))

    def test_accepts_and_normalises_a_signature(self):
        image=Image.new('RGBA',(500,160),(255,255,255,0));draw=ImageDraw.Draw(image)
        draw.line([(10,100),(70,20),(120,110),(190,50),(300,80)],fill='black',width=3)
        result=clean_signature(png(image))
        self.assertTrue(result.startswith('data:image/png;base64,'))
        self.assertEqual(clean_signature(result),result)

    def test_name_is_required_bounded_and_preserved_for_escaping_at_render(self):
        self.assertEqual(clean_name('  Jane Collector  '),'Jane Collector')
        for name in [None,'','A\nName','x'*141]:
            with self.assertRaises(ValueError):clean_name(name)

    def test_cutoff_is_not_reset_on_later_migrations(self):
        with patch.object(receipts,'frappe',new=Mock()) as runtime, \
             patch.object(receipts.checkout,'_settings',return_value={'hospice_signed_receipts_from':'2026-10-23 10:00:00'}):
            receipts.setup();runtime.db.set_single_value.assert_not_called()

    def test_new_datetime_cutoff_is_initialised_without_a_truthy_minimum_date(self):
        with patch.object(receipts,'frappe',new=Mock()) as runtime, \
             patch.object(receipts.checkout,'_settings',return_value={}), \
             patch.object(receipts,'now_datetime',return_value='2026-10-23 10:00:00'):
            receipts.setup()
            runtime.db.set_single_value.assert_called_once_with('Callus Checkout Settings','hospice_signed_receipts_from','2026-10-23 10:00:00')

    def test_unrelated_delivery_does_not_claim_customer_email(self):
        with patch.object(receipts,'hospice_orders',return_value=[]),patch.object(receipts,'enqueue_delivery') as enqueue:
            self.assertFalse(receipts.handle_customer_pod_email(Mock()))
            enqueue.assert_not_called()

    def test_hospice_email_is_claimed_for_the_per_order_workflow(self):
        execution=Mock()
        with patch.object(receipts,'hospice_orders',return_value=['SO']),patch.object(receipts,'enqueue_delivery') as enqueue:
            self.assertTrue(receipts.handle_customer_pod_email(execution))
            enqueue.assert_called_once_with(execution)

    def test_delivery_requires_both_apps_to_support_safe_per_order_email(self):
        from bloominggarden.bloominggarden.delivery import notifications
        execution=Mock(execution_status='Delivered')
        with patch.object(receipts,'hospice_orders',return_value=['SO']), \
             patch.object(notifications,'CUSTOMER_POD_HANDLERS_SUPPORTED',False), \
             patch.object(receipts,'frappe',new=Mock()) as runtime:
            runtime.throw.side_effect=ValueError('Deploy delivery integration')
            with self.assertRaises(ValueError):receipts.validate_delivery_signature(execution)

    def test_old_delivery_jobs_are_not_emailed_after_upgrade(self):
        from types import SimpleNamespace
        with patch.object(receipts.checkout,'_settings',return_value={'hospice_signed_receipts_from':'2026-10-23 10:00:00'}):
            self.assertFalse(receipts.after_cutoff(SimpleNamespace(delivered_at='2026-10-22 10:00:00')))
            self.assertTrue(receipts.after_cutoff(SimpleNamespace(delivered_at='2026-10-23 10:01:00')))
