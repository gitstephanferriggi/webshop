const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const s=fs.readFileSync('webshop/public/callus/storefront.js','utf8');
const ctx={esc:s=>String(s).replaceAll('"','&quot;').replaceAll('<','&lt;'),imageFor:p=>(p.image||'').startsWith('/files/')?p.image:'',image:p=>`<img src="${p.image||''}">`};
vm.createContext(ctx);vm.runInContext(s.slice(s.indexOf('    function productGallery('),s.indexOf('    function renderProduct(')),ctx);
const html=ctx.productGallery({name:'Plant',image:'/files/main.jpg',images:[{image:'/files/main.jpg'},{image:'/files/extra.jpg',caption:'"<test>'},{image:'/private/files/no.jpg'}]});
assert.equal((html.match(/data-gallery-image=/g)||[]).length,2);
assert.ok(html.includes('aria-pressed="true"'));assert.ok(html.includes('&quot;&lt;test>'));assert.ok(!html.includes('/private/'));
assert.ok(!ctx.productGallery({name:'Plant',image:'/files/main.jpg'}).includes('cg-gallery-thumbs'));
console.log('Gallery deduplication, private URL rejection, escaping and single-image behavior passed.');
