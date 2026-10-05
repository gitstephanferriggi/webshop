"""Validate Bolt basket amounts before creating any ERP sales document."""
from decimal import Decimal, InvalidOperation
import hashlib


def money(value):
    if isinstance(value, bool):
        raise ValueError('Invalid amount')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid amount') from None
    if not result.is_finite() or result < 0:
        raise ValueError('Invalid amount')
    return result


def order_key(provider_id, order_id):
    return hashlib.sha256((str(provider_id)+'\0'+str(order_id)).encode()).hexdigest()


def sales_lines(payload, item_lookup):
    """Map only supported piece-based baskets. Reject ambiguity rather than misbill.

    Bolt delivery/service fees belong to Bolt unless an explicit ERP fee mapping
    is supplied by a future implementation. They are not product sales here.
    """
    total = payload['total_order_price']
    if total.get('currency','').upper() != 'EUR':
        raise ValueError('Only EUR baskets are configured')
    rows=[];amount=Decimal('0')
    for line in payload['items']:
        if line.get('options') or line.get('measure'):
            raise ValueError('Measured items and options need manual basket review')
        item=item_lookup(line['sku'])
        if not item or item.get('disabled') or not item.get('is_sales_item'):
            raise ValueError('Unknown or unavailable SKU: '+line['sku'])
        quantity=money(line['qty'])
        if quantity <= 0 or quantity != quantity.to_integral_value():
            raise ValueError('Expected a positive whole-piece quantity')
        unit=line.get('unit_item_price') or {}
        final=line.get('total_item_price') or {}
        if unit.get('currency','').upper()!='EUR' or final.get('currency','').upper()!='EUR':
            raise ValueError('Missing or inconsistent item currency')
        rate=money(unit.get('value'));line_total=money(final.get('value'))
        if (quantity*rate).quantize(Decimal('.01')) != line_total.quantize(Decimal('.01')):
            raise ValueError('Item quantity and price do not reconcile')
        amount+=line_total
        rows.append({'item_code':line['sku'],'qty':int(quantity),'rate':float(rate),
                     'uom':item['stock_uom'],'warehouse':'Garden Center - BGL'})
    if not rows or amount.quantize(Decimal('.01')) != money(total['value']).quantize(Decimal('.01')):
        raise ValueError('Basket total requires fee/discount review')
    return rows
