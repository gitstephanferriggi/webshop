"""Pure Bolt catalogue mapping. Website publication never gates Bolt selection."""
from decimal import Decimal, ROUND_FLOOR
import hashlib
import re
from urllib.parse import urljoin, urlparse


def category_id(group):
    return 'erp-' + hashlib.sha256(group.encode()).hexdigest()[:24]


def available_stock(actual, reserved):
    value = max(Decimal('0'), Decimal(str(actual or 0)) - Decimal(str(reserved or 0)))
    if not value.is_finite():
        raise ValueError('Invalid stock quantity')
    return min(10000, int(value.to_integral_value(rounding=ROUND_FLOOR)))


def build(items, website_items, prices, bins, provider_id, asset_base):
    """Return a provider-scoped catalogue plus reasons for excluded opt-ins.

    Caller supplies current, unambiguous prices in the agreed gross EUR price list.
    Quantities are whole pieces only. Excluded opt-ins must be withdrawn by sync.
    """
    products, price_rows, stocks, excluded = [], [], [], []
    groups = set()
    for web in website_items:
        if not web.get('custom_bolt_enabled'):
            continue
        code = web['item_code']
        item, price = items.get(code), prices.get(code)
        reason = None
        if not item or item.get('disabled') or not item.get('is_sales_item') or item.get('has_variants'):
            reason = 'Item is disabled, missing or not a saleable item'
        elif item.get('stock_uom') not in ('Pcs', 'Nos', 'Piece', 'Unit'):
            reason = 'Unsupported selling unit; explicit measurement mapping required'
        elif price is None or not Decimal(str(price)).is_finite() or Decimal(str(price)) <= 0:
            reason = 'Missing or ambiguous positive EUR selling price'
        if reason:
            excluded.append({'item_code': code, 'reason': reason})
            continue
        group = item['item_group']
        groups.add(group)
        desc = web.get('short_description') or web.get('web_long_description') or ''
        product = {'sku': code, 'name': {'en-US': web.get('web_item_name') or item['item_name']},
                   'category_external_ids': [category_id(group)], 'provider_ids': [provider_id],
                   'selling_unit': 'piece', 'description': {'en-US': re.sub('<[^>]*>', '', desc).strip()}}
        image = web.get('website_image') or ''
        if image and not image.startswith('/private/'):
            image = urljoin(asset_base, image)
            if urlparse(image).scheme == 'https':
                product['image_url'] = image
        products.append(product)
        price_rows.append({'sku': code, 'base_selling_price': float(Decimal(str(price)))})
        stock = bins.get(code, {})
        stocks.append({'sku': code, 'quantity': available_stock(stock.get('actual_qty'), stock.get('reserved_qty')), 'selling_unit': 'piece'})
    categories = [{'external_id': 'callus-products', 'name': {'en-US': 'Callus Garden Centre'},
                   'sub_categories': [{'external_id': category_id(g), 'name': {'en-US': g},
                                       'external_provider_ids': [provider_id]} for g in sorted(groups)]}]
    return {'products': products, 'categories': categories, 'prices': price_rows,
            'stocks': stocks, 'excluded': excluded}
