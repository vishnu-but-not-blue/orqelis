'use strict';
// Catalog keys are English source messages (gettext-style); values never contain HTML.
// Only explicitly marked UI messages are translated. Procurement/user data is not a key.
const I18N = (() => {
  const languages = {en:'English',de:'Deutsch',fr:'Français',es:'Español',it:'Italiano',nl:'Nederlands',pl:'Polski',pt:'Português'};
  let language = 'en', catalog = {}, english = {};
  const missing=new Set();
  try { const stored=localStorage.getItem('orqelis.language'); if(Object.hasOwn(languages,stored)) language=stored; } catch {}
  const escape = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const message = key => {
    if(!Object.hasOwn(english,key))missing.add(String(key));
    return Object.hasOwn(catalog,key) ? catalog[key] : (english[key] ?? String(key));
  };
  const t = (key,...values) => message(key).replace(/\{(\d+)\}/g,(match,i)=>i<values.length?String(values[i]):match);
  // Interpolations already follow the renderer's escaping rules. Escape catalog text first,
  // then insert values once: braces or markup in evidence can never become translation keys.
  const htmlMessage = (key,...values) => escape(message(key)).replace(/\{(\d+)\}/g,(match,i)=>i<values.length?String(values[i]):match);
  let patterns=[];
  function generated(value) {
    const text=String(value ?? '');
    if(Object.hasOwn(english,text))return t(text);
    for(const [key,pattern,indices] of patterns){
      const match=text.match(pattern);
      if(match){const values=[];indices.forEach((index,i)=>values[index]=match[i+1]);return t(key,...values);}
    }
    return text;
  }
  async function load(code) {
    const response=await fetch((document.body?.dataset.assets || '/static')+'/locales/'+code+'.json');
    if(!response.ok) throw new Error('Language catalog unavailable');
    return response.json();
  }
  const ready=(async()=>{
    english=await load('en');
    patterns=Object.keys(english).filter(key=>/^[A-Z][a-z]/.test(key)&&/\{\d+\}/.test(key)).map(key=>{
      const indices=[];
      const pattern=key.split(/(\{\d+\})/).map(part=>{
        if(/^\{\d+\}$/.test(part)){indices.push(Number(part.slice(1,-1)));return '([\\s\\S]*?)';}
        return part.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
      }).join('');
      return [key,new RegExp('^'+pattern+'$'),indices];
    });
    if(language!=='en') { try {catalog=await load(language);} catch {language='en';} }
    document.documentElement.lang=language;
    document.addEventListener('input',event=>event.target.setCustomValidity?.(''));
    document.addEventListener('invalid',event=>{
      const node=event.target;
      if(!node.validity)return;
      node.setCustomValidity(t(node.validity.valueMissing?'Please fill out this field.':node.type==='email'&&node.validity.typeMismatch?'Please enter a valid email address.':'Please enter a valid value.'));
    },true);
    document.querySelectorAll('[data-i18n]').forEach(node=>{node.textContent=t(node.dataset.i18n);});
    document.querySelectorAll('[data-i18n-label]').forEach(node=>node.setAttribute('aria-label',t(node.dataset.i18nLabel)));
    const selector=document.querySelector('#language');
    if(selector){
      selector.setAttribute('aria-label',t('Language'));
      selector.innerHTML=Object.entries(languages).map(([code,name])=>`<option value="${code}" lang="${code}">${name}</option>`).join('');
      selector.value=language;
      selector.addEventListener('change',()=>{
        if(!Object.hasOwn(languages,selector.value))return;
        try{localStorage.setItem('orqelis.language',selector.value);}catch{}
        // A reload preserves links and server sessions; language never alters API values.
        location.reload();
      });
    }
  })();
  function error(data,status) {
    const key=data.error?.message || data.detail;
    if(typeof key==='string' && Object.hasOwn(english,key))return t(key);
    const generic={401:'Sign in to continue.',403:'Access denied. Refresh the page and check your permissions.',409:'This change conflicts with the current state. Refresh and retry.',422:'Check the form values and try again.',429:'Too many requests. Please wait and retry.'};
    return t(generic[status] || 'The request could not complete. Please retry.');
  }
  return {t,htmlMessage,ready,error,generated,get language(){return language;},get missing(){return [...missing];},languages};
})();
const t=I18N.t, htmlMessage=I18N.htmlMessage;
