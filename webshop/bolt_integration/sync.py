"""Resumable catalogue synchronisation, scoped to one configured Bolt provider."""
import json
import hashlib
from collections import defaultdict
from urllib.parse import urlparse
import frappe
from frappe.utils import nowdate, get_url
from webshop.bolt_integration.catalogue import build
from webshop.bolt_integration.client import request


def snapshot(s):
    web=frappe.get_all('Website Item',filters={'custom_bolt_enabled':1},fields=['item_code','web_item_name','short_description','web_long_description','website_image','custom_bolt_enabled'])
    codes=[x.item_code for x in web]
    if not codes:
        return {'products':[],'categories':[],'prices':[],'stocks':[],'excluded':[]}
    items={x.name:x for x in frappe.get_all('Item',filters={'name':['in',codes]},fields=['name','item_name','item_group','stock_uom','disabled','is_sales_item','has_variants'])}
    bins={x.item_code:x for x in frappe.get_all('Bin',filters={'item_code':['in',codes],'warehouse':'Garden Center - BGL'},fields=['item_code','actual_qty','reserved_qty'])}
    candidates=defaultdict(list)
    for p in frappe.get_all('Item Price',filters={'item_code':['in',codes],'price_list':s.price_list,'currency':'EUR'},fields=['item_code','price_list_rate','uom','valid_from','valid_upto','customer','supplier','batch_no','packing_unit']):
        if p.customer or p.supplier or p.batch_no or (p.packing_unit or 1)!=1:
            continue
        if p.uom and p.uom!=items[p.item_code].stock_uom:
            continue
        if (p.valid_from and str(p.valid_from)>nowdate()) or (p.valid_upto and str(p.valid_upto)<nowdate()):
            continue
        candidates[p.item_code].append(p.price_list_rate)
    prices={k:v[0] for k,v in candidates.items() if len(v)==1}
    result=build(items,web,prices,bins,s.provider_id,get_url())
    for product in result['products']:
        product['vat_tag']=s.vat_tag
    return result


def tick():
    s=frappe.get_single('Callus Bolt Settings')
    if not s.enabled or not s.sync_catalogue:
        return
    if urlparse(get_url()).hostname!=s.site_hostname:
        return
    # One worker owns each tick; network stages resume on later scheduler ticks.
    with frappe.cache().lock('callus-bolt-catalogue',timeout=240,blocking_timeout=1):
        try:
            step(s)
            frappe.db.commit()
        except Exception as exc:
            frappe.db.rollback()
            frappe.db.set_single_value('Callus Bolt Settings',{'sync_phase':'Review','sync_error':str(exc)[:1000]})
            frappe.db.commit()
            frappe.log_error(title='Bolt catalogue requires review',message=frappe.get_traceback())


def step(s):
    if not all([s.region_id,s.provider_id,s.integrator_id,s.secret_key,s.vat_tag,s.price_list]):
        frappe.throw('Complete Bolt catalogue settings')
    region={'region_id':int(s.region_id)}
    phase=s.sync_phase or 'Idle'
    data=json.loads(s.sync_snapshot or '{}')
    def call(path,payload):return request(s,path,payload)
    def save(phase,**values):
        values['sync_phase']=phase
        frappe.db.set_single_value('Callus Bolt Settings',values)
    if phase=='Review':
        return
    if phase=='Idle':
        data=snapshot(s)
        previous=json.loads(s.last_synced_skus or '[]')
        current=[p['sku'] for p in data['products']]
        data['removed']=sorted(set(previous)-set(current))
        if data['excluded']:
            frappe.throw('Selected products need mapping review: '+json.dumps(data['excluded'])[:700])
        data['catalogue_hash']=hashlib.sha256(json.dumps({'products':data['products'],'categories':data['categories']},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        # An unchanged catalogue only needs price and quantity refreshes.
        if not data['removed'] and data['catalogue_hash']==s.last_catalogue_hash:
            if data['prices']:
                call('/pim/v1/products/prices/import',dict(region,provider_ids=[s.provider_id],price_list={'currency':'EUR','skus':data['prices']}))
                result=call('/genericClient/updateMenuQuantity',{'provider_id':s.provider_id,'sku_quantities':data['stocks']})
                if result.get('affected_skus')!=len(data['stocks']):
                    frappe.throw('Not all selected products received stock')
            save('Idle',last_sync=frappe.utils.now_datetime(),sync_error='')
            return
        # Withdraw unchecked items first. Never leave their stale non-zero stock.
        if data['removed']:
            result=call('/genericClient/updateMenuQuantity',{'provider_id':s.provider_id,'sku_quantities':[{'sku':sku,'quantity':0} for sku in data['removed']]})
            if result.get('affected_skus')!=len(data['removed']):
                frappe.throw('Not all removed products had stock withdrawn')
        state=call('/pim/v1/products/import/status/retrieve',region)['state']
        if state!='idle':
            frappe.throw('Another Bolt product import is active; review before replacing it')
        if not current and not previous:
            return
        if data['categories']:
            call('/pim/v1/categoryTree/set',dict(region,categories=data['categories']))
        if data['products']:
            call('/pim/v1/products/import/create',dict(region,products=data['products']))
            phase='Product validation'
        else:
            phase='Remove products'
        save(phase,sync_snapshot=json.dumps(data),sync_error='')
    elif phase in ('Product validation','Removal validation'):
        state=call('/pim/v1/products/import/status/retrieve',region)
        if state.get('errors') or state.get('warnings') or state['state']=='failed':
            frappe.throw('Bolt import validation needs review: '+json.dumps(state)[:700])
        if state['state']=='waiting_for_apply':
            call('/pim/v1/products/import/apply',region)
            save('Product applying' if phase=='Product validation' else 'Removal applying')
    elif phase in ('Product applying','Removal applying'):
        state=call('/pim/v1/products/import/status/retrieve',region)
        if state.get('errors') or state['state']=='failed':
            frappe.throw('Bolt import application failed')
        if state['state']=='idle':
            save('Remove products' if phase=='Product applying' else 'Prices and stock')
    elif phase=='Remove products':
        if data['removed']:
            call('/pim/v1/products/import/edit',dict(region,products=[{'sku':sku,'provider_ids':[]} for sku in data['removed']]))
            save('Removal validation')
        else:
            save('Prices and stock')
    elif phase=='Prices and stock':
        if data['prices']:
            call('/pim/v1/products/prices/import',dict(region,provider_ids=[s.provider_id],price_list={'currency':'EUR','skus':data['prices']}))
            result=call('/genericClient/updateMenuQuantity',{'provider_id':s.provider_id,'sku_quantities':data['stocks']})
            if result.get('affected_skus')!=len(data['stocks']):
                frappe.throw('Not all selected products received stock')
        state=call('/pim/v1/menu/drafts/state/retrieve',region)['state']
        if state!='no_draft':
            frappe.throw('Another menu draft exists; manual review required')
        call('/pim/v1/menu/drafts/create',dict(region,provider_ids=[s.provider_id]))
        save('Menu validation')
    elif phase=='Menu validation':
        state=call('/pim/v1/menu/drafts/state/retrieve',region)
        if state['state']=='failed':
            frappe.throw(state.get('error_message') or 'Bolt menu validation failed')
        if state['state']=='waiting_for_review':
            data['prior_menu_ids']=[m['id'] for m in call('/pim/v1/menu/publish/list',region).get('menus',[])]
            call('/pim/v1/menu/drafts/publish',region)
            save('Publishing',sync_snapshot=json.dumps(data))
    elif phase=='Publishing':
        publications=call('/pim/v1/menu/publish/list',region).get('menus',[])
        fresh=[m for m in publications if m['id'] not in data.get('prior_menu_ids',[])]
        if len(fresh)>1:
            frappe.throw('Concurrent Bolt menu publication requires review')
        if fresh and fresh[0]['state']=='published':
            menu=call('/genericClient/getMenu',{'provider_id':s.provider_id}).get('menu',{})
            visible={x.get('sku') for x in menu.values() if x.get('sku')}
            expected={p['sku'] for p in data['products']}
            if not expected.issubset(visible) or set(data['removed']) & visible:
                frappe.throw('Published Bolt menu does not match the selected products')
            save('Idle',last_catalogue_hash=data['catalogue_hash'],last_synced_skus=json.dumps(sorted(expected)),sync_snapshot='',last_sync=frappe.utils.now_datetime())


@frappe.whitelist(methods=['POST'])
def run_now():
    """Advance one sync stage; a publish acknowledgment is not final completion."""
    frappe.only_for('System Manager')
    tick()
    return {'ok':True}
