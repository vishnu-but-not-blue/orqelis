'use strict';
// Basic consent mode: no Google request, cookie, or queued event before opt-in.
// Event parameters are constructed here from a closed vocabulary, never from forms/API data.
window.OrqelisAnalytics = (() => {
  const measurementId = 'G-GHGKC163XE';
  const consentKey = 'orqelis.analytics-consent.v1';
  const pendingKey = 'orqelis.analytics-navigation.v1';
  const navigationEvents = new Set(['login','sign_up','onboarding_complete']);
  const allowedEvents = new Set(['page_view','auth_start','login','sign_up','onboarding_complete','opportunity_view','assessment_start','assessment_complete','decision_complete']);
  const publicPaths = new Set(['/','/de/','/fr/','/es/','/it/','/nl/','/pl/','/pt/','/guides/find-eu-tenders','/guides/bid-no-bid-decisions','/guides/cross-border-tender-qualification','/legal/sources']);
  const languageCodes = ['en','de','fr','es','it','nl','pl','pt'];
  const copy = {
    en:['Analytics preferences','Help improve Orqelis? Optional Google Analytics measures visits and basic actions. It receives no form contents, tender details or account identifiers. Google processes device and network information. Your choice does not affect access.','Allow analytics','Reject analytics','Privacy details'],
    de:['Analyse-Einstellungen','Orqelis verbessern? Optionales Google Analytics misst Besuche und grundlegende Aktionen. Keine Formularinhalte, Ausschreibungsdetails oder Kontokennungen werden übermittelt. Google verarbeitet Geräte- und Netzwerkinformationen. Ihre Wahl beeinflusst den Zugang nicht.','Analyse erlauben','Analyse ablehnen','Datenschutzdetails'],
    fr:['Préférences statistiques','Améliorer Orqelis ? Google Analytics mesure les visites et les actions simples, uniquement avec votre accord. Aucun contenu de formulaire, détail d’appel d’offres ou identifiant de compte n’est transmis. Google traite des données techniques et réseau. Votre choix ne limite pas l’accès.','Autoriser les statistiques','Refuser les statistiques','Confidentialité'],
    es:['Preferencias de análisis','¿Ayudar a mejorar Orqelis? Google Analytics mide visitas y acciones básicas de forma opcional. No recibe formularios, detalles de licitaciones ni identificadores de cuenta. Google procesa información del dispositivo y la red. Su elección no afecta al acceso.','Permitir análisis','Rechazar análisis','Privacidad'],
    it:['Preferenze di analisi','Vuoi migliorare Orqelis? Google Analytics misura visite e azioni di base solo con il consenso. Non riceve contenuti dei moduli, dettagli delle gare o identificativi degli account. Google tratta dati del dispositivo e della rete. La scelta non limita l’accesso.','Consenti analisi','Rifiuta analisi','Privacy'],
    nl:['Analysevoorkeuren','Orqelis helpen verbeteren? Optionele Google Analytics meet bezoeken en eenvoudige acties. Geen formulierinhoud, aanbestedingsdetails of accountidentificaties worden verstuurd. Google verwerkt apparaat- en netwerkgegevens. Uw keuze heeft geen invloed op toegang.','Analyse toestaan','Analyse weigeren','Privacyinformatie'],
    pl:['Ustawienia analityki','Pomóc ulepszyć Orqelis? Opcjonalne Google Analytics mierzy wizyty i podstawowe działania. Nie otrzymuje treści formularzy, szczegółów przetargów ani identyfikatorów kont. Google przetwarza dane urządzenia i sieci. Wybór nie wpływa na dostęp.','Zezwól na analitykę','Odrzuć analitykę','Prywatność'],
    pt:['Preferências de análise','Ajudar a melhorar o Orqelis? O Google Analytics opcional mede visitas e ações básicas. Não recebe formulários, detalhes de concursos ou identificadores de conta. A Google trata dados do dispositivo e da rede. A escolha não afeta o acesso.','Permitir análise','Rejeitar análise','Privacidade']
  };
  const language = () => {let code=document.documentElement.lang;try{if(!document.body.dataset.public)code=localStorage.getItem('orqelis.language')||code;}catch{}return languageCodes.includes(code)?code:'en';};
  let consent = 'unset', loaded = false;
  try {const record=JSON.parse(localStorage.getItem(consentKey));if(record && Date.now()-record.at<180*86400000 && ['granted','denied'].includes(record.value))consent=record.value;} catch {}
  if(navigator.globalPrivacyControl || navigator.doNotTrack==='1')consent='denied';
  const enabled = () => consent==='granted' && !navigator.globalPrivacyControl && navigator.doNotTrack!=='1' && location.hostname==='orqelis.pro' && location.protocol==='https:' && /^G-[A-Z0-9]+$/.test(measurementId);
  const safePath = () => publicPaths.has(location.pathname) ? location.pathname : '/app';
  function gtag(){window.dataLayer.push(arguments);}
  function navigationEvent(name) {
    if(!enabled() || !navigationEvents.has(name))return;
    // Carry only a fixed event name across a same-tab redirect. No account data.
    // Sending on the destination avoids losing Google's buffered hit on unload.
    try {sessionStorage.setItem(pendingKey,JSON.stringify({name,at:Date.now()}));}
    catch {return event(name);}
  }
  function event(name) {
    if(!enabled() || !loaded || !allowedEvents.has(name))return;
    // No arguments from callers are accepted. Never read titles, input values, API bodies,
    // query strings, hashes, document IDs, user IDs, or arbitrary data attributes.
    if(name==='page_view' && !publicPaths.has(location.pathname))return;
    return new Promise(resolve=>{
      const done=()=>{clearTimeout(timer);resolve();};
      const timer=setTimeout(resolve,1500);
      gtag('event',name,{page_location:'https://orqelis.pro'+safePath(),page_title:publicPaths.has(location.pathname)?'Orqelis public information':'Orqelis workspace',page_referrer:'',language:language(),send_to:measurementId,event_callback:done,event_timeout:1200});
    });
  }
  function start() {
    if(!enabled() || loaded)return;
    loaded=true;window['ga-disable-'+measurementId]=false;window.dataLayer=window.dataLayer||[];
    gtag('consent','default',{analytics_storage:'granted',ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied'});
    gtag('js',new Date());
    let referrer='';
    try {const u=new URL(document.referrer);if(['www.google.com','www.google.de','www.google.fr','www.google.es','www.google.it','www.google.nl','www.google.pl','www.google.pt','www.bing.com','duckduckgo.com'].includes(u.hostname))referrer='https://'+u.hostname+'/';} catch {}
    gtag('config',measurementId,{send_page_view:false,allow_google_signals:false,allow_ad_personalization_signals:false,ignore_referrer:!referrer,page_location:'https://orqelis.pro'+safePath(),page_title:publicPaths.has(location.pathname)?'Orqelis public information':'Orqelis workspace',page_referrer:referrer,cookie_domain:'orqelis.pro',cookie_expires:15552000,cookie_update:false,cookie_flags:'SameSite=Strict;Secure'});
    const script=document.createElement('script');script.async=true;script.src='https://www.googletagmanager.com/gtag/js?id='+measurementId;document.head.append(script);
    event('page_view');
    try {
      const pending=JSON.parse(sessionStorage.getItem(pendingKey));
      sessionStorage.removeItem(pendingKey);
      if(pending && navigationEvents.has(pending.name) && Number.isFinite(pending.at) && Date.now()-pending.at>=0 && Date.now()-pending.at<120000)event(pending.name);
    } catch {}
  }
  function choose(value) {
    consent=value;try {localStorage.setItem(consentKey,JSON.stringify({value,at:Date.now()}));} catch {}
    panel.hidden=true;
    if(value==='granted')start();
    else {
      try {sessionStorage.removeItem(pendingKey);} catch {}
      window['ga-disable-'+measurementId]=true;
      for(const cookie of document.cookie.split(';')) {
        const name=cookie.split('=')[0].trim();if(!/^_ga(?:_|$)/.test(name))continue;
        for(const domain of ['', ';domain=orqelis.pro',';domain=.orqelis.pro'])document.cookie=name+'=;Max-Age=0;path=/'+domain+';Secure;SameSite=Strict';
      }
      // Remove loaded Google listeners after withdrawing previously granted consent.
      if(loaded)location.reload();
    }
  }
  const panel=document.createElement('section');panel.className='analytics-consent';panel.setAttribute('aria-label',copy[language()][0]);panel.hidden=consent!=='unset';
  const heading=document.createElement('h2'),text=document.createElement('p'),actions=document.createElement('div'),allow=document.createElement('button'),deny=document.createElement('button'),privacy=document.createElement('a');
  heading.textContent=copy[language()][0];text.textContent=copy[language()][1];allow.textContent=copy[language()][2];deny.textContent=copy[language()][3];privacy.textContent=copy[language()][4];privacy.href='/legal/privacy#analytics';allow.type=deny.type='button';allow.dataset.analyticsAllow='';deny.dataset.analyticsDeny='';allow.addEventListener('click',()=>choose('granted'));deny.addEventListener('click',()=>choose('denied'));actions.append(allow,deny,privacy);panel.append(heading,text,actions);document.body.append(panel);
  let settings=document.querySelector('[data-analytics-settings]');
  if(!settings){settings=document.createElement('button');settings.type='button';settings.className='analytics-settings';document.body.append(settings);}
  settings.textContent=copy[language()][0];settings.addEventListener('click',()=>{panel.hidden=false;allow.focus();});
  start();
  if(!enabled())try {sessionStorage.removeItem(pendingKey);} catch {}
  return Object.freeze({event,navigationEvent});
})();
