// Port of app/decision.py. Keep parity tests before changing eligibility semantics.
export const ALGORITHM_VERSION = 'decision-1.0-cf1';
export const canonical = value => {
  const text = value.toUpperCase().trim(), iso = text.match(/ISO\s*(?:\/\s*IEC\s*)?(\d{4,5}(?:-\d+)?)/);
  return iso ? `ISO ${iso[1]}` : ({REVENUE:'TURNOVER','ANNUAL TURNOVER':'TURNOVER','PROFESSIONAL INDEMNITY':'INSURANCE'}[text] || text);
};
// Python's round uses ties-to-even.
export function round(x) {const floor=Math.floor(x), fraction=x-floor;return fraction===0.5 ? (floor%2===0 ? floor : floor+1) : Math.round(x);}
const day = value => value?.civilDay || new Date(value).toISOString().slice(0,10);
export function parseDatetime(value) {if(typeof value!=='string'||!/[T ]/.test(value)||!/(Z|[+-]\d\d:\d\d)$/.test(value)||!Number.isFinite(Date.parse(value)))return null;const parsed=new Date(value);parsed.civilDay=value.slice(0,10);return parsed;}
export function evaluate(req,evidence,deadline,today=day(new Date())) {
  const target=deadline?day(deadline):today;
  const base={requirement:req,state:'UNKNOWN',evidence_ids:[],reason:'No confirmed documentary evidence proves this requirement.',next_action:'Add evidence for '+req.capability};
  if(req.not_applicable)return {...base,state:'NOT_APPLICABLE',reason:'Source explicitly states this is not required.',next_action:null};
  if(req.ambiguous||req.capability==='UNKNOWN')return {...base,reason:'Ambiguous or unsupported clause. Review the original source and obtain clarification.',next_action:'Clarify: '+req.text};
  const candidates=evidence.filter(e=>canonical(e.capability)===canonical(req.capability)&&['USER_CONFIRMED','SYSTEM_VERIFIED','EXPIRED'].includes(e.state)&&e.document_id&&e.document_available!==false),failures=[];
  for(const e of candidates){
    if(e.valid_from&&e.valid_from>today)continue;
    if(e.state==='EXPIRED'||(e.valid_until&&e.valid_until<target)){failures.push([e.id,'Evidence expires before the required date; renewal is not assumed.']);continue;}
    const data=e.data||{};
    if(req.edition&&!(data.original_capability||'').includes(req.edition))continue;
    if(req.category==='CERTIFICATION'&&!e.valid_until)continue;
    if(req.currency&&req.currency!==data.currency)continue;
    if(req.threshold!=null){
      let values=[data.value];
      if(req.years){const annual=data.annual_values||{},years=Array.from({length:req.years},(_,i)=>String(Number(target.slice(0,4))-i-1));if(!years.every(y=>y in annual))continue;values=years.map(y=>annual[y]);if(req.period_mode==='average')values=[values.reduce((a,b)=>a+b,0)/values.length];else if(req.period_mode==='aggregate')values=[values.reduce((a,b)=>a+b,0)];}
      if(values.some(v=>v==null))continue;
      const cmp={gte:v=>v>=req.threshold,gt:v=>v>req.threshold,lte:v=>v<=req.threshold}[req.comparator];if(!cmp)continue;
      if(!values.every(cmp)){failures.push([e.id,'Confirmed documentary value does not meet the source threshold.']);continue;}
    }
    return {...base,state:'PASS',reason:'Confirmed document satisfies the normalized predicate and validity window.',evidence_ids:[e.id],next_action:null};
  }
  return failures.length?{...base,state:'FAIL',reason:failures[0][1],evidence_ids:failures.map(x=>x[0])}:base;
}
export function businessDays(start,end){const n=Math.max(0,Math.floor((Date.parse(end)-Date.parse(start))/86400000)),weeks=Math.floor(n/7),rem=n%7;let result=weeks*5;for(let i=0;i<rem;i++){const d=new Date(Date.parse(start)+(weeks*7+i)*86400000).getUTCDay();if(d!==0&&d!==6)result++;}return result;}
const WEIGHTS={technical_fit:.25,evidence_coverage:.3,financial_fit:.15,geography:.1,deadline:.15,capacity:.05};
const ATTR={size_fit:.4,margin:.25,bid_cost_ratio:.2,strategic_fit:.15};
export function analyze(notice,profile,evidence,at=new Date(),lot_id=null){
  const requirements=(notice.requirements||[]).filter(r=>r.lot_id==null||r.lot_id===lot_id),deadline=parseDatetime(notice.deadline),results=requirements.map(r=>evaluate(r,evidence,deadline,day(at)));
  const relevant=results.filter(r=>r.state!=='NOT_APPLICABLE'),weight=r=>r.requirement.hard_gate?3:1,total=relevant.reduce((s,r)=>s+weight(r),0),verified=relevant.filter(r=>r.state==='PASS').reduce((s,r)=>s+weight(r),0),coverage=total?round(verified/total*100):0;
  const failures=results.filter(r=>r.state==='FAIL'&&r.requirement.hard_gate),unknown=results.filter(r=>r.state==='UNKNOWN'&&r.requirement.hard_gate),complete=notice.requirements_complete||false,eligibility=failures.length?'FAIL':unknown.length||!complete?'UNKNOWN':'PASS',friction=[];
  if(notice.country&&!(profile.operating_countries||[]).includes(notice.country))friction.push({reason:'Buyer country is outside declared operating countries. Confirm the place of performance.',source:'buyer_country',kind:'GEOGRAPHY'});
  if(notice.languages?.length&&!notice.languages.some(l=>(profile.languages||[]).includes(l)))friction.push({reason:'The source language is outside declared working languages; confirm submission language and translation needs.',source:'languages',kind:'LANGUAGE'});
  for(const [key,reason] of [['onsite','Onsite delivery is specified.'],['site_visit','A mandatory site visit is specified.']])if(notice[key])friction.push({reason,source:key,kind:'LOGISTICS'});
  const missing=results.filter(r=>['UNKNOWN','FAIL'].includes(r.state)).length,base=12+requirements.length*2+missing*3+(notice.document_count||0)*2+friction.length*5;
  let effort=[round(base*.8),round(base*1.3)];if(profile.effort_multiplier)effort=effort.map(v=>round(v*profile.effort_multiplier));
  const available=deadline?businessDays(day(at),day(deadline))*(profile.bid_hours_per_day??2)*(profile.availability_factor??.8):null;
  const deadlineScore=deadline&&deadline<=at?0:available==null?50:Math.min(100,round(available/Math.max(effort[1],1)*100)),cpvs=notice.cpv_codes||[],interests=profile.cpv_interests||[];
  const overlap=cpvs.filter(c=>interests.some(p=>String(c).slice(0,2)===String(p).slice(0,2))).length,financial=results.filter(r=>r.requirement.category==='FINANCIAL');
  const components={technical_fit:cpvs.length&&interests.length?round(overlap/cpvs.length*100):0,evidence_coverage:coverage,financial_fit:financial.length?round(financial.filter(r=>r.state==='PASS').length/financial.length*100):50,geography:Math.max(0,100-friction.length*25),deadline:deadlineScore,capacity:deadlineScore};
  const feasibility=round(Object.entries(WEIGHTS).reduce((s,[k,w])=>s+components[k]*w,0)),hourly=profile.hourly_cost??60,external=profile.external_bid_cost??0,cost=effort.map(h=>round(h*hourly+external)),value=notice.value,comparable=value!=null&&notice.currency===(profile.currency??'EUR');
  const attr={size_fit:comparable&&value>=(profile.min_contract??0)&&value<=(profile.max_contract??1000000)?100:comparable?20:50,margin:profile.expected_margin!=null?Math.min(100,profile.expected_margin*3):50,bid_cost_ratio:comparable&&value>0?Math.max(0,100-cost[1]/value*1000):50,strategic_fit:profile.strategic_fit??50};
  const attractiveness=round(Object.entries(ATTR).reduce((s,[k,w])=>s+attr[k]*w,0)),confidence=round((notice.completeness_score||0)*.4+coverage*.4+(requirements.length?requirements.reduce((s,r)=>s+r.confidence,0)/requirements.length*100:0)*.2);
  let decision='REVIEW',explanation='Resolve missing or ambiguous evidence before committing bid resources.';
  if(failures.length||notice.status==='CANCELLED'||(deadline&&deadline<=at)){decision='NO_BID';explanation='A mandatory failure, cancellation, or elapsed deadline prevents a supported bid recommendation.';}
  else if(eligibility==='PASS'&&confidence>=75&&deadline&&available>=effort[1]){if(feasibility>=85&&attractiveness>=75){decision='STRONG_BID';explanation='Verified eligibility, strong fit, and sufficient estimated capacity support pursuing this opportunity.';}else if(feasibility>=65&&attractiveness>=50){decision='BID';explanation='Verified eligibility and practical fit support a bid, subject to your final review.';}}
  else if(eligibility==='PASS'&&confidence>=65&&available!=null&&effort[0]<=available&&available<effort[1]){decision='CONDITIONAL_BID';explanation='Eligibility is supported; allocate additional bid capacity before proceeding.';}
  if(available!=null&&available<effort[0]&&decision!=='NO_BID'){decision='REVIEW';explanation='Estimated minimum effort exceeds available bid-team hours.';}
  return {decision,explanation,eligibility,feasibility,attractiveness,confidence,coverage,coverage_numerator:verified,coverage_denominator:total,components:Object.fromEntries(Object.entries(components).map(([k,v])=>[k,{score:v,weight:WEIGHTS[k],basis:k==='evidence_coverage'?'Documentary coverage':'Declared profile and source facts; heuristic'}])),attractiveness_components:Object.fromEntries(Object.entries(attr).map(([k,v])=>[k,{score:round(v),weight:ATTR[k]}])),requirements:results,friction,effort_hours:effort,available_hours:available,cost_range:cost,cost_currency:profile.currency??'EUR',cost_inputs:{hourly_cost:hourly,external_known_cost:external},unmodeled_costs:['Translation, certification, travel and partner costs unless included in your external-cost assumption.'],missing_evidence:results.filter(r=>r.next_action).map(r=>r.next_action),uncertainty:[...complete?[]:['Full tender documentation has not been confirmed complete.'],...deadline?[]:['Authoritative deadline or timezone missing.'],'Competition and incumbency are unavailable unless supported by historical awards.','Effort and attractiveness are estimates, not a win probability.'],sensitivity:['BID','STRONG_BID'].includes(decision)&&available!=null&&available>=effort[1]*1.25?'ROBUST':'FRAGILE',algorithm_version:ALGORITHM_VERSION,model_version:'deterministic',lot_id,analyzed_at:at.toISOString()};
}
export function analyzeLots(notice,profile,evidence,at=new Date()) {const summary=analyze(notice,profile,evidence,at);if(notice.lots?.length){summary.lots=notice.lots.map(l=>analyze({...notice,...l},profile,evidence,at,l.id));summary.decision='REVIEW';summary.explanation='Lot-level assessments govern eligibility. Select the lots you intend to bid for; tender-wide aggregation is not assumed.';}return summary;}
