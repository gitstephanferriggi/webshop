/* Callus storefront. No credentials, customer data or order creation in the browser. */
(() => {
  'use strict';
  const start = () => {
    const app = document.querySelector('.cg-app');
    if (!app || app.dataset.initialized) return;
    app.dataset.initialized = 'true';
    const payload = document.querySelector('#cg-catalogue');
    let products;
    try { products = JSON.parse(payload.textContent); } catch (_) { app.querySelector('#cg-main').innerHTML = '<div class="cg-wrap cg-section cg-empty"><h1>Our catalogue is taking a moment.</h1><p>Please refresh the page or call <a href="tel:+35621462229">+356 2146 2229</a> · <a href="tel:+35699119529">+356 9911 9529</a>.</p></div>'; return; }
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const plain = value => { const d = new DOMParser().parseFromString(String(value || ''),'text/html'); d.querySelectorAll('script,style').forEach(e=>e.remove()); d.querySelectorAll('p,li,br,div').forEach(e=>e.append('\n')); return (d.body.textContent || '').replace(/\n{3,}/g,'\n\n').trim(); };
    const money = (n,c='EUR') => Number.isFinite(Number(n)) && n !== null ? new Intl.NumberFormat('en-MT',{style:'currency',currency:c}).format(n) : 'Ask for price';
    const icon = name => `<svg class="cg-icon" viewBox="0 0 24 24" aria-hidden="true">${({arrow:'<path d="M4 12h15m-6-6 6 6-6 6"/>',heart:'<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',filter:'<path d="M4 7h16M7 12h10m-7 5h4"/>',bag:'<path d="M5 7h14l1 14H4L5 7Z M9 8V6a3 3 0 0 1 6 0v2"/>'})[name] || ''}</svg>`;
    const categories = [
      {id:'indoor',name:'Indoor plants',desc:'A little life in every room.',image:'ITE-2023-011372'},
      {id:'outdoor',name:'Outdoor plants',desc:'Make room for the outdoors.'},
      {id:'pots',name:'Pots & planters',desc:'The perfect home for your plants.'},
      {id:'grow',name:'Grow your own',desc:'From your garden to your table.'},
      {id:'care',name:'Soil & plant care',desc:'Give good things room to grow.'},
      {id:'tools',name:'Tools & watering',desc:'Everyday essentials for growing.'},
      {id:'flowers',name:'Flowers & arrangements',desc:'A thoughtful touch of colour.'},
      {id:'gifts',name:'Home & gifts',desc:'Small details, beautiful spaces.'}
    ];
    const categoryById = Object.fromEntries(categories.map(c=>[c.id,c]));
    let deliveryPolicy=null;try{deliveryPolicy=JSON.parse(document.querySelector('#cg-delivery-policy')?.textContent||'null');}catch(_){}
    function deliveryTerms(){
      if(!deliveryPolicy)return 'Delivery charges are confirmed before payment.';
      const p=deliveryPolicy;
      if(p.basis==='Fixed')return `Delivery in Malta: ${money(p.fixed)}.`;
      if(p.basis==='Net Total' && p.bands.length===1 && p.bands[0].to>0){const band=p.bands[0];return `Delivery in Malta is ${money(band.fee)} when the items subtotal before VAT is up to and including ${money(band.to)}. Free delivery above ${money(band.to)} before VAT. Collection is free.`;}
      return 'Delivery is calculated using the shop’s delivery rates and confirmed before payment.';
    }
    app.querySelectorAll('[data-delivery-terms]').forEach(el=>{el.textContent=deliveryTerms();});

    const byId = new Map(products.flatMap(p=>[[p.id,p],[p.web_id,p]]));
    const usable = p => p.available && p.price !== null && p.price > 0;
    const popular = [...products].filter(usable).sort((a,b)=>a.rank-b.rank || a.name.localeCompare(b.name));
    const available = [...products].filter(usable);
    const getSaved = (key,fallback) => { try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch (_) { return fallback; } };
    const persist = (key,value) => { try { localStorage.setItem(key,JSON.stringify(value)); } catch (_) { toast('Your browser cannot save this basket after you leave.'); } };
    let basket = getSaved('callus-basket-v1',[]);
    if (!Array.isArray(basket)) basket=[];
    basket=basket.filter(x=>x && byId.has(x.id) && Number.isInteger(x.qty) && x.qty>0).map(x=>({id:x.id,qty:Math.min(x.qty,99)}));
    let saved = getSaved('callus-saved-v1',[]);
    if(!Array.isArray(saved))saved=[];
    saved=saved.filter(id=>byId.has(id));
    let toastTimer;
    function toast(message,link=false) {
      app.querySelector('.cg-toast')?.remove();
      const el=document.createElement('div');el.className='cg-toast';el.setAttribute('role','status');
      el.innerHTML=`<span>${esc(message)}</span>${link?'<a href="/cart">View basket</a>':''}`;app.append(el);
      clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.remove(),4500);
    }
    function counts(){app.querySelectorAll('[data-basket-count]').forEach(el=>el.textContent=basket.reduce((s,x)=>s+x.qty,0));}
    const linkFor = p => '/item/'+encodeURIComponent(p.id);
    const imageFor = p => {const u=p.image||''; return u.startsWith('/files/')||u.startsWith('/assets/') ? u : '';};
    function image(p,loading='lazy'){return imageFor(p)?`<img src="${esc(imageFor(p))}" alt="${esc(p.name)}" loading="${loading}" decoding="async" width="500" height="500">`:`<div class="cg-empty" aria-label="Product photograph coming soon">Photograph coming soon</div>`;}
    function card(p,index=0){const fav=saved.includes(p.id);return `<article class="cg-product"><div class="cg-product-image"><a href="${linkFor(p)}" tabindex="-1" aria-hidden="true">${image(p)}</a>${usable(p)&&p.rank<150?'<span class="cg-product-tag">Customer favourite</span>':''}<button class="cg-save" data-save="${esc(p.id)}" aria-pressed="${fav}" aria-label="${fav?'Unsave':'Save'} ${esc(p.name)}">${icon('heart')}</button></div><div class="cg-product-info"><p class="cg-product-group">${esc(p.group)}</p><a class="cg-product-name" href="${linkFor(p)}">${esc(p.name)}</a><div class="cg-product-bottom"><span class="cg-price">${money(p.price,p.currency)}</span><span class="cg-stock ${p.available?'':'unavailable'}">${p.available?'In stock':p.on_request?'Please enquire':'Currently unavailable'}</span></div>${usable(p)?`<button class="cg-quickadd" data-add="${esc(p.id)}">Add to basket <span aria-hidden="true">+</span></button>`:`<a class="cg-quickadd" style="display:grid;place-items:center" href="${linkFor(p)}">View details</a>`}</div></article>`;}
    const cards = list => list.map(card).join('');
    function catImage(c){let list=products.filter(p=>p.category===c.id&&imageFor(p)&&usable(p)); const prefer={indoor:'Ficus Elastica',outdoor:'Hibiscus',pots:'Classico',grow:'Basil P14',care:'Substrate Universal',tools:'Watering',flowers:'Bouquet',gifts:'Candle'};return list.find(p=>p.name.toLowerCase().includes((prefer[c.id]||'').toLowerCase())) || list[0] || products.find(p=>p.category===c.id&&imageFor(p));}
    function catCard(c){const p=catImage(c);return `<a class="cg-category" href="/category/${c.id}"><div class="cg-category-picture">${p?image(p):''}</div><div class="cg-category-title"><div>${c.name}<small>${products.filter(p=>p.category===c.id).length} to discover</small></div>${icon('arrow')}</div></a>`;}
    const breadcrumb = text => `<div class="cg-breadcrumb"><a href="/shop">Home</a> &nbsp;/&nbsp; ${esc(text)}</div>`;
    const heading = (title,desc='') => `<div class="cg-page-heading"><h1>${esc(title)}</h1>${desc?`<p>${esc(desc)}</p>`:''}</div>`;
    const main = app.querySelector('#cg-main');
    const page=app.dataset.page;
    const params=new URLSearchParams(location.search);
    const slug=decodeURIComponent(location.pathname.split('/').filter(Boolean).pop()||'');
    const collectionDefs={popular:{name:'Customer favourites',desc:'Popular picks from the last 90 days, with available favourites shown first.'},statement:{name:'Something a little extraordinary',desc:'Sculptural foliage and distinctive plants for spaces with personality.'},under20:{name:'Little joys under €20',desc:'Thoughtful finds that make a difference, without a big spend.'},kitchen:{name:'From garden to table',desc:'Herbs, seedlings and everything you need to grow something delicious.'},balcony:{name:'Your greener outdoor space',desc:'Plants, pots and practical essentials for balconies, terraces and gardens.'}};
    function collectionProducts(id){switch(id){case 'popular':return products.filter(p=>p.rank<999999);case 'statement':return products.filter(p=>/rare|limited|monstera|ficus|strelitzia|bonsai/i.test(p.group+' '+p.name));case 'under20':return products.filter(p=>p.price>0&&p.price<20);case 'kitchen':return products.filter(p=>p.category==='grow');case 'balcony':return products.filter(p=>['outdoor','pots','tools'].includes(p.category));default:return [];}}
    function renderHome(){
      app.querySelector('[data-category-grid]').innerHTML=categories.slice(0,4).map(catCard).join('');
      app.querySelector('[data-popular-grid]').innerHTML=cards(popular.slice(0,4));
      let statement=collectionProducts('statement').filter(usable).sort((a,b)=>a.price-b.price);
      const preferred=['Strelitzia Nicolai','Ficus Audrey','Monstera Deliciosa','Ficus Elastica'];
      const picks=preferred.map(name=>statement.find(p=>p.name.includes(name))).filter(Boolean);
      app.querySelector('[data-featured-grid]').innerHTML=cards([...new Map([...picks,...statement].map(p=>[p.id,p])).values()].slice(0,4));
    }
    function renderCatalogue(){
      const isCat=page==='category', isCol=page==='collection';
      const cat=isCat?categoryById[slug]:null,collection=isCol?collectionDefs[slug]:null;
      if((isCat&&!cat)||(isCol&&!collection)){main.innerHTML=`<div class="cg-wrap cg-section cg-empty"><h1>Let’s find your next favourite.</h1><p>This collection is not available.</p><a class="cg-btn" href="/store">Browse all products</a></div>`;return;}
      let q=params.get('q')||'',sort=params.get('sort')||'recommended',stockOnly=params.get('stock')==='1',under20=params.get('under20')==='1',pageNumber=Math.max(1,Number(params.get('page'))||1);
      const title=q?`Search results for “${q}”`:cat?.name||collection?.name||'Find your next favourite';
      const desc=cat?.desc||collection?.desc||'Plants, pots and everything in between. Find a little something for your home and garden.';
      main.innerHTML=`<div class="cg-wrap">${breadcrumb(cat?.name||collection?.name||'Shop')}${heading(title,desc)}<div class="cg-catalog-layout"><aside class="cg-filters" id="cg-filters" aria-label="Product filters"><div class="cg-filter-section"><h3>Shop by category</h3><div class="cg-filter-categories"><a href="/store" ${!cat?'aria-current="page"':''}>All products <small>${products.length}</small></a>${categories.map(c=>`<a href="/category/${c.id}" ${cat?.id===c.id?'aria-current="page"':''}>${c.name}<small>${products.filter(p=>p.category===c.id).length}</small></a>`).join('')}</div></div><div class="cg-filter-section"><h3>Find your favourite</h3><label class="cg-filter-check"><input type="checkbox" id="cg-in-stock" ${stockOnly?'checked':''}> In stock only</label><label class="cg-filter-check"><input type="checkbox" id="cg-under20" ${under20?'checked':''}> Under €20</label></div><a class="cg-link" href="/store">Clear filters</a></aside><section aria-label="Products"><div class="cg-toolbar"><button class="cg-mobile-filter" aria-expanded="false" aria-controls="cg-filters" data-filter-toggle>${icon('filter')} Filters</button><span id="cg-results-count" aria-live="polite"></span><label>Sort by <select id="cg-sort" aria-label="Sort products"><option value="recommended">Recommended</option><option value="popular">Most popular</option><option value="price-asc">Price: low to high</option><option value="price-desc">Price: high to low</option><option value="newest">Newest arrivals</option><option value="name">Name: A–Z</option></select></label></div><div class="cg-products" id="cg-results"></div><nav class="cg-pagination" id="cg-pagination" aria-label="Product pages"></nav></section></div></div>`;
      const sortEl=app.querySelector('#cg-sort');sortEl.value=sort;if(!sortEl.value){sort='recommended';sortEl.value=sort;}
      function update(scroll=false){
        let list=cat?products.filter(p=>p.category===cat.id):collection?collectionProducts(slug):[...products];
        if(q){const terms=q.toLowerCase().trim().split(/\s+/);list=list.filter(p=>terms.every(t=>(p.name+' '+p.group+' '+p.id).toLowerCase().includes(t)));}
        if(stockOnly)list=list.filter(p=>p.available);if(under20)list=list.filter(p=>p.price>0&&p.price<20);
        list.sort((a,b)=>sort==='price-asc'?(a.price??Infinity)-(b.price??Infinity):sort==='price-desc'?(b.price??-1)-(a.price??-1):sort==='name'?a.name.localeCompare(b.name):sort==='newest'?b.created.localeCompare(a.created):sort==='popular'?a.rank-b.rank:Number(b.available)-Number(a.available)||a.rank-b.rank||a.name.localeCompare(b.name));
        const totalPages=Math.max(1,Math.ceil(list.length/24));pageNumber=Math.min(totalPages,pageNumber);const start=(pageNumber-1)*24;
        app.querySelector('#cg-results-count').textContent=list.length?`${start+1}–${Math.min(start+24,list.length)} of ${list.length} products`:'0 products';
        const results=app.querySelector('#cg-results');results.classList.toggle('cg-products',list.length>0);results.innerHTML=list.length?cards(list.slice(start,start+24)):`<div class="cg-empty"><h2>No matches just yet.</h2><p>Try a different search or remove a filter to discover more.</p><a class="cg-btn" href="/store">Explore all products</a></div>`;
        const pages=[...new Set([1,...[pageNumber-1,pageNumber,pageNumber+1].filter(n=>n>1&&n<totalPages),totalPages])];
        app.querySelector('#cg-pagination').innerHTML=totalPages>1?`<button data-page-number="${pageNumber-1}" ${pageNumber===1?'disabled':''} aria-label="Previous page">←</button>${pages.map((n,i)=>`${i&&n-pages[i-1]>1?'<span>…</span>':''}<button data-page-number="${n}" ${pageNumber===n?'aria-current="page"':''} aria-label="Page ${n}">${n}</button>`).join('')}<button data-page-number="${pageNumber+1}" ${pageNumber===totalPages?'disabled':''} aria-label="Next page">→</button>`:'';
        const u=new URL(location.href);for(const [k,v] of Object.entries({q,sort:sort==='recommended'?'':sort,stock:stockOnly?'1':'',under20:under20?'1':'',page:pageNumber>1?String(pageNumber):''})){v?u.searchParams.set(k,v):u.searchParams.delete(k);}history.replaceState(null,'',u);
        if(scroll)app.querySelector('.cg-page-heading').scrollIntoView({behavior:'smooth'});
      }
      sortEl.addEventListener('change',()=>{sort=sortEl.value;pageNumber=1;update();});
      app.querySelector('#cg-in-stock').addEventListener('change',e=>{stockOnly=e.target.checked;pageNumber=1;update();});app.querySelector('#cg-under20').addEventListener('change',e=>{under20=e.target.checked;pageNumber=1;update();});
      app.querySelector('#cg-pagination').addEventListener('click',e=>{const b=e.target.closest('[data-page-number]');if(b){pageNumber=Number(b.dataset.pageNumber);update(true);}});update();
    }
    function renderProduct(){
      const p=byId.get(slug);
      if(!p){main.innerHTML=`<div class="cg-wrap cg-section cg-empty"><h1>This product is no longer available.</h1><p>There is plenty more to discover.</p><a class="cg-btn" href="/store">Explore the shop</a></div>`;return;}
      document.title=p.name+' | Callus Garden Centre';
      const desc=plain(p.description);const useful=desc&&desc.toLowerCase()!==p.name.trim().toLowerCase();
      main.innerHTML=`<div class="cg-wrap">${breadcrumb(categoryById[p.category]?.name||'Shop')}<div class="cg-detail"><div class="cg-detail-image">${image(p,'eager')}</div><div class="cg-detail-copy"><a class="cg-product-group" href="/category/${p.category}">${esc(p.group)}</a><h1>${esc(p.name)}</h1><p class="cg-detail-price" id="cg-live-price">${money(p.price,p.currency)}</p><span class="cg-stock ${p.available?'':'unavailable'}">${p.available?'In stock':p.on_request?'Please enquire about availability':'Currently unavailable'}</span><p class="cg-detail-description">${esc(useful?desc:'A little inspiration for your home and garden, selected from the Callus range. Need help choosing? Our team can advise on the right option for your space.')}</p><div class="cg-detail-buy"><div class="cg-qty"><button data-detail-qty="-1" aria-label="Decrease quantity">−</button><input id="cg-product-qty" type="number" aria-label="Quantity" min="1" max="${Math.min(99,Math.floor(p.quantity)||1)}" value="1"><button data-detail-qty="1" aria-label="Increase quantity">+</button></div>${usable(p)?`<button class="cg-btn" data-add="${esc(p.id)}" data-detail-add>Add to basket ${icon('bag')}</button>`:'<a class="cg-btn" href="/contact-callus">Ask our team</a>'}</div><button class="cg-link" style="background:none;border:0;border-bottom:1px solid;padding:5px 0" data-save="${p.id}" aria-pressed="${saved.includes(p.id)}">${icon('heart')} ${saved.includes(p.id)?'Saved to your favourites':'Save for later'}</button><div class="cg-product-facts"><details open><summary>Product details</summary><p>Product code: ${esc(p.id)}<br>Sold by: ${esc(p.uom||'piece')}<br>${/Plants|Herbs|Shrubs|Trees|Foliage|Climber|Cacti|Succulent|Perennial|Rose/i.test(p.group)?'Plants are living things: shape, size and colour can vary. Decorative pots are included only when stated in the product name.':'Please check the product name for size, colour and pack details.'}</p></details><details><summary>Delivery & collection</summary><p>Contact our team to confirm delivery arrangements or collection from Mqabba Road, Siġġiewi. Any delivery charge will be confirmed before payment.</p></details><details><summary>Need a little advice?</summary><p>Call <a href="tel:+35621462229">+356 2146 2229</a> · <a href="tel:+35699119529">+356 9911 9529</a> or email <a href="mailto:info@callusgardencentre.com">info@callusgardencentre.com</a>. Please mention product code ${esc(p.id)}.</p></details></div></div></div><section class="cg-section" style="border-top:1px solid var(--line)"><div class="cg-section-heading"><h2>A few more you might love</h2><a class="cg-link" href="/category/${p.category}">Explore the collection ${icon('arrow')}</a></div><div class="cg-products">${cards(available.filter(x=>x.category===p.category&&x.id!==p.id).slice(0,4))}</div></section></div>`;
      app.querySelectorAll('[data-detail-qty]').forEach(b=>b.addEventListener('click',()=>{const el=app.querySelector('#cg-product-qty');el.value=Math.min(Number(el.max),Math.max(1,(Number(el.value)||1)+Number(b.dataset.detailQty)));}));

    }
    function basketProducts(){return basket.map(row=>({...row,product:byId.get(row.id)})).filter(x=>x.product);}
    function basketTotal(){return basketProducts().reduce((s,x)=>s+Number(x.product.price||0)*x.qty,0);}
    function summary(button=true){return `<aside class="cg-order-summary"><h2>Your order summary</h2><div class="cg-summary-row"><span>Items (${basket.reduce((s,x)=>s+x.qty,0)})</span><span>${money(basketTotal())}</span></div><div class="cg-summary-row"><span>Delivery</span><span>Calculated at checkout</span></div><div class="cg-summary-row cg-summary-total"><span>Subtotal</span><span>${money(basketTotal())}</span></div>${button?'<a class="cg-btn" href="/checkout">Continue as guest '+icon('arrow')+'</a>':''}<p class="cg-note">${esc(deliveryTerms())}</p><p class="cg-note">Prices use the shop’s VAT-inclusive price list. Final charges and availability are confirmed before payment.</p></aside>`;}
    function renderBasket(){
      main.innerHTML=`<div class="cg-wrap">${breadcrumb('Your basket')}${heading('Good things are growing.','Your next favourites, all in one place.')}<div class="cg-basket-layout">${!basket.length?'<div class="cg-empty"><h2>Your basket is waiting to bloom.</h2><p>Start with a plant, a pot, or a little inspiration.</p><a class="cg-btn" href="/store">Explore the shop</a></div>':`<div>${basketProducts().map(x=>`<div class="cg-basket-row">${image(x.product)}<div><a href="${linkFor(x.product)}"><h3>${esc(x.product.name)}</h3></a><span class="cg-note">${money(x.product.price)} each</span>${!x.product.available||x.qty>x.product.quantity?'<p class="cg-note">Availability has changed. Please adjust your basket.</p>':''}<div><div class="cg-qty"><button data-cart-change="${x.id}" data-delta="-1" aria-label="Decrease ${esc(x.product.name)}">−</button><span style="min-width:25px;text-align:center" aria-label="Quantity">${x.qty}</span><button data-cart-change="${x.id}" data-delta="1" aria-label="Increase ${esc(x.product.name)}">+</button></div><button class="cg-remove" data-remove="${x.id}">Remove</button></div></div><span class="cg-price">${money(x.qty*x.product.price)}</span></div>`).join('')}<a class="cg-link" style="margin-top:25px" href="/store">← Continue exploring</a></div>${summary()}`}</div></div>`;
    }
    async function checkoutApi(method, payload){
      const headers={'Content-Type':'application/json'};
      if(window.frappe?.csrf_token)headers['X-Frappe-CSRF-Token']=window.frappe.csrf_token;
      const response=await fetch('/api/method/webshop.callus_storefront.checkout.'+method,
        {method:payload?'POST':'GET',credentials:'same-origin',headers,body:payload?JSON.stringify(payload):undefined});
      let result;try{result=await response.json();}catch(_){throw new Error('Checkout is temporarily unavailable. Please try again.');}
      if(!response.ok||result.exc){
        let message='We could not complete this step. Please try again or contact our team.';
        try{const messages=JSON.parse(result._server_messages||'[]');if(messages.length)message=plain(JSON.parse(messages[0]).message);}catch(_){}
        const error=new Error(message);error.checkoutRejected=response.status>=400&&response.status<500;throw error;
      }
      return result.message;
    }
    function newCheckoutToken(){return [...crypto.getRandomValues(new Uint8Array(32))].map(x=>x.toString(16).padStart(2,'0')).join('');}
    function clearPurchasedBasket(order,token){
      if(!token||!['Paid','Refund Pending','Refunded'].includes(order.status))return false;
      const key='callus-cleared-checkouts-v1';
      const stored=getSaved(key,[]);const cleared=Array.isArray(stored)?stored:[];
      let legacy=false;try{legacy=sessionStorage.getItem('callus-cleared-checkout')===token;}catch(_){}
      if(cleared.includes(token)||legacy)return false;
      // Read the current basket: another tab may have added items during payment.
      const current=getSaved('callus-basket-v1',basket);
      basket=Array.isArray(current)?current:basket;
      for(const purchased of order.summary.items){const row=basket.find(x=>x.id===purchased.id);if(row)row.qty=Math.max(0,row.qty-purchased.qty);}
      basket=basket.filter(x=>x.qty>0);
      persist('callus-basket-v1',basket);persist(key,[...cleared,token]);counts();
      try{sessionStorage.setItem('callus-cleared-checkout',token);}catch(_){}
      return true;
    }
    async function reconcileBasket(){
      let token;try{token=sessionStorage.getItem('callus-active-checkout');}catch(_){}
      if(!token)return;
      try{clearPurchasedBasket(await checkoutApi('status',{token}),token);basket=getSaved('callus-basket-v1',basket);counts();if(page==='basket')renderBasket();}
      catch(_){/* Keep the basket until payment is verified; checkout offers retry. */}
    }
    async function renderCheckout(){
      const sessionKey='callus-active-checkout';
      let token;try{token=sessionStorage.getItem(sessionKey);}catch(_){}
      const errorBox=message=>`<div class="cg-alert" role="alert">${esc(message)}</div>`;
      const quoteHtml=q=>`<div class="cg-order-summary"><h2>Your confirmed total</h2>${q.items.map(x=>`<div class="cg-summary-row"><span>${esc(x.name)} × ${x.qty}</span><span>${money(x.amount,q.currency)}</span></div>`).join('')}<div class="cg-summary-row"><span>Net items</span><span>${money(q.net_total,q.currency)}</span></div><div class="cg-summary-row"><span>${q.delivery_fee===undefined?'Taxes & delivery':'VAT & other taxes'}</span><span>${money(q.taxes_and_charges-(q.delivery_fee||0),q.currency)}</span></div>${q.delivery_fee===undefined?'':`<div class="cg-summary-row"><span>${q.fulfilment==='delivery'?'Malta delivery':'Collection'}</span><span>${q.delivery_fee?money(q.delivery_fee,q.currency):'Free'}</span></div>`}<div class="cg-summary-row cg-summary-total"><span>Total</span><span>${money(q.total,q.currency)}</span></div><p class="cg-note">${q.fulfilment==='collection'?'Collection from Callus Garden Centre. Please wait for the team to confirm when your order is ready.':'Delivery in Malta. Your confirmed total includes the configured delivery charge.'}</p></div>`;
      function showOrder(order){
        const paid=['Paid','Refund Pending','Refunded'].includes(order.status);
        const title=order.status==='Paid'?'Thank you. Your payment is confirmed.':order.status==='Refunded'?'Your refund is confirmed.':order.status==='Refund Pending'?'Your refund is being processed.':order.status==='Expired'?'This checkout has ended.':'Your order is ready for payment.';
        main.innerHTML=`<div class="cg-wrap cg-section">${breadcrumb('Checkout')}${heading(title)}<p>Order reference: <strong>${esc(order.order)}</strong></p>${!order.is_live?errorBox('Stripe test mode — no real money is taken.'):''}<div class="cg-basket-layout"><div><div id="cg-payment-message" aria-live="polite"></div>${paid?'<p class="cg-note">Keep your order reference for any questions. Call <a href="tel:+35621462229">+356 2146 2229</a> · <a href="tel:+35699119529">+356 9911 9529</a> for help.</p>':''}${['Draft','Pending'].includes(order.status)?'<button class="cg-btn" id="cg-pay">Continue to secure payment</button><button class="cg-link" id="cg-cancel-order" style="display:block;margin-top:24px">Cancel checkout & return to basket</button>':'<button class="cg-btn" id="cg-new-order">Continue shopping</button>'}<p class="cg-note" style="margin-top:20px">Card details are entered securely on Stripe. Confirmation here is based on the payment provider’s verified status.</p><button class="cg-link" id="cg-refresh-payment">Refresh payment status</button></div>${quoteHtml(order.summary)}</div></div>`;
        window.scrollTo({top:0,behavior:"instant"});
        if(paid)clearPurchasedBasket(order,token);
        const action=async(button,fn)=>{button.disabled=true;try{await fn();}catch(e){app.querySelector('#cg-payment-message').innerHTML=errorBox(e.message);button.disabled=false;}};
        app.querySelector('#cg-new-order')?.addEventListener('click',()=>{sessionStorage.removeItem(sessionKey);location.assign('/store');});
        app.querySelector('#cg-pay')?.addEventListener('click',e=>action(e.currentTarget,async()=>{
          const result=await checkoutApi('pay',{token});
          if(result.url){const target=new URL(result.url);if(target.protocol!=='https:'||target.hostname!=='checkout.stripe.com')throw new Error('Unexpected payment address. Please contact the shop.');location.assign(target.href);}else showOrder(result);
        }));
        app.querySelector('#cg-refresh-payment').addEventListener('click',e=>action(e.currentTarget,async()=>showOrder(await checkoutApi('status',{token}))));
        app.querySelector('#cg-cancel-order')?.addEventListener('click',e=>action(e.currentTarget,async()=>{const state=await checkoutApi('cancel',{token});if(state.status==='Expired'){sessionStorage.removeItem(sessionKey);location.assign('/cart');}else showOrder(state);}));
      }
      if(token){
        main.innerHTML=`<div class="cg-wrap cg-section"><h1>Checking your order…</h1><p role="status">Please wait while we confirm its current status.</p></div>`;
        try{const order=await checkoutApi('status',{token});if(order.status==='Expired'){sessionStorage.removeItem(sessionKey);token=null;}else{showOrder(order);return;}}
        catch(e){main.innerHTML=`<div class="cg-wrap cg-section"><h1>We could not confirm your order yet.</h1>${errorBox(e.message)}<p>Please retry before placing another order.</p><a class="cg-btn" href="/checkout">Check again</a><p><a href="/contact-callus">Contact our team</a></p></div>`;return;}
      }
      if(!basket.length){renderBasket();return;}
      main.innerHTML='<div class="cg-wrap cg-section"><p role="status">Preparing your checkout…</p></div>';
      let config;try{config=await checkoutApi('options');}catch(_){config={enabled:false};}
      if(!config?.enabled){main.innerHTML=`<div class="cg-wrap cg-section">${heading('Online checkout is being prepared.')}<p>Your basket is saved. Please contact the team if you would like to order now.</p><a class="cg-btn" href="/contact-callus">Contact Callus</a><p><a href="/cart">Back to your basket</a></p></div>`;return;}
      main.innerHTML=`<div class="cg-wrap">${breadcrumb('Checkout')}${heading('A little closer to greener living.')}<div class="cg-basket-layout"><div><p class="cg-note">No account needed. We will confirm stock, prices and taxes before payment.</p>${!config.is_live?errorBox('Stripe test mode — use test details for this checkout.'):''}<form id="cg-checkout-form"><section class="cg-checkout-step"><h2>1. Your details</h2><div class="cg-form"><label>First name<input name="first_name" autocomplete="given-name" required maxlength="80"></label><label>Last name<input name="last_name" autocomplete="family-name" required maxlength="80"></label><label class="wide">Email address<input name="email" type="email" autocomplete="email" required maxlength="140"></label><label class="wide">Phone number<input name="phone" type="tel" autocomplete="tel" required minlength="8" maxlength="25"></label></div></section><section class="cg-checkout-step"><h2>2. Collection or delivery</h2><label class="cg-radio"><input type="radio" name="delivery" value="collection" checked> Collection from Callus Garden Centre</label>${config.delivery?'<label class="cg-radio"><input type="radio" name="delivery" value="delivery"> Delivery in Malta — charge shown before payment</label><p class="cg-note">'+esc(deliveryTerms())+'</p>':'<p class="cg-note">For delivery arrangements, please contact our team.</p>'}<h3 style="margin:24px 0 12px">Billing address</h3><p class="cg-note">For delivery, we will also use this as your delivery address.</p><div class="cg-form"><label class="wide">Address<input name="address" autocomplete="address-line1" required maxlength="140"></label><label>Town<input name="town" autocomplete="address-level2" required maxlength="80"></label><label>Postcode<input name="postcode" autocomplete="postal-code" required maxlength="12"></label><label class="wide">Country<select name="country" autocomplete="country-name"><option>Malta</option></select></label></div></section><section class="cg-checkout-step"><h2>3. Confirm your total</h2><p class="cg-note">We use these details to prepare your order. Card details are entered on Stripe at the next step. <a href="/privacy-callus">Privacy information</a></p><div id="cg-checkout-error" aria-live="polite"></div><button class="cg-btn" type="submit" style="margin-top:20px">Review order ${icon('arrow')}</button></section></form></div>${summary(false)}</div></div>`;
      const form=app.querySelector('#cg-checkout-form');let lastPayload='';let attempt=null;
      form.addEventListener('submit',async e=>{
        e.preventDefault();if(!form.reportValidity())return;
        const button=form.querySelector('[type="submit"]');button.disabled=true;
        const buyer=Object.fromEntries(new FormData(form));const items=basket.map(x=>({id:x.id,qty:x.qty}));const payload=JSON.stringify({buyer,items});
        if(payload!==lastPayload){attempt=newCheckoutToken();lastPayload=payload;}
        try{
          // Verify storage before creating an order; the token must survive Stripe's redirect.
          sessionStorage.setItem(sessionKey,attempt);
          const result=await checkoutApi('prepare',{token:attempt,items,buyer});token=attempt;showOrder(result);
        }catch(e){if(e.checkoutRejected)sessionStorage.removeItem(sessionKey);app.querySelector('#cg-checkout-error').innerHTML=errorBox(e.message);button.disabled=false;}
      });
    }
    function renderSaved(){const list=saved.map(id=>byId.get(id)).filter(Boolean);main.innerHTML=`<div class="cg-wrap">${breadcrumb('Saved favourites')}${heading('Keep a little inspiration.','Your favourites are saved on this browser, ready when you are.')}<div class="cg-page-body">${list.length?`<div class="cg-products">${cards(list)}</div>`:'<div class="cg-empty"><h2>Found something you love?</h2><p>Tap the heart on any product to save it here.</p><a class="cg-btn" href="/store">Find your favourites</a></div>'}</div></div>`;}
    function renderCategories(){main.innerHTML=`<div class="cg-wrap">${breadcrumb('Categories')}${heading('A world of growing possibilities.','From your first houseplant to your next garden project, start here.')}<div class="cg-category-grid cg-page-body">${categories.map(catCard).join('')}</div></div>`;}
    function renderCollections(){main.innerHTML=`<div class="cg-wrap">${breadcrumb('Collections')}${heading('A little inspiration, thoughtfully chosen.','Find a collection for your space, your plans and your next little joy.')}<div class="cg-category-grid cg-page-body">${Object.entries(collectionDefs).map(([id,c])=>{const p=collectionProducts(id).filter(usable)[0];return `<a class="cg-category" href="/collection/${id}"><div class="cg-category-picture">${p?image(p):''}</div><div class="cg-category-title"><div>${c.name}<small>${c.desc}</small></div>${icon('arrow')}</div></a>`;}).join('')}</div></div>`;}
    function add(id,qty){const p=byId.get(id);if(!p||!usable(p)){toast('This item is not available to add right now.');return;}const existing=basket.find(x=>x.id===id);const max=Math.min(99,Math.floor(p.quantity));const amount=Math.max(1,Math.floor(Number(qty)||1));if((existing?.qty||0)+amount>max){toast('You have reached the available quantity for this item.');return;}if(existing)existing.qty+=amount;else basket.push({id,qty:amount});persist('callus-basket-v1',basket);counts();toast('Added to your basket.',true);}
    app.addEventListener('click',e=>{
      const addButton=e.target.closest('[data-add]');if(addButton){add(addButton.dataset.add,addButton.hasAttribute('data-detail-add')?app.querySelector('#cg-product-qty').value:1);return;}
      const saveButton=e.target.closest('[data-save]');if(saveButton){const id=saveButton.dataset.save;saved=saved.includes(id)?saved.filter(x=>x!==id):[...saved,id];persist('callus-saved-v1',saved);app.querySelectorAll('[data-save]').forEach(b=>{if(b.dataset.save===id){b.setAttribute('aria-pressed',String(saved.includes(id)));if(b.classList.contains('cg-save'))b.setAttribute('aria-label',(saved.includes(id)?'Unsave ':'Save ')+byId.get(id).name);else b.innerHTML=icon('heart')+' '+(saved.includes(id)?'Saved to your favourites':'Save for later');}});if(page==='saved')renderSaved();return;}
      const remove=e.target.closest('[data-remove]');const change=e.target.closest('[data-cart-change]');if(remove||change){const id=remove?.dataset.remove||change.dataset.cartChange;const row=basket.find(x=>x.id===id);if(!row)return;if(remove)basket=basket.filter(x=>x.id!==id);else{const next=row.qty+Number(change.dataset.delta);if(next<1)basket=basket.filter(x=>x.id!==id);else if(next<=Math.min(99,Math.floor(byId.get(id).quantity)))row.qty=next;else{toast('You have reached the available quantity.');return;}}persist('callus-basket-v1',basket);counts();renderBasket();return;}
      const toggle=e.target.closest('[data-menu-toggle]');if(toggle){const el=app.querySelector('#cg-mobile-menu');const open=el.classList.toggle('open');toggle.setAttribute('aria-expanded',String(open));return;}
      const filter=e.target.closest('[data-filter-toggle]');if(filter){const open=app.querySelector('#cg-filters').classList.toggle('open');filter.setAttribute('aria-expanded',String(open));}
    });
    app.addEventListener('keydown',e=>{if(e.key==='Escape'){app.querySelector('#cg-mobile-menu')?.classList.remove('open');app.querySelector('[data-menu-toggle]')?.setAttribute('aria-expanded','false');}});
    app.querySelectorAll('.cg-search input').forEach(input=>{input.value=params.get('q')||'';});
    app.querySelectorAll('.cg-search').forEach(form=>form.addEventListener('submit',e=>{const input=form.querySelector('input');input.value=input.value.trim();if(!input.value){e.preventDefault();location.href='/store';}}));
    const renderers={home:renderHome,store:renderCatalogue,category:renderCatalogue,collection:renderCatalogue,product:renderProduct,basket:renderBasket,checkout:renderCheckout,saved:renderSaved,categories:renderCategories,collections:renderCollections};
    if(renderers[page])renderers[page]();counts();
    if(page!=='checkout')reconcileBasket();
    window.addEventListener('pageshow',event=>{if(event.persisted){if(page==='checkout')renderCheckout();else reconcileBasket();}});
    window.addEventListener('storage',event=>{if(event.key==='callus-basket-v1'){basket=getSaved('callus-basket-v1',[]);counts();if(page==='basket')renderBasket();}});
    app.addEventListener('error',e=>{const img=e.target;if(img.tagName!=='IMG'||img.hidden)return;img.hidden=true;const label=document.createElement('span');label.className='cg-image-fallback';label.textContent='Photograph coming soon';img.parentElement.append(label);},true);
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
