const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../webshop/public/callus/storefront.js'),'utf8');
const helpers=source.slice(source.indexOf('    function categoryTree('),source.indexOf('    function renderCatalogue('));
const ctx={products:[{category:'indoor',group:'Indoor Bonsai',group_path:['All Item Groups','Products','Plants & Trees','Bonsai','Indoor Bonsai']},{category:'indoor',group:'Indoor Bonsai Sale',group_path:['All Item Groups','Products','Plants & Trees','Bonsai','Indoor Bonsai Sale']},{category:'outdoor',group:'Others',group_path:['All Item Groups','Products','Plants & Trees','Trees','Others']}],categories:[{id:'indoor',name:'Indoor plants'},{id:'outdoor',name:'Outdoor plants'}],esc:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')};
vm.createContext(ctx);vm.runInContext(helpers,ctx);
const tree=ctx.categoryTree('indoor');assert.equal(tree.length,1);assert.equal(tree[0].name,'Bonsai');assert.equal(tree[0].count,2);assert.equal(tree[0].children.length,2);
const html=ctx.categorySidebar('indoor','Indoor Bonsai');assert.equal((html.match(/<details[^>]* open/g)||[]).length,2);assert.ok(html.includes('?group=Indoor%20Bonsai" aria-current="page"'));assert.ok(!html.includes('All Item Groups'));assert.ok(html.includes('Trees'));assert.equal(ctx.categoryTree('missing').length,0);
console.log('Category tree counts, nesting, active ancestors and encoded links verified');
