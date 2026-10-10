// Standalone browser checks with a simulated API. No payment or external site requests.
const {chromium} = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
(async()=>{
 const root=path.resolve(__dirname,'..');
 const browser=await chromium.launch({headless:true,channel:"chrome"});
 const context=await browser.newContext({viewport:{width:1280,height:900}});
 let prepared=0, cancelled=0, lastBuyer;
 const items=[{id:'TEST-PLANT',name:'Poinsettia Rossa P14 cm',price:8.5,available:true},{id:'TEST-SAUCER',name:'Saucer Medea 12 cm Terracotta',price:1.5,available:true}];
 const summary={items:[{id:'TEST-PLANT',name:items[0].name,qty:2}],total:22,delivery_fee:5};
 const errors=[];
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',async route=>{
  const url=new URL(route.request().url());let content, type;
  if(url.pathname.startsWith('/api/')) {
   const method=url.pathname.split('.').pop();const payload=route.request().postDataJSON();let result;
   if(method==='catalogue') result={items,is_live:false};
   else if(method==='prepare'){prepared++;lastBuyer=payload.buyer;assert.deepEqual(payload.items,[{id:'TEST-PLANT',qty:2}]);result={status:'Draft',summary};}
   else if(method==='cancel'){cancelled++;result={status:'Expired'};}
   else if(method==='track') result={order:'TEST-ORDER',progress:{delivery_state:'Preparing'},items:summary.items};
   else throw new Error('Unexpected API '+method);
   return route.fulfill({contentType:'application/json',body:JSON.stringify({message:result})});
  }
  if(['/hospice','/hospice-track'].includes(url.pathname)){content=fs.readFileSync(path.join(root,'webshop/www',url.pathname.slice(1)+'.html'),'utf8').replace('{{ csrf_token | e }}','test-csrf');type='text/html';}
  else if(url.pathname.startsWith('/assets/webshop/')){const relative=url.pathname.replace('/assets/webshop/','');assert(!relative.includes('..'));content=fs.readFileSync(path.join(root,'webshop/public',relative));type=url.pathname.endsWith('.css')?'text/css':url.pathname.endsWith('.png')?'image/png':'application/javascript';}
  else return route.abort();
  await route.fulfill({contentType:type,body:content});
 });
 await page.goto('https://hospice.localtest/hospice');await page.locator('#order-form').waitFor({state:'visible'});
 await page.screenshot({path:process.env.HOSPICE_PREVIEW+'/desktop.png',fullPage:true});
 await page.locator('[data-item="TEST-PLANT"]').fill('2');
 const buyer={first_name:'Jane',last_name:'Test',email:'jane@example.com',phone:'+35699990000',company:'Example Ltd',address:'1 Test Street',town:'Siggiewi',postcode:'SGW 2600'};
 for(const [field,value] of Object.entries(buyer)) await page.locator(`[name="${field}"]`).fill(value);
 await page.locator('#review').click();await page.locator('#summary').waitFor({state:'visible'});
 assert.equal(prepared,1);assert.equal(lastBuyer.company,'Example Ltd');assert.equal(lastBuyer.delivery,'delivery');
 assert((await page.locator('#summary').innerText()).includes('€22.00'));
 await page.locator('#edit').click();await page.locator('#order-form').waitFor({state:'visible'});assert.equal(cancelled,1);
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 await page.screenshot({path:process.env.HOSPICE_PREVIEW+'/mobile.png',fullPage:true});
 await page.goto('https://hospice.localtest/hospice-track#'+'a'.repeat(64));
 await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('Preparing'));
 assert(!(await page.locator('body').innerText()).includes('jane@example.com'));
 await page.screenshot({path:process.env.HOSPICE_PREVIEW+'/tracking.png',fullPage:true});
 assert.deepEqual(errors,[]);await browser.close();console.log('Desktop, mobile, review/edit and tracking UI checks passed.');
})().catch(e=>{console.error(e);process.exit(1)});
