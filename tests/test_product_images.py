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


class AttachmentImport(unittest.TestCase):
    def test_new_images_only_and_privacy(self):
        web={'website_image':'/files/main.jpg','custom_product_images':[]}
        files=[{'file_url':url,'is_private':private} for url,private in [('/files/main.jpg',0),('/files/extra.jpg',0),('/files/extra.jpg',0),('/private/files/secret.jpg',1),('/files/invoice.pdf',0)]]
        rows,history=m.plan_attachment_import(web,files)
        self.assertEqual([r['image'] for r in rows],['/files/extra.jpg'])
        self.assertEqual(rows[0]['hide_from_website'],0)
        # Removed row remains absent on rerun.
        web['custom_gallery_import_history']=history
        self.assertEqual(m.plan_attachment_import(web,files)[0],[])
    def test_hidden_and_manually_selected_photos_preserved(self):
        rows=[{'image':'/files/hidden.jpg','hide_from_website':1,'caption':'Keep caption'}]
        web={'custom_product_images':rows}
        new,history=m.plan_attachment_import(web,[{'file_url':'/files/hidden.jpg'}])
        self.assertEqual(new,[]);self.assertEqual(rows[0]['hide_from_website'],1)
        self.assertIn('/files/hidden.jpg',history)
    def test_limit_preserves_unprocessed_photos_for_later(self):
        web={'custom_product_images':[{'image':f'/files/{i}.jpg'} for i in range(20)]}
        rows,history=m.plan_attachment_import(web,[{'file_url':'/files/new.jpg'}])
        self.assertEqual(rows,[]);self.assertNotIn('/files/new.jpg',history)

if __name__=='__main__':unittest.main()
