const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../webshop/public/callus/storefront.js'),'utf8');
const helpers=source.slice(source.indexOf('    function clearPurchasedBasket('),source.indexOf('    async function renderCheckout('));
const order={status:'Paid',summary:{items:[{id:'plant',qty:2}]}};
function setup(status='Paid'){
 const saved={'callus-basket-v1':[{id:'plant',qty:2}]},session=new Map([['callus-active-checkout','token']]);
 const ctx={basket:[],getSaved:(key,fallback)=>saved[key]===undefined?fallback:JSON.parse(JSON.stringify(saved[key])),persist:(key,value)=>saved[key]=JSON.parse(JSON.stringify(value)),sessionStorage:{getItem:key=>session.get(key),setItem:(key,value)=>session.set(key,value)},counts:()=>{},page:'basket',renderBasket:()=>ctx.rendered=true,checkoutApi:async()=>({...order,status})};
 vm.createContext(ctx);vm.runInContext(helpers,ctx);return {ctx,saved,session};
}
(async()=>{
 let {ctx,saved}=setup();await ctx.reconcileBasket();assert.deepEqual(saved['callus-basket-v1'],[]);assert.equal(ctx.rendered,true);
 saved['callus-basket-v1']=[{id:'plant',qty:3}];await ctx.reconcileBasket();assert.equal(saved['callus-basket-v1'][0].qty,3,'refresh must not subtract twice');
 ctx.sessionStorage.getItem=key=>key==='callus-active-checkout'?'token':null;await ctx.reconcileBasket();assert.equal(saved['callus-basket-v1'][0].qty,3,'shared marker protects another tab');
 ({ctx,saved}=setup());saved['callus-basket-v1']=[{id:'plant',qty:4},{id:'pot',qty:1}];await ctx.reconcileBasket();assert.deepEqual(saved['callus-basket-v1'],[{id:'plant',qty:2},{id:'pot',qty:1}]);
 ({ctx,saved}=setup('Pending'));await ctx.reconcileBasket();assert.equal(saved['callus-basket-v1'][0].qty,2);
 ({ctx,saved}=setup());ctx.checkoutApi=async()=>{throw Error('offline');};await ctx.reconcileBasket();assert.equal(saved['callus-basket-v1'][0].qty,2);
 const legacy=setup();legacy.session.set('callus-cleared-checkout','token');await legacy.ctx.reconcileBasket();assert.equal(legacy.saved['callus-basket-v1'][0].qty,2);
 for(const status of ['Refund Pending','Refunded']){({ctx,saved}=setup(status));await ctx.reconcileBasket();assert.deepEqual(saved['callus-basket-v1'],[]);}
 console.log('9 basket confirmation checks passed');
})();
