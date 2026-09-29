"""Portable, opt-in refresh of the existing sale emails and delivery rule.

No migration enables mail. Run explicitly on the intended site after a backup.
"""
from pathlib import Path
import frappe
from frappe.utils import validate_email_address

CUSTOMER = 'New Website Order - Customer'
BUSINESS = 'Website Sales Notifications Internally'
DELIVERY_RULE = 'Delivery Fee - Orders Under 35 Euros'
CONDITION = 'doc.docstatus == 1 and doc.customer_group == "Website" and not doc.is_return'

ADDRESS = '''{% if address %}{{ address.address_line1 | e }}<br>{% if address.address_line2 %}{{ address.address_line2 | e }}<br>{% endif %}{{ address.city | e }} {{ (address.pincode or '') | e }}<br>{{ address.country | e }}{% else %}Please contact the shop to confirm the address.{% endif %}'''

def email_template(audience):
    source=(Path(__file__).parent/'emails/order.html').read_text()
    if audience=='customer':
        values=dict(PREHEADER='Your Callus order details and what happens next.',EYEBROW='A LITTLE GREENER. A LITTLE HAPPIER.',TITLE='Thank you. Let good things grow.',
            INTRO='<p style="margin:0">Hello {{ doc.customer_name | e }},</p><p>Thank you for choosing Callus Garden Centre. We’ve received your order and our team will prepare your items with care.</p>',ITEM_HEADING='Your little collection of good things.',
            FULFILMENT='<h2 style="font-family:Georgia,serif;font-size:23px;font-weight:normal">What happens next?</h2>{% if is_delivery %}<p>Our team will contact you to arrange delivery. We’ll confirm the timing with you before dispatch.</p><p><strong>Delivery address</strong><br>'+ADDRESS+'</p>{% else %}<p>We’ll contact you when your order is ready to collect. Please wait for that confirmation before visiting.</p><p><strong>Collect from Callus Garden Centre</strong><br>Mqabba Road, Siġġiewi, Malta.</p>{% endif %}',
            CONTACT='<p>Need to change something or ask a question? Reply to this email or contact <a href="mailto:sales@callusgardencentre.com" style="color:#244c3a">sales@callusgardencentre.com</a>, quoting your order number.</p>',CLOSING='With care,<br><strong>The Callus team</strong>')
    elif audience=='business':
        values=dict(PREHEADER='New website order: quantities, customer details and fulfilment instructions.',EYEBROW='CALLUS · WEBSITE ORDER',TITLE='A new order to prepare.',
            INTRO='<p style="margin:0">Hello team,</p><p>A website order from <strong>{{ doc.customer_name | e }}</strong> is ready for preparation. Review the order and payment record, then pick and check the items below.</p>',ITEM_HEADING='Pick &amp; prepare.',
            FULFILMENT='<h2 style="font-family:Georgia,serif;font-size:23px;font-weight:normal">{{ "Arrange delivery" if is_delivery else "Prepare for collection" }}</h2>{% if is_delivery %}<p>Check every item, pack securely and call the customer to agree delivery before dispatch.</p><p><strong>Delivery address</strong><br>'+ADDRESS+'</p>{% else %}<p>Check every item and keep the order together. Contact the customer only when it is ready to collect.</p>{% endif %}',
            CONTACT='<p><strong>Customer:</strong> {{ doc.customer_name | e }}<br><strong>Email:</strong> {{ (doc.contact_email or "Not supplied") | e }}<br><strong>Phone:</strong> {{ (doc.contact_mobile or "Not supplied") | e }}</p><p><a href="{{ frappe.utils.get_url() }}/app/{{ "sales-order" if order_name else "sales-invoice" }}/{{ (order_name or doc.name) | urlencode }}" style="color:#244c3a">Open the {{ "sales order" if order_name else "invoice" }} →</a></p>',CLOSING='Thank you for taking care of every order.<br><strong>Callus Garden Centre</strong>')
    else:
        raise ValueError('Unknown email audience')
    for key,value in values.items():source=source.replace('__'+key+'__',value)
    return source


def install(test_recipient=None, enable=False):
    """Preserve business recipients; optionally route both UAT templates to one tester."""
    frappe.only_for('System Manager')
    if test_recipient and not validate_email_address(test_recipient):
        frappe.throw('A valid UAT test recipient is required.')
    for name,audience in [(CUSTOMER,'customer'),(BUSINESS,'business')]:
        doc=frappe.get_doc('Notification',name)
        doc.message=email_template(audience)
        doc.message_type="HTML"
        doc.subject=('Your Callus order {{ doc.name }} — thank you!' if audience=='customer' else 'Prepare website order {{ doc.name }} — {{ doc.customer_name }}')
        doc.condition=CONDITION
        doc.enabled=int(bool(enable))
        if test_recipient:
            doc.set('recipients',[{'cc':test_recipient}])
        elif audience=='customer':
            # Automated invoices are owned by staff/system users, not the buyer.
            doc.set('recipients',[{'receiver_by_document_field':'contact_email'}])
        doc.save()
    settings=frappe.get_single('Callus Checkout Settings')
    rule=frappe.get_doc('Shipping Rule',DELIVERY_RULE)
    shop=frappe.get_single('Webshop Settings')
    if rule.disabled or rule.company!=shop.company or rule.shipping_rule_type!='Selling':
        frappe.throw('Review the existing delivery rule before enabling it.')
    settings.delivery_rule=rule.name
    settings.save(ignore_permissions=True)


@frappe.whitelist(methods=['POST'])
def configure_delivery(rule_name: str):
    """Allow a manager to select an existing Malta rule without editing payment settings."""
    frappe.only_for('System Manager')
    rule=frappe.get_doc('Shipping Rule',rule_name)
    shop=frappe.get_single('Webshop Settings')
    if rule.disabled or rule.company!=shop.company or rule.shipping_rule_type!='Selling':
        frappe.throw('Choose an enabled selling rule for the shop company.')
    if rule.countries and 'Malta' not in [row.country for row in rule.countries]:
        frappe.throw('The selected rule does not cover Malta.')
    settings=frappe.get_single('Callus Checkout Settings')
    settings.delivery_rule=rule.name
    settings.save(ignore_permissions=True)
    return {'delivery_rule':rule.name}
