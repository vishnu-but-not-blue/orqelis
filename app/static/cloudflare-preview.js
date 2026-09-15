'use strict';
// Optional preview adapter. The original upload UI and processing implementation remain intact.
window.orqelisAuthReady = (async () => {
  if(location.pathname!=='/login'||!location.hash)return;
  const params=new URLSearchParams(location.hash.slice(1)),access=params.get('access_token');
  history.replaceState(null,'',location.pathname);
  if(access){const response=await fetch('/api/v1/auth/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:access})});if(response.ok){location.replace('/dashboard');await new Promise(()=>{});}}
})();
const previewObserver = new MutationObserver(() => {
  const main=document.querySelector('#main');if(!main)return;
  if(!document.querySelector('#preview-banner')){const banner=document.createElement('div');banner.id='preview-banner';banner.className='notice info';banner.textContent='Private preview · Use test data. File uploads and automated document processing are temporarily paused. Manual evidence entry is available.';main.before(banner);}
  const form=document.querySelector('#upload-form');if(form&&!form.dataset.disabled){form.dataset.disabled='true';form.replaceChildren();const note=document.createElement('p');note.textContent='Uploads are temporarily paused. Add a manual capability below. Existing documents remain stored for later use.';form.append(note);}
  for(const selector of ['#review-dossier','#refresh-source']){const button=document.querySelector(selector);if(button)button.remove();}
  const confirm=document.querySelector('#state option[value="USER_CONFIRMED"]');if(confirm&&!document.querySelector('#document_id option[value]:not([value=""])'))confirm.disabled=true;
});
previewObserver.observe(document.documentElement,{childList:true,subtree:true});
