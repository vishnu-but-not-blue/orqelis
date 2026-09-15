import * as S from './schemas.mjs';
import {canonical,analyzeLots,ALGORITHM_VERSION} from './decision.mjs';
import {id,token,sha,stable,fail,equal,json,input,attachment} from './utils.mjs';
import {syncTed} from './ted.mjs';

const PLANS={FREE:{analyses:20,documents:20,members:3},SME:{analyses:300,documents:200,members:10},PRO:{analyses:1000,documents:1000,members:30},ADVISOR:{analyses:2000,documents:2000,members:50}};
const cookie=v=>`session=${v}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${v?43200:0}`;
async function allowed(sql,env,email){
  if(env.RELEASE_MODE!=='restricted-preview')fail(503,'This deployment is restricted to invited preview accounts.');
  if((env.PREVIEW_ALLOWED_EMAILS||'').toLowerCase().split(',').map(x=>x.trim()).includes(email))return;
  const [invited]=await sql`select id from invitations where email=${email} and expires_at>now() limit 1`;
  const [member]=await sql`select m.id from memberships m join users u on u.id=m.user_id where u.email=${email} limit 1`;
  if(!invited&&!member)fail(403,'This preview is invitation-only. Contact the workspace owner.');
}
async function provider(env,path,body,bearer){
  const response=await fetch(env.SUPABASE_URL.replace(/\/$/,'')+'/auth/v1/'+path,{method:body?'POST':'GET',headers:{apikey:env.SUPABASE_ANON_KEY,'Content-Type':'application/json',...(bearer?{Authorization:'Bearer '+bearer}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(15000),redirect:'error'});
  if(!response.ok)fail(response.status===429?429:response.status>=500?503:401,path.startsWith('otp')?'Unable to send a sign-in code. Check email configuration or retry later.':'Invalid or expired sign-in code.');
  return response.json();
}
export async function principal(sql,request){
  const raw=(request.headers.get('Cookie')||'').match(/(?:^|;\s*)session=([^;]*)/)?.[1]||'';
  if(!/^[a-f0-9]{64}$/.test(raw))fail(401,'Sign in to continue.');
  const [session]=await sql`select s.*,u.email,u.name from sessions s join users u on u.id=s.user_id where s.token_hash=${await sha(raw)} and s.expires_at>now()`;
  if(!session)fail(401,'Sign in to continue.');
  if(!['GET','HEAD','OPTIONS'].includes(request.method)&&!equal(request.headers.get('X-CSRF-Token')||'',session.csrf))fail(403,'Invalid CSRF token. Refresh the page and retry.');
  return session;
}
async function audit(sql,org,user,operation,target=''){await sql`insert into audit_events(id,organization_id,user_id,operation,target,created_at) values(${id()},${org},${user},${operation},${target},now())`;}
async function invalidate(sql,org){await sql`update organizations set capability_version=capability_version+1 where id=${org}`;await sql`update opportunity_analyses set stale=true where organization_id=${org}`;}
async function notice(sql,noticeId){const [n]=await sql`select n.*,v.normalized,v.content_hash,v.source_version,v.fetched_at,v.publication_number from source_notices n join notice_versions v on v.id=n.current_version_id where n.id=${noticeId}`;if(!n)fail(404,'Opportunity not found.');return n;}
async function analysis(sql,orgId,user,noticeId){
  const [org]=await sql`select * from organizations where id=${orgId} for update`;
  const n=await notice(sql,noticeId),corrections=await sql`select id,requirement_id,data,reason from corrections where organization_id=${orgId} and notice_id=${noticeId} and version_id=${n.current_version_id} order by created_at`;
  const key=await sha(stable([n.content_hash,org.capability_version,ALGORITHM_VERSION,corrections,new Date().toISOString().slice(0,10)]));
  const [cached]=await sql`select id,result,stale from opportunity_analyses where organization_id=${orgId} and cache_key=${key} and stale=false`;if(cached)return cached;
  const [used]=await sql`select count(*)::int as count from usage_events where organization_id=${orgId} and kind='analysis' and created_at>=date_trunc('month',now())`;
  if(used.count>=(PLANS[org.plan]||PLANS.FREE).analyses)fail(429,'Your monthly analysis quota has been reached.');
  const normalized=structuredClone(n.normalized);
  for(const c of corrections){if(c.requirement_id==='__dossier__'){
    const [doc]=await sql`select id from documents where id=${c.data.document_id||''} and organization_id=${orgId} and status='READY'`;
    if(doc){normalized.requirements.push(...(c.data.requirements||[]));if(c.data.complete){if(c.data.lot_id){const lot=normalized.lots?.find(l=>l.id===c.data.lot_id);if(lot)lot.requirements_complete=true;}else if(!normalized.lots?.length)normalized.requirements_complete=true;}}
  }else for(const r of normalized.requirements||[])if(r.id===c.requirement_id)Object.assign(r,c.data,{user_correction:c.reason});}
  const evidence=await sql`select e.*,coalesce(d.status='READY',false) as document_available from evidence e left join documents d on d.id=e.document_id and d.organization_id=e.organization_id where e.organization_id=${orgId}`;
  const result={...analyzeLots(normalized,org.profile,evidence),notice_version:n.source_version,source_url:normalized.source_url,source_hash:n.content_hash,company_capability_version:org.capability_version,corrections};
  const aid=id();await sql`insert into opportunity_analyses(id,organization_id,notice_id,version_id,cache_key,result,stale,created_at) values(${aid},${orgId},${noticeId},${n.current_version_id},${key},${sql.json(result)},false,now())`;
  await sql`insert into usage_events(id,organization_id,kind,amount,created_at) values(${id()},${orgId},'analysis',1,now())`;await audit(sql,orgId,user,'analysis.created',noticeId);return {id:aid,result,stale:false};
}
export async function api(request,env,sql){
  const url=new URL(request.url),path=url.pathname.replace(/^\/api\/v1/,''),method=request.method;
  const out=data=>json(data),ok=()=>out({ok:true});
  if(path==='/features'&&method==='GET')return out({document_uploads:false,document_processing:false,manual_evidence:true,release_mode:'restricted-preview',restore_note:'Uploads can return after a scanner-backed processing service is configured.'});
  if(path==='/sources'&&method==='GET')return out({source:'TED / Publications Office of the European Union',legal_notice:'https://ted.europa.eu/en/legal-notice',attribution:'Independent analysis. No endorsement by EU institutions.'});
  if(path==='/auth/request'&&method==='POST'){
    const body=await input(request,S.login);await allowed(sql,env,body.email);
    // Shared database throttle survives isolates and concurrent requests.
    await sql`select pg_advisory_xact_lock(hashtext(${body.email}))`;
    const [recent]=await sql`select id from login_links where email=${body.email} and name='cloudflare-otp-throttle' and expires_at>now() limit 1`;if(recent)fail(429,'Wait one minute before requesting another sign-in email.');
    await provider(env,'otp?redirect_to='+encodeURIComponent(env.BASE_URL+'/login'),{email:body.email,create_user:true,data:{full_name:body.name||body.email.split('@')[0]}});
    await sql`insert into login_links(id,token_hash,email,name,expires_at) values(${id()},${await sha(token())},${body.email},'cloudflare-otp-throttle',now()+interval '1 minute')`;
    return out({message:'Check your email for your sign-in link or one-time code.',provider:'supabase'});
  }
  if(path==='/auth/verify'&&method==='POST'){
    const body=await input(request,S.verify);if(body.email)await allowed(sql,env,body.email);
    const access=body.email?(await provider(env,'verify',{email:body.email,token:body.token,type:'email'})).access_token:body.token;
    const identity=await provider(env,'user',null,access);if(!identity.id||!identity.email||!identity.email_confirmed_at)fail(401,'A verified email identity is required.');
    const email=identity.email.toLowerCase();await allowed(sql,env,email);const subject='supabase:'+identity.id;
    await sql`select pg_advisory_xact_lock(hashtext(${email}))`;
    let [user]=await sql`select * from users where auth_subject=${subject}`;
    if(!user){[user]=await sql`select * from users where email=${email}`;if(user&&user.auth_subject&&user.auth_subject!==subject)fail(409,'This email is linked to another identity.');if(user){await sql`update users set auth_subject=${subject} where id=${user.id}`;}else{[user]=await sql`insert into users(id,email,name,auth_subject,created_at) values(${id()},${email},${String(identity.user_metadata?.full_name||email.split('@')[0]).slice(0,120)},${subject},now()) returning *`;}}
    const [membership]=await sql`select organization_id from memberships where user_id=${user.id} order by id limit 1`,raw=token(),csrf=token();
    await sql`insert into sessions(id,token_hash,user_id,organization_id,expires_at,csrf) values(${id()},${await sha(raw)},${user.id},${membership?.organization_id||null},now()+interval '12 hours',${csrf})`;
    return json({csrf,organization_id:membership?.organization_id||null},200,{'Set-Cookie':cookie(raw)});
  }
  const session=await principal(sql,request),user=session.user_id;
  if(path==='/auth/logout'&&method==='POST'){await sql`delete from sessions where id=${session.id}`;return json({ok:true},200,{'Set-Cookie':cookie('')});}
  if(path==='/auth/me'&&method==='GET'){const organizations=await sql`select o.id,o.name,m.role from memberships m join organizations o on o.id=m.organization_id where m.user_id=${user}`;return out({id:user,name:session.name,email:session.email,csrf:session.csrf,organization_id:session.organization_id,organizations});}
  if(path==='/organizations'&&method==='POST'){
    const body=await input(request,S.org);await sql`select id from users where id=${user} for update`;const [count]=await sql`select count(*)::int as count from memberships where user_id=${user}`;if(count.count>=10)fail(409,'Organization limit reached.');const oid=id();
    await sql`insert into organizations(id,name,capability_version,profile,plan) values(${oid},${body.name},1,${sql.json(S.profile.parse({}))},'FREE')`;
    await sql`insert into memberships(id,organization_id,user_id,role) values(${id()},${oid},${user},'OWNER')`;await sql`update sessions set organization_id=${oid} where id=${session.id}`;await audit(sql,oid,user,'organization.created',oid);return out({id:oid,name:body.name});
  }
  let match;
  if((match=path.match(/^\/organizations\/([a-f0-9]{32})\/switch$/))&&method==='POST'){const [m]=await sql`select id from memberships where user_id=${user} and organization_id=${match[1]}`;if(!m)fail(404,'Organization not found.');await sql`update sessions set organization_id=${match[1]} where id=${session.id}`;return ok();}
  if(path==='/memberships/accept'&&method==='POST'){
    const body=await input(request,S.token),[inv]=await sql`select * from invitations where token_hash=${await sha(body.token)} and email=${session.email} and expires_at>now() for update`;if(!inv)fail(404,'Valid invitation not found for this account.');
    await sql`insert into memberships(id,organization_id,user_id,role) values(${id()},${inv.organization_id},${user},${inv.role}) on conflict(organization_id,user_id) do nothing`;await sql`update sessions set organization_id=${inv.organization_id} where id=${session.id}`;await sql`delete from invitations where id=${inv.id}`;return ok();
  }
  if(path==='/account'&&method==='DELETE'){
    const owned=await sql`select o.id from organizations o join memberships m on m.organization_id=o.id where m.user_id=${user} and m.role='OWNER' for update of o`;
    for(const o of owned){const [count]=await sql`select count(*)::int as count from memberships where organization_id=${o.id}`;if(count.count>1)fail(409,'Remove team memberships before deleting an owned organization.');const docs=await sql`select object_key from documents where organization_id=${o.id}`;for(const d of docs)await deleteObject(env,d.object_key);await sql`delete from jobs where payload->>'organization_id'=${o.id}`;await sql`delete from organizations where id=${o.id}`;}
    await sql`delete from users where id=${user}`;return json({ok:true,message:'Active application data deleted. Supabase sign-in identity is retained; contact the operator to remove it.'},200,{'Set-Cookie':cookie('')});
  }
  const [org]=await sql`select o.*,m.role from organizations o join memberships m on m.organization_id=o.id where o.id=${session.organization_id} and m.user_id=${user}`;
  if(!org)fail(409,'Create or join an organization first.');const oid=org.id;
  if(!['GET','HEAD','OPTIONS'].includes(method)&&org.role==='VIEWER')fail(403,'Viewer access is read-only.');
  const admin=()=>{if(!['OWNER','ADMIN'].includes(org.role))fail(403,'An organization administrator is required.');};
  if(path==='/company'&&method==='GET')return out(org);
  if(path==='/company'&&method==='PUT'){const p=await input(request,S.profile);await sql`update organizations set profile=${sql.json(p)} where id=${oid}`;await invalidate(sql,oid);await audit(sql,oid,user,'profile.updated');return out({ok:true,capability_version:org.capability_version+1});}
  if(path==='/memberships'&&method==='GET')return out(await sql`select m.id,m.user_id,m.role,u.email from memberships m join users u on u.id=m.user_id where m.organization_id=${oid}`);
  if(path==='/memberships/invite'&&method==='POST'){
    admin();const body=await input(request,S.invite);await sql`select id from organizations where id=${oid} for update`;
    const [count]=await sql`select (select count(*) from memberships where organization_id=${oid})+(select count(*) from invitations where organization_id=${oid} and expires_at>now()) as count`;if(Number(count.count)>=(PLANS[org.plan]||PLANS.FREE).members)fail(429,'Your team member quota has been reached.');
    const raw=token();await sql`insert into invitations(id,organization_id,email,role,token_hash,expires_at) values(${id()},${oid},${body.email},${body.role},${await sha(raw)},now()+interval '7 days')`;await audit(sql,oid,user,'membership.invited');return out({invitation_code:raw,expires_in_days:7,message:'Share this one-use code with the intended team member.'});
  }
  if((match=path.match(/^\/memberships\/([a-f0-9]{32})$/))&&method==='DELETE'){admin();const [m]=await sql`select * from memberships where id=${match[1]} and organization_id=${oid}`;if(!m)fail(404,'Record not found.');if(m.role==='OWNER')fail(409,'The organization owner cannot be removed.');await sql`delete from memberships where id=${m.id} and organization_id=${oid}`;await audit(sql,oid,user,'membership.removed',m.id);return ok();}
  if(path==='/documents'&&method==='GET')return out(await sql`select id,filename,mime,size,status,created_at,content_hash from documents where organization_id=${oid} order by created_at desc`);
  if(path==='/documents'&&method==='POST')fail(503,'Document uploads are temporarily disabled. Use manual evidence entry; document processing can be restored later.');
  if((match=path.match(/^\/documents\/([a-f0-9]{32})(?:\/(access|download))?$/))){const [doc]=await sql`select * from documents where id=${match[1]} and organization_id=${oid}`;if(!doc)fail(404,'Record not found.');
    if(method==='DELETE'&&!match[2]){await deleteObject(env,doc.object_key);await sql`delete from documents where id=${doc.id} and organization_id=${oid}`;await invalidate(sql,oid);await sql`delete from opportunity_analyses where organization_id=${oid}`;await audit(sql,oid,user,'document.deleted',doc.id);return ok();}
    if(method==='GET'&&!match[2])return out({id:doc.id,filename:doc.filename,status:doc.status,text:doc.status==='READY'?doc.text:'',content_hash:doc.content_hash});
    if(doc.status!=='READY')fail(409,'Document is unavailable until validation passes.');
    if(method==='POST'&&match[2]==='access'){const minute=Math.floor(Date.now()/60000),grant=await sha(session.csrf+'|'+doc.id+'|'+minute);return out({access_token:minute+'.'+grant,expires_in:60});}
    if(method==='GET'&&match[2]==='download'){const grant=request.headers.get('X-Document-Token')||'',[minute,sig]=grant.split('.');if(!/^\d+$/.test(minute)||Number(minute)!==Math.floor(Date.now()/60000)||!equal(sig,await sha(session.csrf+'|'+doc.id+'|'+minute)))fail(403,'Document access grant is invalid or expired.');const response=await fetchObject(env,doc.object_key);return new Response(response.body,{headers:{'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename="evidence-document"','Cache-Control':'no-store'}});}
  }
  if(path==='/evidence'&&method==='GET')return out(await sql`select e.*,coalesce(d.status='READY',false) as document_available from evidence e left join documents d on d.id=e.document_id and d.organization_id=e.organization_id where e.organization_id=${oid}`);
  if((path==='/evidence'&&method==='POST')||((match=path.match(/^\/evidence\/([a-f0-9]{32})$/))&&method==='PUT')){
    const body=await input(request,S.evidence);let eid=id();if(method==='PUT'){eid=match[1];const [existing]=await sql`select id from evidence where id=${eid} and organization_id=${oid}`;if(!existing)fail(404,'Record not found.');}
    let doc=null;if(body.document_id){[doc]=await sql`select * from documents where id=${body.document_id} and organization_id=${oid}`;if(!doc)fail(404,'Document not found.');}
    if(body.state==='USER_CONFIRMED'&&(!doc||doc.status!=='READY'||!body.locator||!body.source_excerpt||!doc.text.includes(body.source_excerpt)))fail(422,'Confirmation requires a validated document, source locator and exact excerpt. Manual declarations remain unverified.');
    const data={value:body.value,currency:body.currency,annual_values:body.annual_values,issuer:body.issuer,jurisdiction:body.jurisdiction,source_excerpt:body.source_excerpt,confidence:body.state==='USER_CONFIRMED'?1:.3,extraction_version:'manual-1',content_hash:doc?.content_hash||null};
    if(method==='POST')await sql`insert into evidence(id,organization_id,document_id,capability,data,state,valid_from,valid_until,locator) values(${eid},${oid},${body.document_id},${canonical(body.capability)},${sql.json(data)},${body.state},${body.valid_from},${body.valid_until},${body.locator||'Self-declared; no documentary locator'})`;
    else await sql`update evidence set document_id=${body.document_id},capability=${canonical(body.capability)},data=${sql.json(data)},state=${body.state},valid_from=${body.valid_from},valid_until=${body.valid_until},locator=${body.locator||'Self-declared; no documentary locator'} where id=${eid} and organization_id=${oid}`;
    await invalidate(sql,oid);await audit(sql,oid,user,'evidence.updated',eid);return out({id:eid,state:body.state});
  }
  if((match=path.match(/^\/evidence\/([a-f0-9]{32})$/))&&method==='DELETE'){const rows=await sql`delete from evidence where id=${match[1]} and organization_id=${oid} returning id`;if(!rows.length)fail(404,'Record not found.');await invalidate(sql,oid);await audit(sql,oid,user,'evidence.deleted',match[1]);return ok();}
  if(path==='/opportunities'&&method==='GET'){
    const q=url.searchParams.get('q')||'',country=(url.searchParams.get('country')||'').toUpperCase(),cpv=url.searchParams.get('cpv')||'',cursor=url.searchParams.get('cursor')||'',saved=url.searchParams.get('saved')==='true',limit=Math.min(100,Math.max(1,Number(url.searchParams.get('limit'))||24));if(q.length>200||cursor.length>64||cpv.length>20||country.length>8)fail(422,'Search input too long.');
    const rows=await sql`select n.id,n.source,n.title,n.country,n.published,n.deadline,n.status,v.normalized,v.fetched_at,a.result,a.stale,w.state as watch from source_notices n left join notice_versions v on v.id=n.current_version_id left join lateral (select result,stale from opportunity_analyses where notice_id=n.id and organization_id=${oid} order by created_at desc limit 1) a on true left join watchlist w on w.notice_id=n.id and w.organization_id=${oid} where (${q}='' or to_tsvector('simple',n.search_text)@@plainto_tsquery('simple',${q})) and (${country}='' or n.country=${country}) and (${cpv}='' or position(${cpv} in n.search_text)>0) and n.id>${cursor} and (${saved}=false or w.state in ('WATCH','SAVED')) order by n.id limit ${limit+1}`;
    return out({items:rows.slice(0,limit).map(({normalized:n,result,stale,...row})=>({...row,buyer:n?.buyer,value:n?.value,currency:n?.currency,cpv_codes:n?.cpv_codes||[],decision:result&&!stale?result.decision:'UNASSESSED'})),next_cursor:rows.length>limit?rows[limit-1].id:null});
  }
  if((match=path.match(/^\/opportunities\/([a-f0-9]{32})(?:\/(requirements|analysis|corrections|outcome|refresh-source|dossier-review))?$/))){
    const nid=match[1],action=match[2],n=await notice(sql,nid);
    if(method==='GET'&&!action){const versions=await sql`select id,source_version as version,content_hash,fetched_at from notice_versions where notice_id=${nid} order by fetched_at desc limit 100`,changes=await sql`select change_class as class,fields,created_at from notice_changes where notice_id=${nid} order by created_at desc limit 100`;return out({id:nid,source:n.source,facts:n.normalized,version_id:n.current_version_id,fetched_at:n.fetched_at,versions,changes});}
    if(method==='GET'&&action==='requirements')return out(n.normalized.requirements||[]);
    if(method==='GET'&&action==='analysis'){const [a]=await sql`select id,result,stale from opportunity_analyses where organization_id=${oid} and notice_id=${nid} order by created_at desc limit 1`;return out(a||{result:null});}
    if(method==='POST'&&action==='analysis')return out(await analysis(sql,oid,user,nid));
    if(method==='POST'&&action==='corrections'){const body=await input(request,S.correction);if(!(n.normalized.requirements||[]).some(r=>r.id===body.requirement_id))fail(404,'Requirement not found.');await sql`insert into corrections(id,organization_id,notice_id,version_id,requirement_id,data,reason,created_at) values(${id()},${oid},${nid},${n.current_version_id},${body.requirement_id},${sql.json({hard_gate:body.hard_gate})},${body.reason},now())`;await invalidate(sql,oid);await audit(sql,oid,user,'requirement.corrected',nid);return ok();}
    if(method==='POST'&&action==='outcome'){const body=await input(request,S.outcome);await sql`insert into outcomes(id,organization_id,notice_id,data) values(${id()},${oid},${nid},${sql.json(body)})`;return ok();}
    if(method==='POST'&&['dossier-review','refresh-source'].includes(action))fail(503,'Automated source-document processing is temporarily disabled. Open the authoritative TED notice; existing assessments retain their source history.');
  }
  if(path==='/watchlist'&&method==='GET')return out(await sql`select notice_id,state,reason,assigned_to from watchlist where organization_id=${oid}`);
  if((match=path.match(/^\/watchlist\/([a-f0-9]{32})$/))&&method==='PUT'){await notice(sql,match[1]);const body=await input(request,S.watch);if(body.assigned_to){const [m]=await sql`select id from memberships where user_id=${body.assigned_to} and organization_id=${oid}`;if(!m)fail(422,'Assignee must belong to your organization.');}await sql`insert into watchlist(id,organization_id,notice_id,state,reason,assigned_to,preference) values(${id()},${oid},${match[1]},${body.state},${body.reason},${body.assigned_to},${body.preference}) on conflict(organization_id,notice_id) do update set state=excluded.state,reason=excluded.reason,assigned_to=excluded.assigned_to,preference=excluded.preference`;return ok();}
  if(path==='/notifications'&&method==='GET')return out(await sql`select id,title,body,href,read,delivered,created_at from notifications where organization_id=${oid} order by created_at desc limit 100`);
  if((match=path.match(/^\/notifications\/([a-f0-9]{32})\/read$/))&&method==='POST'){const rows=await sql`update notifications set read=true where id=${match[1]} and organization_id=${oid} returning id`;if(!rows.length)fail(404,'Record not found.');return ok();}
  if((match=path.match(/^\/exports\/analyses\/([a-f0-9]{32})$/))&&method==='GET'){const [a]=await sql`select * from opportunity_analyses where id=${match[1]} and organization_id=${oid}`;if(!a)fail(404,'Record not found.');await audit(sql,oid,user,'analysis.exported',a.id);return attachment({organization:org.name,analysis_id:a.id,historical:a.stale,report:a.result},'decision-report.json');}
  if(path==='/billing'&&method==='GET'){const usage=await sql`select kind,sum(amount)::int as amount from usage_events where organization_id=${oid} and created_at>=date_trunc('month',now()) group by kind`;return out({plan:org.plan,plans:PLANS,provider:'disabled',usage:Object.fromEntries(usage.map(x=>[x.kind,x.amount])),paid_enabled:false});}
  if(path.startsWith('/billing/')&&method==='POST')fail(503,'Paid billing is disabled; no charges are collected.');
  if(path==='/account/export'&&method==='GET'){
    const data={account:{email:session.email,name:session.name},organization:{name:org.name,profile:org.profile}};
    for(const table of ['evidence','opportunity_analyses','watchlist','corrections','notifications','outcomes','usage_events','audit_events','subscriptions','documents']){
      const [count]=await sql`select count(*)::int as count from ${sql(table)} where organization_id=${oid}`;if(count.count>2000)fail(413,'This workspace requires an operator-assisted full export.');
      data[table]=await sql`select * from ${sql(table)} where organization_id=${oid}`;
    }
    data.export_notes='JSON data export. Original document bytes can be downloaded separately from the evidence vault.';await audit(sql,oid,user,'account.exported');return attachment(data,'orqelis-account.json');
  }
  if(path==='/sources/ted/sync'&&method==='POST'){admin();const result=await syncTed(sql);return out({status:'DONE',...result});}
  if(path==='/health/organization'&&method==='GET'){admin();return out({document_uploads:false,document_processing:false,database:true});}
  fail(404,'Endpoint not found.');
}
async function fetchObject(env,key,method='GET'){
  if(!/^[a-f0-9]{64}$/.test(key))fail(422,'Invalid object key.');
  const response=await fetch(env.SUPABASE_URL+'/storage/v1/object/'+(env.SUPABASE_STORAGE_BUCKET||'documents')+'/'+key,{method,headers:{apikey:env.SUPABASE_SERVICE_ROLE_KEY,Authorization:'Bearer '+env.SUPABASE_SERVICE_ROLE_KEY},redirect:'error',signal:AbortSignal.timeout(15000)});
  if(!response.ok&&!(method==='DELETE'&&response.status===404))fail(502,'Private storage operation failed; retry.');return response;
}
async function deleteObject(env,key){await fetchObject(env,key,'DELETE');}
