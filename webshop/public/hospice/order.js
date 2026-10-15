/* No buyer data is kept in browser storage. Payment capability survives redirects only. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), key = 'callus.hospice.checkout';
  const base = '/api/method/webshop.callus_storefront.';
  let token = sessionStorage.getItem(key), busy = false;
  const message = (text, error = false) => { $('message').textContent = text; $('message').className = error ? 'error' : ''; };
  async function api(method, data) {
    const response = await fetch(base + method, {method: data ? 'POST' : 'GET', credentials:'same-origin',
      headers: {'Content-Type':'application/json', 'X-Frappe-CSRF-Token':document.querySelector('meta[name=csrf-token]').content},
      body: data ? JSON.stringify(data) : undefined});
    const result = await response.json();
    if (!response.ok || result.exc) throw new Error('We could not complete this step. Please check your details and availability, or contact Callus.');
    return result.message;
  }
  async function run(fn) {
    if (busy) return;
    busy = true; document.querySelectorAll('button').forEach(x => x.disabled = true);
    try { await fn(); } catch (e) { message(e.message, true); $('message').scrollIntoView({block:'center'}); }
    finally { busy = false; document.querySelectorAll('button').forEach(x => x.disabled = false); }
  }
  function line(tag, text, parent) { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node; }
  const euros = value => new Intl.NumberFormat('en-MT', {style:'currency',currency:'EUR'}).format(value);
  let freeDeliveryFrom = 35;
  function fulfilment() {
    const pickup = $('fulfilment').value === 'collection';
    $('delivery-fields').hidden = pickup;
    $('delivery-fields').querySelectorAll('input').forEach(input => {
      input.disabled = pickup;
      if (['address', 'town', 'postcode'].includes(input.name)) input.required = !pickup;
    });
    $('fulfilment-help').textContent = pickup
      ? 'Pickup is free. We’ll email you when your order is ready to collect. Please wait for that email before visiting.'
      : `Delivery within 3–5 working days. Free delivery on products totalling ${euros(freeDeliveryFrom)} or more, including VAT. Any delivery charge is shown at review.`;
  }
  $('fulfilment').onchange = fulfilment;
  async function load() {
    const data = await api('hospice.catalogue');
    freeDeliveryFrom = data.free_delivery_from || 35; fulfilment();
    for (const item of data.items) {
      const card = document.createElement('article'); card.className = 'product';
      if (item.image) { const img = document.createElement('img'); img.src = item.image; img.alt = item.name; card.append(img); }
      line('h3', item.name, card); line('p', item.price ? euros(item.price) + ' · includes VAT' : 'Currently unavailable', card);
      const label = line('label', item.available ? 'Quantity' : 'Currently unavailable', card);
      const input = document.createElement('input'); Object.assign(input, {type:'number', min:'0', max:'99', step:'1', value:'0', disabled:!item.available});
      input.dataset.item = item.id; label.append(input); $('products').append(card);
    }
    message(data.is_live ? '' : 'Test checkout — no real payment will be taken.'); $('order-form').hidden = false;
  }
  $('order-form').addEventListener('submit', e => { e.preventDefault(); run(async () => {
    const items = [...document.querySelectorAll('[data-item]')].filter(x => Number(x.value)>0).map(x => ({id:x.dataset.item,qty:Number(x.value)}));
    if (!items.length) throw new Error('Please choose at least one product.');
    const buyer = Object.fromEntries(new FormData($('order-form'))); buyer.country='Malta';
    if (!token) { token = [...crypto.getRandomValues(new Uint8Array(32))].map(x=>x.toString(16).padStart(2,'0')).join(''); sessionStorage.setItem(key,token); }
    const data = await api('hospice.prepare',{token,items,buyer});
    $('summary-content').replaceChildren();
    for (const item of data.summary.items) line('p', `${item.qty} × ${item.name} · ${euros(item.amount)}`, $('summary-content'));
    const pickup = data.summary.fulfilment === 'collection';
    line('p', pickup ? 'Pickup from Callus Garden Centre · free. We’ll email you when ready.' : 'Delivery within 3–5 working days.', $('summary-content'));
    if (!pickup) line('p', `Delivery, including VAT: ${euros(data.summary.delivery_fee)}`, $('summary-content'));
    line('strong', `Total to pay, including VAT: ${euros(data.summary.total)}`, $('summary-content'));
    $('order-form').hidden=true; $('summary').hidden=false; message('Please check your order before payment.'); $('summary').scrollIntoView();
  }); });
  async function pay() {
    const data = await api('checkout.pay',{token});
    if (data.url) { const url = new URL(data.url); if(url.protocol!=='https:'||url.hostname!=='checkout.stripe.com') throw new Error('Unexpected payment address. Please contact Callus.'); location.assign(url.href); }
    else await status();
  }
  async function status() {
    const data = await api('checkout.status',{token});
    $('result').hidden=false; $('order-form').hidden=true; $('summary').hidden=true;
    const paid = ['Paid','Refund Pending','Refunded'].includes(data.status);
    $('result-title').textContent = paid ? (data.status==='Paid' ? 'Thank you. Your payment is confirmed.' : data.status) : 'Your payment is not confirmed yet.';
    const fulfilmentText = data.summary.fulfilment === 'collection' ? 'We’ll email you when your order is ready to collect from the shop.' : 'Delivery is within 3–5 working days.';
    $('result-text').textContent = paid ? `Order ${data.order}. Your confirmation email includes a private tracking link. ${fulfilmentText}` : 'You can check again or resume payment. Please do not place a second order.';
    $('check').hidden=paid||data.status==='Expired'; $('resume').hidden=paid||data.status==='Expired';
    if(paid) {sessionStorage.removeItem(key); message('');}
    if(data.status==='Expired') {history.replaceState(null,'','/hospice');sessionStorage.removeItem(key); token=null; $('result-text').textContent='This payment attempt expired. Reload this page to start a new order.';}
  }
  $('pay').onclick=()=>run(pay); $('resume').onclick=()=>run(pay); $('check').onclick=()=>run(status);
  $('edit').onclick=()=>run(async()=>{const cancelled = await api('checkout.cancel',{token});if(cancelled.status !== 'Expired') { await status(); return; }sessionStorage.removeItem(key);token=null;$('summary').hidden=true;$('order-form').hidden=false;message('Update your details and review again.');});
  run(async()=>{if(token) await status();else if(new URLSearchParams(location.search).has('payment')) {message('Open the confirmation email to track your order, or contact Callus before placing another order.',true);} else await load();});
})();
