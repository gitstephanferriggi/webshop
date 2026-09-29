# Executed by Builder's restricted data-script runner. Read-only, public fields only.
settings = frappe.get_doc('Webshop Settings')
data.catalogue = []
data.shop_enabled = bool(settings.enabled)
data.checkout_enabled = False  # Guest order/payment backend must pass separate acceptance tests.
data.currency = 'EUR'
data.product_code = frappe.form_dict.get('item_code', '')
data.collection_slug = frappe.form_dict.get('name', '')
if settings.enabled and not (settings.login_required_to_view_products and frappe.session.user == 'Guest'):
    website_items = frappe.get_all('Website Item', filters={'published': 1}, fields=['name', 'item_code', 'web_item_name', 'item_group', 'website_image', 'description', 'short_description', 'web_long_description', 'website_warehouse', 'creation'], limit_page_length=10000)
    codes = [item.item_code for item in website_items]
    items = frappe.get_all('Item', filters={'name': ['in', codes], 'disabled': 0}, fields=['name', 'is_stock_item', 'stock_uom'], limit_page_length=10000) if codes else []
    active = {item.name: item for item in items}
    price_rows = frappe.get_all('Item Price', filters={'item_code': ['in', codes], 'price_list': settings.price_list}, fields=['item_code', 'price_list_rate', 'currency', 'valid_from', 'valid_upto', 'uom', 'customer', 'supplier', 'batch_no'], order_by='valid_from desc, modified desc', limit_page_length=30000) if codes else []
    prices = {}
    today = frappe.utils.getdate()
    for row in price_rows:
        if row.item_code in prices or row.customer or row.supplier or row.batch_no:
            continue
        if row.valid_from and frappe.utils.getdate(row.valid_from) > today:
            continue
        if row.valid_upto and frappe.utils.getdate(row.valid_upto) < today:
            continue
        if row.uom and row.item_code in active and row.uom != active[row.item_code].stock_uom:
            continue
        prices[row.item_code] = row
    stock_rows = frappe.get_all('Bin', filters={'item_code': ['in', codes]}, fields=['item_code', 'warehouse', 'actual_qty', 'reserved_qty'], limit_page_length=50000) if codes else []
    stock = {}
    for row in stock_rows:
        stock[row.item_code + '|' + row.warehouse] = max(0, (row.actual_qty or 0) - (row.reserved_qty or 0))
    groups = frappe.get_all('Item Group', fields=['name', 'parent_item_group'], limit_page_length=5000)
    parents = {group.name: group.parent_item_group for group in groups}
    # Use Sales Invoices only: consolidated POS sales must not be counted twice.
    sales = frappe.get_all('Sales Invoice', filters={'docstatus': 1, 'is_return': 0, 'posting_date': ['>=', frappe.utils.add_days(today, -90)]}, fields=['`tabSales Invoice Item`.item_code', 'sum(`tabSales Invoice Item`.qty) as units'], group_by='`tabSales Invoice Item`.item_code', order_by='units desc', limit_page_length=10000)
    ranks = {}
    for index, sale in enumerate(sales):
        if sale.units and sale.units > 0:
            ranks[sale.item_code] = index + 1
    for item in website_items:
        if item.item_code not in active:
            continue
        ancestor = item.item_group
        trail = [ancestor]
        for depth in range(12):
            ancestor = parents.get(ancestor)
            if not ancestor or ancestor in trail:
                break
            trail.append(ancestor)
        category = 'outdoor'
        if 'House Plants' in trail:
            category = 'indoor'
        elif 'Pots & Planters' in trail:
            category = 'pots'
        elif 'Herbs & Vegetables' in trail or 'Seeds & Bulbs' in trail or 'Seeds' in trail:
            category = 'grow'
        elif 'Irrigation' in trail or 'Garden Tools' in trail:
            category = 'tools'
        elif 'Home Accessories & Candles' in trail or 'Artificial Plants' in trail or 'Decorations' in trail:
            category = 'gifts'
        elif 'Floristry' in trail or 'Occasions' in trail or 'Flower' in item.item_group and ('Bouquet' in item.item_group or 'Arrangement' in item.item_group or 'Cut' in item.item_group):
            category = 'flowers'
        elif 'Garden Accessories & Utilities' in trail or 'Soil & Substrate' in trail or 'Aggregates & Mulching' in trail:
            category = 'care'
        price = prices.get(item.item_code)
        quantity = stock.get(item.item_code + '|' + (item.website_warehouse or ''), 0)
        non_stock = not active[item.item_code].is_stock_item
        visible_price = bool(settings.show_price and not (frappe.session.user == 'Guest' and settings.hide_price_for_guest))
        data.catalogue.append({'id': item.item_code, 'web_id': item.name, 'name': item.web_item_name, 'group': item.item_group, 'category': category, 'image': item.website_image or '', 'description': (item.web_long_description or item.short_description or item.description or '') if data.product_code in (item.item_code, item.name) else '', 'price': price.price_list_rate if price and visible_price else None, 'currency': price.currency if price else 'EUR', 'available': quantity > 0, 'quantity': quantity, 'on_request': non_stock, 'rank': ranks.get(item.item_code, 999999), 'created': str(item.creation)[:10], 'uom': active[item.item_code].stock_uom})

for product in data.catalogue:
    if data.product_code in (product["id"], product["web_id"]):
        data.metatags = {"title": product["name"] + " | Callus Garden Centre", "description": product["name"] + " at Callus Garden Centre, Siġġiewi, Malta.", "image": product["image"]}
        break
