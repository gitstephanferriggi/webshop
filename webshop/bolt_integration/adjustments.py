"""Whole-piece adjustments and reconciliation against Bolt's final basket."""
from collections import defaultdict
from decimal import Decimal
from webshop.bolt_integration.orders import money
from webshop.bolt_integration.workflow import validate_picks, numeric_order_id


def build_adjustment(lines, quantities, replacements, catalogue):
    picks = validate_picks(lines, quantities)
    if not isinstance(replacements, dict) or set(replacements) - {r['id'] for r in lines}:
        raise ValueError('Replacement rows do not match the order.')
    outgoing, expected = {}, {}
    changed = False
    for row in lines:
        qty = picks[row['id']]
        if qty != int(qty):
            raise ValueError('Bolt adjustments require whole-piece quantities.')
        qty = int(qty)
        code = replacements.get(row['id']) or row['code']
        if not isinstance(code, str):
            raise ValueError('Choose a valid replacement.')
        changed |= qty != row['qty'] or code != row['code']
        rate = money(row['rate'])
        if code != row['code']:
            if code not in catalogue or money(catalogue[code]) > rate:
                raise ValueError('Choose a published Bolt replacement with an equal or lower price.')
            rate = money(catalogue[code])
        if not qty:
            continue
        if code in expected and money(expected[code]['rate']) != rate:
            raise ValueError('Repeated SKU has different prices. Manager review is required.')
        expected.setdefault(code, {'qty': 0, 'rate': float(rate)})['qty'] += qty
        if expected[code]['qty'] > 10000:
            raise ValueError('Quantity exceeds Bolt limit.')
        outgoing.setdefault(code, {'sku': code, 'amount': 0})['amount'] += qty
        if code != row['code']:
            outgoing[code].setdefault('replacement_for', []).append({
                'replaced_sku': row['code'], 'replaced_quantity': qty, 'picked_quantity': qty})
    if not changed:
        raise ValueError('No adjustment was made. Use Mark ready for courier.')
    if not outgoing:
        raise ValueError('An empty basket cannot be marked ready. Contact Bolt to cancel the accepted order.')
    for item in outgoing.values():
        if 'replacement_for' in item:
            totals = defaultdict(int)
            for replacement in item['replacement_for']:
                totals[replacement['replaced_sku']] += replacement['picked_quantity']
            item['replacement_for'] = [{'replaced_sku': code, 'replaced_quantity': qty, 'picked_quantity': qty}
                                       for code, qty in totals.items()]
    total = sum((money(r['rate']) * r['qty']).quantize(Decimal('.01')) for r in expected.values())
    return {'items': list(outgoing.values()), 'expected': expected, 'expected_total': float(total)}


def confirmed_basket(basket, order_id, expected, original_total):
    if not isinstance(basket, dict) or numeric_order_id(basket.get('order_id')) != numeric_order_id(order_id):
        raise ValueError('Bolt returned a different order.')
    basket_total = basket.get('total_price')
    if isinstance(basket_total, dict):
        if str(basket_total.get('currency', '')).upper() != 'EUR':
            raise ValueError('Bolt final basket currency must be EUR.')
        basket_total = basket_total.get('value')
    rows, seen, total = [], set(), Decimal('0')
    for item in basket.get('items', []):
        code = item.get('sku')
        rate = money(item.get('price'))
        amount = money(item.get('total_price'))
        picked = item.get('picked_amount')
        if picked is None:
            # Bolt can omit picked_amount for pieces. Infer only when its
            # unit price and line total prove an exact whole-piece quantity.
            if item.get('selling_unit') != 'piece' or rate <= 0:
                raise ValueError('Bolt quantity cannot be verified.')
            qty = amount / rate
            if qty != qty.to_integral_value():
                raise ValueError('Bolt quantity is not a whole number.')
        else:
            qty = money(picked)
        if qty == 0:
            if amount != 0:
                raise ValueError('A removed item still has a charge.')
            continue
        if code not in expected or code in seen or item.get('selling_unit') != 'piece':
            raise ValueError('Unexpected or duplicate SKU/selling unit in Bolt basket.')
        if qty != expected[code]['qty'] or rate != money(expected[code]['rate']):
            raise ValueError('Bolt quantities or prices differ from the approved adjustment.')
        if (qty * rate).quantize(Decimal('.01')) != amount.quantize(Decimal('.01')):
            raise ValueError('Bolt line total does not reconcile.')
        rows.append({'sku': code, 'qty': int(qty), 'unit_item_price': {'value': float(rate), 'currency': 'EUR'},
                     'total_item_price': {'value': float(amount), 'currency': 'EUR'}})
        seen.add(code); total += amount
    if seen != set(expected) or not rows or total != money(basket_total) or total > money(original_total):
        raise ValueError('Bolt final basket total does not reconcile; handover remains blocked.')
    return {'items': rows, 'total_order_price': {'value': float(total), 'currency': 'EUR'}}
