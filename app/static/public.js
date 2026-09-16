'use strict';
// Public language URLs, rather than browser preference, determine indexable content.
try { if(document.body.dataset.publicLanguage) localStorage.setItem('orqelis.language',document.body.dataset.publicLanguage); } catch {}
document.querySelectorAll('[data-language]').forEach(link=>link.addEventListener('click',()=>{
  try {localStorage.setItem('orqelis.language',link.dataset.language);} catch {}
}));
