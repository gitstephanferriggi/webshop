const fs=require('node:fs');const vm=require('node:vm');const assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../webshop/public/callus/account.js'),'utf8');
const redirect=source.slice(source.indexOf('    const redirect='),source.indexOf('    const authLink='));
const handler=source.slice(source.indexOf('    function handleLogin('),source.indexOf('    function render('));
const cases=[
 ['system user', '', {message:'Logged In',home_page:'/app/hr'},'/app/hr'],
 ['punching portal', '', {message:'No App',home_page:'/hrms'},'/hrms'],
 ['requested clock page','redirect-to=%2Fapp%2Femployee-checkin', {message:'Logged In',home_page:'/app'},'/app/employee-checkin'],
 ['server redirect','',{message:'No App',redirect_to:'/employee-portal',home_page:'/'},'/employee-portal'],
 ['external redirect rejected','redirect-to=https%3A%2F%2Fevil.example', {message:'Logged In',home_page:'/app'},'/account-callus'],
 ['login loop rejected','redirect-to=%2Fcustomer-login', {message:'No App'},'/account-callus'],
 ['customer fallback','',{message:'No App'},'/account-callus'],
];
for(const [label,query,result,expected] of cases){let target;const ctx={params:new URLSearchParams(query),URL,location:{origin:'https://shop.example',assign:value=>target=value},result};vm.runInNewContext(redirect+handler+'\nhandleLogin(result);',ctx);assert.equal(target,expected,label);}
console.log(`${cases.length} account routing checks passed`);
