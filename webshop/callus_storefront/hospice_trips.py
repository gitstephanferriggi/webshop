"""Plan a paid Hospice delivery from its Sales Order without releasing a trip."""
import frappe
from frappe.utils import get_datetime, now_datetime

from webshop.callus_storefront import hospice_fulfilment


def delivery_order(order_name):
    order = frappe.get_doc('Sales Order', order_name)
    order.check_permission('write')
    payment = hospice_fulfilment.checkout_for(order_name)
    if (order.docstatus != 1 or not order.get('custom_hospice_order') or not payment
            or payment.status != 'Paid' or hospice_fulfilment.fulfilment(order, payment) != 'Delivery'):
        frappe.throw('Choose a paid, submitted Hospice delivery order.')
    if hospice_fulfilment.progress_for(order, payment)['delivery_state'] != 'Ready for dispatch':
        frappe.throw('This order must be ready for dispatch before planning its delivery.')
    return order


def delivery_notes(order):
    return frappe.db.sql('''SELECT DISTINCT d.name FROM `tabDelivery Note` d
        JOIN `tabDelivery Note Item` i ON i.parent=d.name
        WHERE i.against_sales_order=%s AND d.docstatus=1 AND d.is_return=0
        AND d.company=%s AND d.customer=%s ORDER BY d.name''',
        (order.name, order.company, order.customer), pluck=True)


def assignments(note):
    return frappe.db.sql('''SELECT DISTINCT t.name FROM `tabDelivery Trip` t
        JOIN `tabDelivery Stop` s ON s.parent=t.name AND s.parenttype='Delivery Trip'
        WHERE s.delivery_note=%s AND t.docstatus<2
        AND IFNULL(t.custom_delivery_trip_status, '') != 'Cancelled' ''', note, pluck=True)


@frappe.whitelist(methods=['POST'])
def trip_options(order_name):
    order = delivery_order(order_name)
    notes = []
    for name in delivery_notes(order):
        note = frappe.get_doc('Delivery Note', name)
        if frappe.has_permission('Delivery Note', 'read', doc=note) and not assignments(name):
            notes.append(name)
    if not notes:
        frappe.throw('No unassigned submitted Delivery Note is available. Check the order’s Delivery Notes and trips.')
    return dict(company=order.company, delivery_notes=notes, departure_time=now_datetime())


def stop_for(order, note):
    if any(row.against_sales_order != order.name for row in note.items):
        frappe.throw('This Delivery Note includes other orders. Plan the combined delivery from Delivery Trip.')
    # Never look up a default address/contact on the shared cash customer.
    address = note.shipping_address_name or order.shipping_address_name
    contact = note.contact_person or order.contact_person
    if not address or not contact:
        frappe.throw('Set this order’s delivery address and contact before planning its trip.')
    return dict(delivery_note=note.name, customer=note.customer, address=address,
                contact=contact, grand_total=note.grand_total)


@frappe.whitelist(methods=['POST'])
def add_to_trip(order_name, delivery_note, trip_name=None, driver=None, vehicle=None, departure_time=None):
    order = delivery_order(order_name)
    # Lock the stock document first so concurrent clicks cannot create two trips.
    frappe.db.sql('SELECT name FROM `tabDelivery Note` WHERE name=%s FOR UPDATE', delivery_note)
    if delivery_note not in delivery_notes(order):
        frappe.throw('Choose a submitted Delivery Note belonging to this order.')
    note = frappe.get_doc('Delivery Note', delivery_note)
    note.check_permission('read')
    linked = assignments(delivery_note)
    if trip_name:
        frappe.db.sql('SELECT name FROM `tabDelivery Trip` WHERE name=%s FOR UPDATE', trip_name)
        trip = frappe.get_doc('Delivery Trip', trip_name)
        trip.check_permission('write')
        if (trip.docstatus != 0 or trip.company != order.company or trip.get('custom_is_bowser_trip')
                or trip.get('custom_delivery_trip_status') not in (None, '', 'Draft')):
            frappe.throw('Choose a normal draft delivery trip for the same company.')
        if linked == [trip.name] and any(s.delivery_note == note.name for s in trip.delivery_stops):
            return dict(name=trip.name, already_added=True)
    else:
        trip = frappe.new_doc('Delivery Trip')
        trip.check_permission('create')
        if not driver or not vehicle or not departure_time:
            frappe.throw('Choose a driver, vehicle and departure time for the new draft trip.')
        trip.update(dict(company=order.company, driver=driver, vehicle=vehicle,
                         departure_time=get_datetime(departure_time)))
    if linked:
        frappe.throw('This Delivery Note is already assigned to a draft or submitted delivery trip.')
    trip.append('delivery_stops', stop_for(order, note))
    trip.save()
    return dict(name=trip.name, already_added=False)
