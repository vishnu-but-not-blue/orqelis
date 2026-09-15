import {id,sha,stable,bounded,fail} from './utils.mjs';
import {canonical,parseDatetime} from './decision.mjs';
const flatten=v=>v==null?[]:Array.isArray(v)?v.flatMap(flatten):typeof v==='object'?('eng' in v?flatten(v.eng):Object.values(v).flatMap(flatten)):[String(v)];
const first=(r,k,d='')=>flatten(r[k])[0]??d;
const fields=['publication-number','notice-title','publication-date','buyer-country','classification-cpv','deadline-receipt-tender-date-lot','deadline-receipt-tender-time-lot','estimated-value-proc','estimated-value-cur-proc','buyer-name','notice-type','procedure-type','notice-identifier','notice-version','change-notice-version-identifier','description-proc','selection-criterion-description-lot','submission-language','submission-url-lot','competition-termination-proc','official-language'];
export async function normalize(row){
  const publication=first(row,'publication-number');if(!/^\d+-\d{4}$/.test(publication))fail(422,'Invalid authoritative publication number.');
  const dates=[...new Set(flatten(row['deadline-receipt-tender-date-lot']))],times=[...new Set(flatten(row['deadline-receipt-tender-time-lot']))];let deadline=null;
  if(dates.length===1&&times.length===1){let combined=dates[0].includes('T')?dates[0]:dates[0].slice(0,10)+'T'+times[0];if(!/(Z|[+-]\d\d:\d\d)$/.test(combined)){const zone=dates[0].match(/(Z|[+-]\d\d:\d\d)$/)?.[1];if(zone)combined+=zone;}if(parseDatetime(combined))deadline=combined;}
  const clauses=[...new Set(flatten(row['selection-criterion-description-lot']))].slice(0,100),requirements=[];
  for(let i=0;i<clauses.length;i++){const text=clauses[i].slice(0,10000),locator=`TED/${publication}/selection-criterion-description-lot/${i+1}`,cap=/ISO\s*(?:\/\s*IEC\s*)?\d{4,5}(?:-\d+)?/i.test(text)?canonical(text):/turnover|revenue/i.test(text)?'TURNOVER':/insurance|indemnity/i.test(text)?'INSURANCE':/references|similar projects/i.test(text)?'REFERENCES':'UNKNOWN';
    requirements.push({id:(await sha(locator+'|'+text+'|None')).slice(0,20),category:cap.startsWith('ISO ')?'CERTIFICATION':cap==='TURNOVER'?'FINANCIAL':cap==='INSURANCE'?'INSURANCE':cap==='REFERENCES'?'EXPERIENCE':'OTHER',text,capability:cap,comparator:'exists',threshold:null,currency:null,hard_gate:!(/\b(may|should|optional|recommended|not required)\b/i.test(text)),not_applicable:/\b(not required|no .{0,35} required|need not)\b/i.test(text),ambiguous:true,lot_id:null,confidence:.4,source_locator:locator,verification_state:'REVIEW_REQUIRED',combination_rule:'unknown_combination_rule',remediability:'CLARIFICATION_NEEDED'});
  }
  const value=Number(first(row,'estimated-value-proc',NaN));
  return {source_id:first(row,'notice-identifier',publication),source_version:first(row,'notice-version',publication),publication_number:publication,source_url:`https://ted.europa.eu/en/notice/-/detail/${publication}`,title:first(row,'notice-title','Untitled procurement notice'),description:first(row,'description-proc'),buyer:first(row,'buyer-name','Not provided'),country:first(row,'buyer-country'),cpv_codes:[...new Set(flatten(row['classification-cpv']))],published:first(row,'publication-date').slice(0,10),source_publication_date:first(row,'publication-date'),deadline,source_deadline_dates:dates,value:Number.isFinite(value)?value:null,currency:first(row,'estimated-value-cur-proc',null),notice_type:first(row,'notice-type'),procedure:first(row,'procedure-type'),status:first(row,'competition-termination-proc').toLowerCase()==='true'?'CANCELLED':first(row,'notice-type').startsWith('can-')?'AWARDED':'ACTIVE',lots:[],requirements,requirements_complete:false,languages:flatten(row['submission-language']).map(v=>v.toUpperCase()),official_languages:flatten(row['official-language']).map(v=>v.toUpperCase()),submission_urls:flatten(row['submission-url-lot']).filter(u=>u.startsWith('https://')),change_reference:first(row,'change-notice-version-identifier',null),source_format:'TED_SEARCH_JSON',parser_confidence:.8,completeness_score:clauses.length?65:45,source_fields:row,extraction_warnings:['Search metadata is not the full tender dossier. Conditions and lot associations require review against the authoritative notice. Numeric predicates are not inferred by this preview parser.']};
}
export async function notify(sql,org,key,title,body,href='/notifications'){await sql`insert into notifications(id,organization_id,dedupe_key,title,body,href,read,delivered,created_at) values(${id()},${org},${key},${title},${body},${href},false,false,now()) on conflict(organization_id,dedupe_key) do nothing`;}
export async function ingest(sql,n,raw){
  const hash=await sha(raw),identity='TED:'+n.source_id;
  let [previous]=await sql`select n.*,v.normalized from source_notices n left join notice_versions v on v.id=n.current_version_id where n.source_id=${identity} for update of n`;
  if(!previous&&n.change_reference){const ref=n.change_reference,prior=ref.length>=36&&ref[8]==='-'?ref.slice(0,36):ref;[previous]=await sql`select n.*,v.normalized from source_notices n left join notice_versions v on v.id=n.current_version_id where n.source_id=${'TED:'+prior} or n.id in (select notice_id from notice_versions where publication_number=${ref}) limit 1 for update of n`;}
  const nid=previous?.id||id();if(!previous)await sql`insert into source_notices(id,source,source_id,title,country,published,deadline,status,search_text) values(${nid},'TED',${identity},${n.title},${n.country},${n.published},${n.deadline},${n.status},'')`;
  const [existing]=await sql`select id from notice_versions where notice_id=${nid} and content_hash=${hash}`;if(existing)return false;
  const vid=id();await sql`insert into notice_versions(id,notice_id,source_version,publication_number,content_hash,raw_payload,normalized,fetched_at,parser_version) values(${vid},${nid},${n.source_version},${n.publication_number},${hash},${raw},${sql.json(n)},now(),'ted-search-cf-1')`;
  if(previous?.normalized&&n.published<(previous.normalized.published||''))return true;
  if(previous?.normalized){const changes=Object.fromEntries(Object.entries(n).filter(([k,v])=>!['source_fields','source_version','publication_number','source_url'].includes(k)&&stable(previous.normalized[k])!==stable(v)).map(([k,v])=>[k,{before:previous.normalized[k]??null,after:v}]));const severity=['deadline','requirements','description','value','lots','status','currency'].some(k=>k in changes)?'CRITICAL':['procedure','languages','buyer','country','cpv_codes'].some(k=>k in changes)?'MATERIAL':'MINOR';
    await sql`insert into notice_changes(id,notice_id,version_id,change_class,fields,created_at) values(${id()},${nid},${vid},${severity},${sql.json(changes)},now())`;
    if(severity!=='MINOR')await sql`update opportunity_analyses set stale=true where notice_id=${nid}`;
    const watches=await sql`select organization_id,preference from watchlist where notice_id=${nid} and state='WATCH'`;
    for(const w of watches)if(({MINOR:1,MATERIAL:2,CRITICAL:3}[severity])>=({MINOR:1,MATERIAL:2,CRITICAL:3}[w.preference]))await notify(sql,w.organization_id,'change:'+vid,severity+' notice change',Object.keys(changes).join(', ')+' changed. Recompute the assessment.','/opportunities/'+nid);
  }
  const search=[n.title,n.description,n.buyer,...n.cpv_codes].join(' ').toLowerCase();await sql`update source_notices set current_version_id=${vid},title=${n.title},country=${n.country},published=${n.published},deadline=${n.deadline},status=${n.status},search_text=${search} where id=${nid}`;return true;
}
export async function syncTed(sql){
  const [source]=await sql`select * from source_registry where name='TED' for update skip locked`;if(!source||!source.enabled)return {imported:0,message:'Source disabled or a sync is running.'};
  const state=source.checkpoint||{};if(state.cf_last_success&&Date.now()-Date.parse(state.cf_last_success)<60000)fail(429,'Source was refreshed recently; retry in a minute.');
  const query=state.cf_query||'publication-date >= '+new Date(Date.now()-3*86400000).toISOString().slice(0,10).replaceAll('-',''),page=state.cf_page||1;
  const response=await fetch('https://api.ted.europa.eu/v3/notices/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,fields,limit:5,page,scope:'LATEST'}),redirect:'error',signal:AbortSignal.timeout(20000)});
  if(!response.ok)fail(503,'TED is temporarily unavailable; existing notices remain accessible.');
  const payload=JSON.parse(await bounded(response,1024*1024)),rows=payload.notices||[];let imported=0;
  for(const row of rows.slice(0,5)){const n=await normalize(row);if(await ingest(sql,n,stable(row)))imported++;}
  const checkpoint={...state,cf_last_success:new Date().toISOString(),cf_query:rows.length<5?null:query,cf_page:rows.length<5?1:page+1};
  await sql`update source_registry set checkpoint=${sql.json(checkpoint)} where id=${source.id}`;return {imported,page,source:'TED',batch_size:5};
}
export async function sweep(sql){
  await sql`delete from sessions where expires_at<now()`;await sql`delete from login_links where expires_at<now()`;await sql`delete from invitations where expires_at<now()`;
  // Invalidate daily so evidence expiry and elapsed deadlines never retain a cached PASS.
  await sql`update opportunity_analyses set stale=true where stale=false and created_at<date_trunc('day',now())`;
  const evidence=await sql`select id,organization_id,valid_until from evidence where valid_until is not null and valid_until<=to_char(now()+interval '30 days','YYYY-MM-DD') and state in ('UNVERIFIED','USER_CONFIRMED','SYSTEM_VERIFIED') limit 100`;
  for(const e of evidence){if(e.valid_until<new Date().toISOString().slice(0,10)){await sql`update evidence set state='EXPIRED' where id=${e.id}`;await sql`update organizations set capability_version=capability_version+1 where id=${e.organization_id}`;await sql`update opportunity_analyses set stale=true where organization_id=${e.organization_id}`;}await notify(sql,e.organization_id,`expiry:${e.id}:${e.valid_until}`,'Evidence validity needs attention','Review expiring evidence. Renewal is not assumed.','/evidence');}
  const watches=await sql`select w.organization_id,w.notice_id,n.deadline,n.title from watchlist w join source_notices n on n.id=w.notice_id where w.state in ('WATCH','SAVED') and n.deadline is not null limit 100`;
  for(const w of watches){const d=parseDatetime(w.deadline);if(d&&d>Date.now()&&d-Date.now()<7*86400000)await notify(sql,w.organization_id,`deadline:${w.notice_id}:${w.deadline}`,'Tender deadline approaching',w.title,'/opportunities/'+w.notice_id);}
}
