"""Real draft-trip and stop tests; the shared fixtures intercept Stripe and SMTP."""
import unittest
from unittest.mock import patch
import frappe
from frappe.utils import now_datetime, nowdate
from hospice_integration import HospiceIntegrationTests
from webshop.callus_storefront import checkout, hospice_trips as trips


class HospiceTripTests(HospiceIntegrationTests):
    @classmethod
    def setUpClass(cls):
        HospiceIntegrationTests.setUpClass()
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
        create_custom_fields({'Delivery Trip':[
            dict(fieldname='custom_delivery_trip_status',label='Delivery Trip Status',fieldtype='Data'),
            dict(fieldname='custom_is_bowser_trip',label='Is Bowser Trip',fieldtype='Check')]})
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.pay();self.mark_paid();checkout.status(self.token)
        self.payment=checkout._doc(self.token);self.note=self.delivery_note()
        self.order=frappe.get_doc('Sales Order',self.payment.sales_order)
        self.driver=frappe.get_doc(dict(doctype='Driver',full_name='Hospice Trip Test '+self.token[:8],status='Active')).insert().name
        self.vehicle=frappe.get_doc(dict(doctype='Vehicle',license_plate='HT-'+self.token[:8],make='Test',model='Test',
            last_odometer=0,acquisition_date=nowdate(),uom='Litre',fuel_type='Petrol')).insert().name

    def create(self, **kwargs):
        return trips.add_to_trip(self.order.name,self.note.name,driver=self.driver,vehicle=self.vehicle,
                                 departure_time=str(now_datetime()),**kwargs)

    def test_create_draft_and_duplicate_protection(self):
        self.assertEqual(trips.trip_options(self.order.name)['delivery_notes'],[self.note.name])
        trip=frappe.get_doc('Delivery Trip',self.create()['name'])
        self.assertEqual(trip.docstatus,0);self.assertEqual(len(trip.delivery_stops),1)
        self.assertEqual(trip.delivery_stops[0].delivery_note,self.note.name)
        self.assertEqual(trip.delivery_stops[0].address,self.order.shipping_address_name)
        self.assertEqual(trip.delivery_stops[0].contact,self.order.contact_person)
        self.assertEqual(frappe.db.get_value('Delivery Note',self.note.name,'docstatus'),1)
        self.assertTrue(trips.add_to_trip(self.order.name,self.note.name,trip_name=trip.name)['already_added'])
        self.assertEqual(len(frappe.get_doc('Delivery Trip',trip.name).delivery_stops),1)
        with self.assertRaises(frappe.ValidationError):self.create()
        with self.assertRaises(frappe.ValidationError):trips.trip_options(self.order.name)

    def test_add_to_existing_draft_preserves_other_stop(self):
        trip=frappe.get_doc('Delivery Trip',self.create()['name'])
        other=frappe.copy_doc(self.note)
        for row in other.items:row.against_sales_order=None;row.so_detail=None
        other.insert();other.submit()
        trip.set('delivery_stops',[])
        trip.append('delivery_stops',dict(delivery_note=other.name,customer=self.order.customer,
            address=self.order.shipping_address_name,contact=self.order.contact_person))
        trip.save()
        trips.add_to_trip(self.order.name,self.note.name,trip_name=trip.name)
        saved=frappe.get_doc('Delivery Trip',trip.name)
        self.assertEqual([s.delivery_note for s in saved.delivery_stops],[other.name,self.note.name])
        self.assertEqual(saved.driver,self.driver);self.assertEqual(saved.docstatus,0)

    def test_wrong_company_submitted_and_bowser_trips_rejected(self):
        trip=frappe.get_doc('Delivery Trip',self.create()['name']);get_doc=frappe.get_doc
        for field,value in [('docstatus',1),('custom_is_bowser_trip',1),('company','Other Company'),('custom_delivery_trip_status','Completed')]:
            original=trip.get(field)
            with patch.object(trips.frappe,'get_doc',side_effect=lambda dt,n=None: trip if dt=='Delivery Trip' else get_doc(dt,n)):
                trip.set(field,value)
                with self.assertRaises(frappe.ValidationError):trips.add_to_trip(self.order.name,self.note.name,trip_name=trip.name)
                trip.set(field,original)

    def test_permissions_and_missing_schedule(self):
        with self.assertRaises(frappe.ValidationError):trips.add_to_trip(self.order.name,self.note.name)
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):trips.trip_options(self.order.name)
        with self.assertRaises(frappe.PermissionError):self.create()

    def test_pickup_and_unpaid_orders_rejected(self):
        with patch.object(trips.hospice_fulfilment,'fulfilment',return_value='Pickup'):
            with self.assertRaises(frappe.ValidationError):self.create()
        with patch.object(trips.hospice_fulfilment,'checkout_for',return_value=frappe._dict(status='Expired')):
            with self.assertRaises(frappe.ValidationError):self.create()

    def test_wrong_note_missing_address_and_combined_notes_rejected(self):
        with self.assertRaises(frappe.ValidationError):trips.add_to_trip(self.order.name,'invalid-note')
        self.order.shipping_address_name=None;self.note.shipping_address_name=None
        with self.assertRaises(frappe.ValidationError):trips.stop_for(self.order,self.note)
        self.note.items[0].against_sales_order='OTHER-ORDER'
        with self.assertRaises(frappe.ValidationError):trips.stop_for(self.order,self.note)


# Reuse fixtures without rerunning unrelated inherited campaign tests.
for name in list(dir(HospiceTripTests)):
    if name.startswith('test_') and name not in HospiceTripTests.__dict__:setattr(HospiceTripTests,name,None)
