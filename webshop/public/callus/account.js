/* Shop account screens use Frappe's session, verification and password APIs. */
(() => {
  'use strict';
  async function startAccount() {
    const app=document.querySelector('.cg-app');
    if(!app || !['account','login','signup','forgot','password'].includes(app.dataset.page))return;
    const main=app.querySelector('#cg-main');
    const params=new URLSearchParams(location.search);
    const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let options={};try{options=JSON.parse(document.querySelector('#cg-account-options')?.textContent||'{}');}catch(_){}
    // Never send the password-link token to another origin or keep it in browser storage.
    let resetKey=params.get('key');
    if(resetKey){history.replaceState(null,'',location.pathname);}
    let challenge=null;let verification=null;
    const redirect=(fallback='/account-callus')=>{
      const raw=params.get('redirect-to')||fallback;
      try{const url=new URL(raw,location.origin);if(url.origin===location.origin && !/^\/(login|customer-login|signup|forgot-password|update-password)(\/|$)/.test(url.pathname))return url.pathname+url.search+url.hash;}catch(_){}
      return '/account-callus';
    };
    const authLink=(path)=>path+(params.has('redirect-to')?'?redirect-to='+encodeURIComponent(redirect()):'');
    async function call(method,data,allowGuest=false){
      const headers={'Accept':'application/json','Content-Type':'application/json'};
      if(window.frappe?.csrf_token)headers['X-Frappe-CSRF-Token']=window.frappe.csrf_token;
      const response=await fetch('/api/method/'+method,{method:data?'POST':'GET',credentials:'same-origin',cache:'no-store',headers,body:data?JSON.stringify(data):undefined});
      let result;try{result=await response.json();}catch(_){throw new Error('The shop could not respond. Please try again in a moment.');}
      if(allowGuest && [401,403].includes(response.status))return {message:'Guest'};
      if(!response.ok){
        let message=response.status===429?'Too many attempts. Please wait a few minutes before trying again.':response.status===401?'The email or password was not recognised. Please try again.':response.status===410?'This link has expired or has already been used. Please request a new link.':'We could not complete that request. Please try again or contact our team.';
        // Password policy feedback is useful; display it as text, never server HTML.
        if(method.endsWith('update_password') && response.status===417){try{const lines=JSON.parse(result._server_messages||'[]').map(x=>JSON.parse(x).message);const doc=new DOMParser().parseFromString(lines.join(' '),'text/html');message=doc.body.textContent||message;}catch(_){}}
        throw new Error(message);
      }
      return result;
    }
    const field=(label,name,type,autocomplete,extra='')=>`<label class="wide">${label}<input name="${name}" type="${type}" autocomplete="${autocomplete}" required ${extra}></label>`;
    const passwordField=(label,name,autocomplete)=>`<label class="wide">${label}<span class="cg-password-field"><input id="cg-${name}" name="${name}" type="password" autocomplete="${autocomplete}" required maxlength="72"><button type="button" data-password="cg-${name}" aria-label="Show ${label.toLowerCase()}" aria-pressed="false">Show</button></span></label>`;
    function shell(title,intro,body,view='login'){
      main.innerHTML=`<div class="cg-wrap"><div class="cg-breadcrumb"><a href="/shop">Home</a> / My account</div><section class="cg-auth-layout"><aside class="cg-auth-story"><p class="cg-eyebrow">YOUR LITTLE CORNER OF CALLUS</p><h1>Good things<br>grow here.</h1><p>A fresh start, a favourite plant, a greener everyday. Make yourself at home.</p><div class="cg-auth-picture" role="img" aria-label="Plants in a sunlit Mediterranean garden"></div><p class="cg-auth-guest">Just looking around? <a href="/store">Keep exploring →</a><br>You can also check out as a guest.</p></aside><div class="cg-auth-card"><div class="cg-auth-tabs"><a href="${esc(authLink('/customer-login'))}" ${view==='login'?'aria-current="page"':''}>Sign in</a><a href="${esc(authLink('/signup'))}" ${view==='signup'?'aria-current="page"':''}>Create account</a></div><h2 tabindex="-1">${title}</h2><p class="cg-auth-intro">${intro}</p>${body}<p class="cg-auth-help"><a href="/login">Employee sign-in / time clock →</a></p><p class="cg-auth-help">A little help? <a href="/contact-callus">Talk to our team</a></p></div></section></div>`;
      main.querySelectorAll('[data-password]').forEach(button=>button.addEventListener('click',()=>{const input=document.getElementById(button.dataset.password);const show=input.type==='password';input.type=show?'text':'password';button.textContent=show?'Hide':'Show';button.setAttribute('aria-pressed',String(show));button.setAttribute('aria-label',(show?'Hide ':'Show ')+input.name.replace('_',' '));}));
    }
    function notice(title,message,link='/customer-login',label='Back to sign in'){
      shell(title,'',`<div class="cg-auth-success" role="status"><span aria-hidden="true">✓</span><p>${esc(message)}</p></div><a class="cg-btn cg-auth-submit" href="${esc(authLink(link))}">${label}</a>`,'done');
      main.querySelector('h2').focus();
    }
    function form(content,button){return `<form id="cg-auth-form" class="cg-auth-form"><div class="cg-form">${content}</div><div class="cg-auth-error" role="alert" tabindex="-1" hidden></div><button class="cg-btn cg-auth-submit" type="submit">${button} →</button></form>`;}
    function bind(submit){const f=main.querySelector('form');f.addEventListener('submit',async e=>{e.preventDefault();if(!f.reportValidity())return;const b=f.querySelector('[type="submit"]'),error=f.querySelector('[role="alert"]');error.hidden=true;b.disabled=true;const label=b.textContent;b.textContent='One moment…';f.setAttribute('aria-busy','true');try{await submit(Object.fromEntries(new FormData(f)));}catch(e){error.textContent=e.message;error.hidden=false;error.focus();}finally{b.disabled=false;b.textContent=label;f.removeAttribute('aria-busy');}});}
    function handleLogin(result){
      if(['Logged In','No App'].includes(result.message)){location.assign(redirect(result.redirect_to||result.home_page||'/account-callus'));return;}
      if(result.message==='Password Reset' && result.redirect_to){const url=new URL(result.redirect_to,location.origin);if(url.origin!==location.origin)throw new Error('Please contact our team to reset your password.');resetKey=url.searchParams.get('key');render('password');return;}
      if(result.verification && result.tmp_id){challenge=result.tmp_id;verification=result.verification;render('otp');return;}
      throw new Error('Sign-in could not be completed. Please try again.');
    }
    function render(view){
      if(view==='signup'){
        if(options.signup_enabled===false){shell('A little pause.','New account registration is currently unavailable.','<p>You can still browse and check out as a guest.</p><a class="cg-btn" href="/store">Explore the shop →</a>','signup');return;}
        shell('Let’s grow together.','Create your account in two simple steps. We’ll email you a secure link to choose your password.',form(field('First name','first_name','text','given-name','maxlength="70"').replace('class="wide"','')+field('Last name','last_name','text','family-name','maxlength="70"').replace('class="wide"','')+field('Email address','email','email','email','maxlength="140"')+'<p class="cg-note wide">We use your details to manage your account. <a href="/privacy-callus">Privacy information</a></p>','Create my account'),'signup');
        bind(async data=>{if(!data.first_name.trim()||!data.last_name.trim())throw new Error('Please enter your first and last name.');const r=await call('frappe.core.doctype.user.user.sign_up',{email:data.email.trim().toLowerCase(),full_name:(data.first_name.trim()+' '+data.last_name.trim()).trim(),redirect_to:redirect()});const status=Number(r.message?.[0]);if(status===2){notice('Your request is received.','Your account needs the shop team’s help before you can sign in. Please contact us.','/contact-callus','Contact our team');}else if(status===0||status===1){notice('Check your inbox.','If this is a new account, you’ll receive a link to choose your password. Already registered? Sign in or use “Forgot password”.');}else{throw new Error('We could not create your account. Please contact our team.');}});
      }else if(view==='forgot'){
        shell('A fresh start.','Enter your email and we’ll help you reset your password.',form(field('Email address','email','email','email','maxlength="140"'),'Send reset link')+'<a class="cg-auth-back" href="/customer-login">Back to sign in</a>','forgot');
        bind(async data=>{await call('frappe.core.doctype.user.user.reset_password',{user:data.email.trim().toLowerCase()});notice('Check your inbox.','If an enabled account matches that email, you’ll receive a password-reset link. Check your spam folder too.');});
      }else if(view==='password'){
        if(!resetKey){shell('Let’s get a new link.','Open the secure link in your email to choose your password.','<a class="cg-btn" href="/forgot-password">Request a new link →</a>','password');return;}
        shell('Make it yours.','Choose a strong, unique password. A few unrelated words make a memorable passphrase.',form(passwordField('New password','new_password','new-password')+passwordField('Confirm password','confirm_password','new-password'),'Save password'),'password');
        bind(async data=>{if(data.new_password!==data.confirm_password)throw new Error('The passwords do not match. Please check them and try again.');await call('frappe.core.doctype.user.user.update_password',{new_password:data.new_password,key:resetKey,logout_all_sessions:1});resetKey=null;location.assign('/account-callus');});
      }else if(view==='otp'){
        shell('One last check.',esc(verification?.method==='OTP App'?'Enter the current code from your authenticator app.':'Enter the verification code sent to you by '+(verification?.method||'email')+'.'),form(field('Verification code','otp','text','one-time-code','inputmode="numeric" maxlength="12"'),'Verify and sign in'),'login');
        bind(async data=>handleLogin(await call('login',{otp:data.otp,tmp_id:challenge})));
      }else{
        if(options.password_login_enabled===false){shell('Sign-in is unavailable.','Please contact the shop team for help accessing your account.','<a class="cg-btn" href="/contact-callus">Contact us →</a>');return;}
        shell('Welcome back.','A little easier to pick up where you left off.',form(field('Email address','email','email','username','maxlength="140"')+passwordField('Password','password','current-password')+'<a class="cg-auth-forgot wide" href="/forgot-password">Forgot password?</a>','Sign in'),'login');
        bind(async data=>handleLogin(await call('login',{usr:data.email.trim(),pwd:data.password})));
      }
    }
    let view=app.dataset.page;
    if(view==='account')view=params.get('view')||'login';
    if(view==='login' && location.hash==='#signup')view='signup';
    if(view==='login' && location.hash==='#forgot')view='forgot';
    if(resetKey)view='password';
    render(view);
    if(!['password','forgot'].includes(view)){
      try{const session=await call('frappe.auth.get_logged_user',null,true);if(session.message && session.message!=='Guest'){
        shell('You’re right at home.',`Signed in as ${esc(session.message)}.`,`<div class="cg-auth-account-actions"><a class="cg-btn" href="/store">Explore the shop →</a><a class="cg-link" href="/saved">Your saved favourites →</a><a class="cg-link" href="/cart">Your basket →</a><button class="cg-auth-signout" type="button">Sign out</button><p class="cg-auth-error" role="alert"></p></div>`,'account');
        main.querySelector('.cg-auth-signout').addEventListener('click',async e=>{e.target.disabled=true;try{await call('logout',{});location.assign('/customer-login');}catch(error){main.querySelector('[role="alert"]').textContent=error.message;e.target.disabled=false;}});
      }}catch(_){/* Keep the usable sign-in form when session lookup is unavailable. */}
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',startAccount);else startAccount();
})();
