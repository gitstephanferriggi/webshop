"""Real isolated stock, evidence, private Files and outbox transactions.

Stripe/SMTP/PDF conversion and the absent driver-module boundary are simulated.
"""
import base64
import secrets
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from pypdf import PdfWriter
import frappe

from hospice_integration import HospiceIntegrationTests
from webshop.callus_storefront import checkout as api, hospice_collection as collection
from webshop.callus_storefront import hospice_fulfilment as fulfilment, hospice_receipts as receipts

writer=PdfWriter();writer.add_blank_page(width=595,height=842);pdf_stream=BytesIO();writer.write(pdf_stream)
PDF_BYTES=pdf_stream.getvalue()


def signature():
    image=Image.new('RGB',(500,160),'white');draw=ImageDraw.Draw(image)
    draw.line([(30,100),(75,35),(90,110),(145,55),(190,100),(240,45),(300,105),(435,70)],fill='black',width=3)
    output=BytesIO();image.save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()


class SignedHandoverTests(unittest.TestCase):
    setUpClass=classmethod(HospiceIntegrationTests.setUpClass.__func__)
    prepare=HospiceIntegrationTests.prepare
    pay=HospiceIntegrationTests.pay
    mark_paid=HospiceIntegrationTests.mark_paid
    stripe=HospiceIntegrationTests.stripe
    delivery_note=HospiceIntegrationTests.delivery_note

    def setUp(self):
        HospiceIntegrationTests.setUp(self)
        self.jobs=patch.object(receipts,'enqueue_receipt');self.enqueued=self.jobs.start()

    def tearDown(self):
        self.jobs.stop();HospiceIntegrationTests.tearDown(self)

    def ready(self):
        self.buyer['delivery']='collection'
        self.pay();self.mark_paid();api.status(self.token)
        self.payment=api._doc(self.token)
        with patch('frappe.enqueue'):
            fulfilment.set_preparation(self.payment.sales_order,'Ready for pickup')
        return frappe.get_doc('Sales Order',self.payment.sales_order)

    def collect(self):
        return collection.confirm_collection(self.payment.sales_order,'Jane Collector',signature())

    def notes(self):
        return frappe.db.sql("""SELECT DISTINCT i.parent FROM `tabDelivery Note Item` i
            JOIN `tabDelivery Note` d ON d.name=i.parent WHERE i.against_sales_order=%s AND d.docstatus=1""",
            self.payment.sales_order,pluck=True)

    def test_signed_collection_creates_one_note_and_one_immutable_receipt(self):
        order=self.ready();before=frappe.db.get_value('Bin',{'warehouse':order.items[0].warehouse,'item_code':'CHECKOUT-BASIL'},'actual_qty')
        first=self.collect();again=self.collect()
        self.assertEqual(first['name'],again['name']);self.assertEqual(len(self.notes()),1)
        after=frappe.db.get_value('Bin',{'warehouse':order.items[0].warehouse,'item_code':'CHECKOUT-BASIL'},'actual_qty')
        self.assertEqual(before-after,2)
        saved=frappe.get_doc('Callus Handover',first['name'])
        self.assertEqual(saved.docstatus,1);self.assertEqual(saved.recipient_name,'Jane Collector')
        self.assertEqual(saved.recorded_by,'Administrator');self.assertTrue(saved.handed_over_at)
        self.assertEqual([row.qty for row in saved.items],[2])
        self.assertEqual(frappe.get_doc('Sales Order',order.name).custom_hospice_status,'Collected')
        self.enqueued.assert_called_once_with(saved.name)
        saved.recipient_name='Changed'
        with self.assertRaises(frappe.UpdateAfterSubmitError):saved.save(ignore_permissions=True)

    def test_existing_submitted_stock_note_is_reused(self):
        self.ready();note=self.delivery_note();before=len(self.notes())
        receipt=self.collect()
        self.assertEqual(len(self.notes()),before)
        self.assertEqual(frappe.get_doc('Callus Handover',receipt['name']).delivery_notes,note.name)

    def test_matching_draft_note_is_submitted_instead_of_duplicated(self):
        self.ready()
        from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
        note=make_delivery_note(self.payment.sales_order);note.insert()
        self.collect()
        self.assertEqual(self.notes(),[note.name])

    def test_evidence_failure_rolls_back_stock_and_collection(self):
        order=self.ready()
        with patch.object(receipts,'create_handover',side_effect=frappe.ValidationError('Evidence failed')):
            with self.assertRaises(frappe.ValidationError):self.collect()
        self.assertEqual(self.notes(),[])
        self.assertFalse(frappe.db.exists('Callus Handover',{'sales_order':order.name}))
        self.assertEqual(frappe.get_doc('Sales Order',order.name).custom_hospice_status,'Ready for pickup')

    def test_unsigned_api_shortcut_is_rejected(self):
        self.ready()
        with self.assertRaises(frappe.ValidationError):fulfilment.set_preparation(self.payment.sales_order,'Collected')
        for sig in ['', 'data:image/svg+xml;base64,abc']:
            with self.assertRaises(frappe.ValidationError):
                collection.confirm_collection(self.payment.sales_order,'Collector',sig)
        self.assertEqual(self.notes(),[])

    def test_unpaid_and_unready_orders_cannot_be_collected(self):
        self.buyer['delivery']='collection';self.pay();doc=api._doc(self.token)
        with self.assertRaises(frappe.ValidationError):collection.confirm_collection(doc.sales_order,'Collector',signature())
        self.mark_paid();api.status(self.token)
        with self.assertRaises(frappe.ValidationError):collection.confirm_collection(doc.sales_order,'Collector',signature())

    def test_guest_cannot_collect_view_or_resend_receipts(self):
        self.ready();receipt=self.collect();frappe.set_user('Guest')
        for action in [lambda:collection.collection_details(self.payment.sales_order),
                       lambda:collection.confirm_collection(self.payment.sales_order,'Collector',signature()),
                       lambda:receipts.order_receipts(self.payment.sales_order),
                       lambda:receipts.retry_or_resend(receipt['name'])]:
            with self.assertRaises(frappe.PermissionError):action()

    def test_unsigned_receipt_cannot_be_inserted_directly(self):
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(dict(doctype='Callus Handover',source_key='forged',recipient_name='Forged',signature=signature())).insert(ignore_permissions=True)

    def test_signed_stock_note_cannot_be_cancelled_as_an_unsigned_handover(self):
        self.ready();self.collect();note=frappe.get_doc('Delivery Note',self.notes()[0])
        with self.assertRaises(frappe.ValidationError):note.cancel()

    def test_cancelled_payment_blocks_collection_even_if_checkout_marker_is_paid(self):
        self.ready();frappe.get_doc('Payment Entry',self.payment.payment_entry).cancel()
        with self.assertRaises(frappe.ValidationError):self.collect()
        self.assertEqual(self.notes(),[])

    def test_email_failure_keeps_collection_and_retries_without_duplicate_stock(self):
        self.ready();receipt=self.collect();frappe.db.commit()
        self.sent.reset_mock()
        with patch.object(receipts,'render_pdf',side_effect=RuntimeError('PDF unavailable')):
            receipts.process_receipt(receipt['name'])
        saved=frappe.get_doc('Callus Handover',receipt['name'])
        self.assertEqual(saved.email_state,'Failed')
        self.assertEqual(frappe.get_doc('Sales Order',self.payment.sales_order).custom_hospice_status,'Collected')
        self.sent.assert_not_called()
        with patch.object(receipts,'render_pdf',return_value=PDF_BYTES):
            receipts.process_receipt(saved.name);receipts.process_receipt(saved.name)
        self.assertEqual(self.sent.call_count,1)
        self.assertEqual(self.sent.call_args.kwargs['recipients'],['tester@example.com'])
        self.assertEqual(len(self.sent.call_args.kwargs['attachments']),1)
        self.assertEqual(len(self.notes()),1)
        saved.reload();self.assertEqual(saved.email_state,'Queued');self.assertTrue(saved.receipt_pdf.startswith('/private/files/'))
        file=frappe.get_doc('File',self.sent.call_args.kwargs['attachments'][0]['fid'])
        self.assertEqual(file.is_private,1);self.assertEqual(file.attached_to_name,self.payment.sales_order)
        frappe.set_user('Guest');self.assertFalse(frappe.has_permission('File','read',doc=file))

    def test_explicit_resend_reuses_evidence_and_pdf(self):
        self.ready();receipt=self.collect();frappe.db.commit();self.sent.reset_mock()
        with patch.object(receipts,'render_pdf',return_value=PDF_BYTES) as renderer:
            receipts.process_receipt(receipt['name']);receipts.retry_or_resend(receipt['name'])
        self.assertEqual(renderer.call_count,1);self.assertEqual(self.sent.call_count,2)
        self.assertEqual(len(self.notes()),1)
        self.assertEqual(frappe.get_doc('Callus Handover',receipt['name']).resend_count,1)

    def test_smtp_queue_failure_retries_only_the_email(self):
        self.ready();receipt=self.collect();frappe.db.commit();self.sent.reset_mock()
        self.sent.side_effect=RuntimeError('Queue temporarily unavailable')
        with patch.object(receipts,'render_pdf',return_value=PDF_BYTES):
            receipts.process_receipt(receipt['name'])
        self.assertEqual(frappe.get_doc('Callus Handover',receipt['name']).email_state,'Failed')
        self.sent.side_effect=None
        with patch.object(receipts,'render_pdf',return_value=PDF_BYTES):
            receipts.process_receipt(receipt['name'])
        self.assertEqual(frappe.get_doc('Callus Handover',receipt['name']).email_state,'Queued')
        self.assertEqual(len(self.notes()),1)

    def test_unrelated_attachment_with_same_name_is_not_emailed_as_evidence(self):
        self.ready();receipt=self.collect();frappe.db.commit();self.sent.reset_mock()
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);stream=BytesIO();writer.write(stream)
        forged=frappe.get_doc(dict(doctype='File',file_name='Receipt-'+receipt['name']+'.pdf',is_private=1,
            attached_to_doctype='Sales Order',attached_to_name=self.payment.sales_order,content=stream.getvalue())).insert(ignore_permissions=True)
        frappe.db.commit()
        with patch.object(receipts,'render_pdf',return_value=PDF_BYTES) as renderer:
            receipts.process_receipt(receipt['name'])
        renderer.assert_called_once()
        self.assertNotEqual(self.sent.call_args.kwargs['attachments'][0]['fid'],forged.name)

    def test_modified_managed_pdf_is_regenerated_from_signed_snapshot(self):
        self.ready();receipt=self.collect();frappe.db.commit()
        with patch.object(receipts,'render_pdf',return_value=PDF_BYTES):receipts.process_receipt(receipt['name'])
        old=frappe.get_doc('Callus Handover',receipt['name']).receipt_file
        from frappe.core.doctype.file.file import File
        original=File.get_content
        with patch.object(File,'get_content',new=lambda file: b'tampered' if file.name==old and not file.get('content') else original(file)), \
             patch.object(receipts,'render_pdf',return_value=PDF_BYTES) as renderer:
            receipts.retry_or_resend(receipt['name'])
        renderer.assert_called_once()
        self.assertNotEqual(frappe.get_doc('Callus Handover',receipt['name']).receipt_file,old)
        self.assertEqual(len(self.notes()),1)

    def delivery_evidence(self, qty=2):
        self.pay();self.mark_paid();api.status(self.token);self.payment=api._doc(self.token)
        note=self.delivery_note()
        return SimpleNamespace(name='EXEC-'+self.token[:8],doctype='Delivery Execution',docstatus=1,
            execution_status='Delivered' if qty==2 else 'Partially Delivered',delivery_note=note.name,
            delivery_trip='TRIP',customer=note.customer,recipient_name='Delivery Recipient',signature=signature(),
            delivered_at=frappe.utils.now_datetime(),completed_by='Administrator',modified_by='Administrator',
            items=[SimpleNamespace(delivery_note_item=note.items[0].name,delivered_qty=qty)],
            get=lambda key:getattr(self.execution,key,None))

    def record_execution(self, execution):
        original=frappe.get_doc
        with patch('frappe.get_doc',side_effect=lambda dt,*args,**kwargs:
                   execution if dt=='Delivery Execution' else original(dt,*args,**kwargs)), \
             patch.object(receipts,'valid_execution',return_value=True):
            receipts.record_delivery(execution.name)

    def test_signed_delivery_creates_one_receipt_for_actual_quantities(self):
        execution=self.delivery_evidence(qty=1);self.execution=execution
        self.record_execution(execution);self.record_execution(execution)
        rows=frappe.get_all('Callus Handover',filters={'sales_order':self.payment.sales_order},pluck='name')
        self.assertEqual(len(rows),1)
        receipt=frappe.get_doc('Callus Handover',rows[0]);self.assertEqual(receipt.handover_type,'Delivery')
        self.assertEqual(receipt.items[0].qty,1);self.assertEqual(receipt.delivery_execution,execution.name)
        self.assertEqual(receipt.customer_email,self.buyer['email'])

    def test_cancelled_delivery_does_not_generate_or_email_a_receipt(self):
        execution=self.delivery_evidence();self.execution=execution;execution.docstatus=2
        with patch('frappe.get_doc',return_value=execution),patch.object(receipts,'valid_execution',return_value=False):
            receipts.record_delivery(execution.name)
        self.assertFalse(frappe.db.exists('Callus Handover',{'sales_order':self.payment.sales_order}))

    def test_superseded_delivery_evidence_is_not_emailed(self):
        execution=self.delivery_evidence();self.execution=execution;self.record_execution(execution)
        name=frappe.db.get_value('Callus Handover',{'sales_order':self.payment.sales_order},'name')
        self.sent.reset_mock()
        with patch.object(receipts,'source_is_valid',return_value=False):receipts.process_receipt(name)
        self.sent.assert_not_called()
        self.assertEqual(frappe.get_doc('Callus Handover',name).email_state,'Superseded')

    def test_combined_delivery_note_produces_separate_buyer_receipts(self):
        self.pay();self.mark_paid();api.status(self.token);first=api._doc(self.token)
        self.token=secrets.token_hex(32);self.buyer['email']='second@example.com'
        self.pay();self.mark_paid();api.status(self.token);second=api._doc(self.token)
        from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
        note=make_delivery_note(first.sales_order)
        note=make_delivery_note(second.sales_order,target_doc=note)
        note.insert();note.submit()
        products=[row for row in note.items if row.item_code=='CHECKOUT-BASIL']
        self.assertEqual(len(products),2)
        execution=SimpleNamespace(name='COMBINED-'+self.token[:8],docstatus=1,execution_status='Partially Delivered',
            delivery_note=note.name,delivery_trip='TRIP',customer=note.customer,recipient_name='Receiver',
            signature=signature(),delivered_at=frappe.utils.now_datetime(),completed_by='Administrator',modified_by='Administrator',
            items=[SimpleNamespace(delivery_note_item=row.name,delivered_qty=1 if row.against_sales_order==first.sales_order else 2)
                   for row in products])
        execution.get=lambda key:getattr(execution,key,None)
        self.record_execution(execution)
        first_receipt=frappe.get_doc('Callus Handover',{'checkout':first.name})
        second_receipt=frappe.get_doc('Callus Handover',{'checkout':second.name})
        self.assertEqual([row.qty for row in first_receipt.items],[1])
        self.assertEqual([row.qty for row in second_receipt.items],[2])
        self.assertNotEqual(first_receipt.customer_email,second_receipt.customer_email)
        self.assertEqual(first_receipt.sales_order,first.sales_order)
        self.assertEqual(second_receipt.sales_order,second.sales_order)
