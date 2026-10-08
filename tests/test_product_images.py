import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

fake = types.ModuleType('frappe')
spec = importlib.util.spec_from_file_location('product_images', Path(__file__).parents[1]/'webshop/callus_storefront/product_images.py')
m = importlib.util.module_from_spec(spec)
old = sys.modules.get('frappe'); sys.modules['frappe'] = fake
try: spec.loader.exec_module(m)
finally:
    if old is None: sys.modules.pop('frappe', None)
    else: sys.modules['frappe'] = old

class Images(unittest.TestCase):
    def setUp(self):
        fake.db = types.SimpleNamespace(exists=Mock(return_value=True))
        fake.get_doc = Mock(return_value=types.SimpleNamespace(website_image='/files/old.jpg', save=Mock()))
        fake.msgprint = Mock()
        fake.throw = Mock(side_effect=ValueError)
    def test_main_image_sync_and_removal(self):
        m.sync_main_image({'image':'/files/new.jpg'}, {'image':'/files/old.jpg'}, 'W')
        web=fake.get_doc.return_value
        self.assertEqual(web.website_image, '/files/new.jpg'); web.save.assert_called_once()
        m.sync_main_image({'image':''}, {'image':'/files/new.jpg'}, 'W')
        self.assertEqual(web.website_image, '')
    def test_unchanged_item_preserves_website_override(self):
        m.sync_main_image({'image':'/files/a.jpg'}, {'image':'/files/a.jpg'}, 'W')
        fake.get_doc.assert_not_called()
    def test_private_or_nonimage_is_not_published(self):
        for url in ['/private/files/x.jpg', '/files/x.pdf', 'https://example.com/x.jpg']:
            m.sync_main_image({'image':url}, {'image':'/files/old.jpg'}, 'W')
        fake.get_doc.assert_not_called()
        fake.db.exists.return_value=False
        self.assertFalse(m.public_image('/files/missing.jpg'))
    def test_gallery_duplicates_and_private_rejected(self):
        row=types.SimpleNamespace(image='/files/x.jpg')
        with self.assertRaises(ValueError):m.validate_gallery({'custom_product_images':[row,row]})
        with self.assertRaises(ValueError):m.validate_gallery({'custom_product_images':[types.SimpleNamespace(image='/private/files/x.jpg')]})
        m.validate_gallery({'custom_product_images':[row]})
    def test_marketing_allowlist_preserved_and_idempotent(self):
        for source, client in [("allowed = ['website_image', 'custom_bolt_enabled']\n# guard",False),('const allowed = ["website_image", "published"];',True)]:
            changed=m.allow_gallery(source,client)
            self.assertIn('custom_product_images',changed)
            self.assertEqual(changed,m.allow_gallery(changed,client))
            self.assertIn('website_image',changed)
            if not client:self.assertIn('# guard',changed);self.assertIn('custom_bolt_enabled',changed)

if __name__=='__main__':unittest.main()
