"""Bolt tender and cashier-shift validation shared by accept and handover."""
import frappe


def context(settings):
    profile = frappe.get_doc('POS Profile', settings.pos_profile)
    mode = settings.get('payment_method') if hasattr(settings, 'get') else getattr(settings, 'payment_method', None)
    if not mode:
        frappe.throw('Select the Bolt Food payment method in Callus Bolt Settings before accepting orders.')
    if not any(row.mode_of_payment == mode for row in profile.payments):
        frappe.throw('Add the Bolt Food payment method to the Bolt POS Profile.')
    mop = frappe.get_doc('Mode of Payment', mode)
    if not mop.enabled or mop.type == 'Cash' or mode == profile.get('posa_cash_mode_of_payment'):
        frappe.throw('Bolt requires an enabled non-cash payment method, separate from the cash drawer.')
    accounts = [r.default_account for r in mop.accounts if r.company == settings.company]
    if len(accounts) != 1:
        frappe.throw('Configure one Bolt clearing account for this company in the payment method.')
    account = frappe.get_doc('Account', accounts[0])
    if (account.company != settings.company or account.is_group or account.disabled
            or account.account_type in ('Cash', 'Receivable', 'Payable') or account.root_type != 'Asset'
            or account.account_currency != 'EUR'):
        frappe.throw('Bolt requires an enabled EUR asset clearing account, not cash or a party account.')
    names = frappe.get_all('POS Opening Shift', filters={'user': frappe.session.user,
        'pos_profile': settings.pos_profile, 'company': settings.company, 'docstatus': 1,
        'status': 'Open'}, pluck='name', limit_page_length=2)
    if len(names) != 1:
        frappe.throw('Open one POS shift for your user on the Bolt POS Profile before accepting or handing over an order.')
    shift = frappe.get_doc('POS Opening Shift', names[0], for_update=True)
    if (shift.status != 'Open' or shift.docstatus != 1 or shift.user != frappe.session.user
            or shift.pos_profile != settings.pos_profile or shift.company != settings.company
            or shift.pos_closing_shift):
        frappe.throw('Your POS shift is closing or closed. Refresh the POS and open a shift before continuing.')
    return profile, shift, mode, account.name


def as_pos_invoice(mapped):
    """Use ERP's Sales Order mapper, rebuilding child rows as POS Invoice children."""
    invoice = frappe.new_doc('POS Invoice')
    for field in invoice.meta.fields:
        value = mapped.get(field.fieldname)
        if value is None:
            continue
        if field.fieldtype == 'Table':
            invoice.set(field.fieldname, [])
            columns = {df.fieldname for df in frappe.get_meta(field.options).fields}
            for row in value:
                invoice.append(field.fieldname, {k: v for k, v in row.as_dict().items() if k in columns})
        elif field.fieldtype not in ('Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button'):
            invoice.set(field.fieldname, value)
    return invoice


def validate_closing(doc, method=None):
    """Serialize Bolt handover with closing and reject a stale closing snapshot."""
    if not frappe.db.exists('DocType', 'Callus Bolt Settings'):
        return
    settings = frappe.get_single('Callus Bolt Settings')
    if not settings.enabled or not settings.get('two_way_enabled') or doc.pos_profile != settings.pos_profile:
        return
    frappe.get_doc('POS Opening Shift', doc.pos_opening_shift, for_update=True)
    use_pos = frappe.db.get_value('POS Profile', doc.pos_profile, 'create_pos_invoice_instead_of_sales_invoice')
    doctype = 'POS Invoice' if use_pos else 'Sales Invoice'
    field = 'pos_invoice' if use_pos else 'sales_invoice'
    extra = " and ifnull(consolidated_invoice, '') = ''" if use_pos else ''
    current = frappe.db.sql(f"select name from `tab{doctype}` where docstatus=1 and posa_pos_opening_shift=%s{extra} for update", (doc.pos_opening_shift,))
    if {row[0] for row in current} != {row.get(field) for row in doc.pos_transactions}:
        frappe.throw('Sales changed after this closing was opened. Refresh Close Shift to include all sales before submitting.')
