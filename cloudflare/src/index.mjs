import postgres from 'postgres';
import shell from '../generated/shell.mjs';
import {api} from './api.mjs';
import {json,fail} from './utils.mjs';
import {syncTed,sweep} from './ted.mjs';
const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function connect(env){if(!env.DB?.connectionString)fail(503,'Database connection is not configured.');return postgres(env.DB.connectionString,{max:1,prepare:false,fetch_types:false,connect_timeout:10,idle_timeout:5,onnotice:()=>{}});}
function origin(request,env){const url=new URL(request.url);if(!env.BASE_URL||url.origin!==env.BASE_URL)fail(400,'Unconfigured application hostname.');const header=request.headers.get('Origin');if(!['GET','HEAD','OPTIONS'].includes(request.method)&&header&&header!==url.origin)fail(403,'Untrusted request origin.');if(request.headers.get('Sec-Fetch-Site')==='cross-site'&&!['GET','HEAD'].includes(request.method))fail(403,'Cross-site request denied.');}
const pages=new Set(['login','dashboard','opportunities','watchlist','evidence','company','notifications','settings','onboarding']);
async function handle(request,env,ctx){
  const url=new URL(request.url),path=url.pathname;
  origin(request,env);
  if(path==='/liveness')return json({status:'alive',release:'restricted-preview'});
  if(path==='/readiness'){
    if(env.RELEASE_MODE!=='restricted-preview'||!env.PREVIEW_ALLOWED_EMAILS||!env.SUPABASE_URL||!env.SUPABASE_ANON_KEY||env.DOCUMENT_UPLOADS_ENABLED!=='false'||env.DOCUMENT_PROCESSING_ENABLED!=='false')fail(503,'Release configuration is incomplete.');
    const sql=connect(env);try{const [v]=await sql`select version_num from alembic_version`;if(v?.version_num!=='72c149c94201')fail(503,'Database migration is required.');return json({status:'ready',document_uploads:false,document_processing:false});}finally{ctx.waitUntil(sql.end({timeout:5}));}
  }
  if(path.startsWith('/static/'))return env.ASSETS.fetch(request);
  if(path.startsWith('/api/v1/')){const sql=connect(env);try{return await sql.begin(tx=>api(request,env,tx));}finally{ctx.waitUntil(sql.end({timeout:5}));}}
  if(!['GET','HEAD'].includes(request.method))fail(405,'Method not allowed.');
  if(path==='/')return Response.redirect(url.origin+'/dashboard',302);
  if(path.startsWith('/legal/'))return new Response(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Orqelis preview information</title><link rel="stylesheet" href="/static/app.css"><main class="panel panel-pad" style="max-width:800px;margin:48px auto"><h1>Restricted Orqelis preview</h1><p>This deployment is available only to invited accounts while operator details and public release terms are being completed. It is not open for public registration. No payments are collected.</p><p>Account details, company profiles and manual evidence are stored in the existing Supabase project and processed by Cloudflare Workers. Use test data during this preview. Export and deletion controls are available in workspace settings.</p><p>Document uploads and automated document processing are temporarily disabled. Manual declarations do not prove mandatory eligibility.</p><p>Public procurement data: TED / Publications Office of the European Union. Analysis is independent and is not endorsed by EU institutions. Consult the authoritative notice before making a bid decision.</p><a href="https://ted.europa.eu/en/legal-notice" rel="noopener noreferrer">TED legal notice</a><p><a href="/dashboard">Return to workspace</a></p></main></html>`,{headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}});
  const page=path.slice(1);if(!pages.has(page)&&!/^opportunities\/[a-f0-9]{32}$/.test(page))fail(404,'Page not found.');
  const html=shell.replaceAll('{{ config.app_name }}','Orqelis').replaceAll('{{ config.environment }}','production').replaceAll('{{ config.auth_provider }}','supabase').replaceAll('{{ page }}',escape(page)).replace('<body ','<body data-document-uploads="false" data-document-processing="false" data-release-mode="restricted-preview" ').replace('<script src="/static/app.js" defer></script>','<script src="/static/cloudflare-preview.js" defer></script><script src="/static/app.js" defer></script>');
  return new Response(html,{headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}});
}
export default {
  async fetch(request,env,ctx){
    let response;const requestId=crypto.randomUUID();
    try{response=await handle(request,env,ctx);}catch(error){
      const status=error.status||503;
      console.error(JSON.stringify({requestId,status,error:error.status?'request_rejected':error.code||error.name||'Error',frames:error.status?undefined:String(error.stack||'').split('\n').slice(1,4)}));
      response=json({error:{code:status===503?'unavailable':'request_failed',message:error.status?error.message:'This operation could not complete. Please retry.',request_id:requestId}},status);
    }
    const headers=new Headers(response.headers);headers.set('X-Content-Type-Options','nosniff');headers.set('Referrer-Policy','no-referrer');headers.set('X-Frame-Options','DENY');headers.set('X-Robots-Tag','noindex, nofollow');headers.set('Strict-Transport-Security','max-age=31536000');headers.set('Permissions-Policy','camera=(), microphone=(), geolocation=()');headers.set('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");return new Response(response.body,{status:response.status,headers});
  },
  async scheduled(controller,env,ctx){const sql=connect(env);ctx.waitUntil((async()=>{try{await sql.begin(tx=>sweep(tx));await sql.begin(tx=>syncTed(tx));console.log(JSON.stringify({operation:'scheduled',result:'done'}));}catch(error){console.error(JSON.stringify({operation:'scheduled',result:'retry_next_schedule',error:error.code||error.name}));}finally{await sql.end({timeout:5});}})());}
};
