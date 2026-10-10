(() => {
  'use strict';
  const token = location.hash.slice(1), message = document.getElementById('message'), button = document.getElementById('refresh');
  async function refresh() {
    button.disabled=true;
    try {
      const response=await fetch('/api/method/webshop.callus_storefront.hospice.track', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Frappe-CSRF-Token':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify({token})});
      const result=await response.json(); if(!response.ok||!result.message) throw new Error('This tracking link is unavailable. Please contact Callus.');
      const data=result.message; message.textContent=`Order ${data.order} · ${data.progress.delivery_state}`;
      const panel=document.getElementById('progress'); panel.replaceChildren();
      for(const item of data.items) {const p=document.createElement('p');p.textContent=`${item.qty} × ${item.name}`;panel.append(p);}
    } catch(e) {message.textContent=e.message;} finally{button.disabled=false;}
  }
  button.onclick=refresh;refresh();
})();
