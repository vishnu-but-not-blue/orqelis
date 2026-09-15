export const id=()=>crypto.randomUUID().replaceAll('-','');
export const token=()=>id()+id();
export const now=()=>new Date().toISOString();
export const sha=async v=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(v))),b=>b.toString(16).padStart(2,'0')).join('');
export const stable=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);
export function fail(status,message){throw Object.assign(new Error(message),{status});}
export function equal(a,b){if(typeof a!=='string'||typeof b!=='string')return false;let diff=a.length^b.length;for(let i=0;i<Math.max(a.length,b.length);i++)diff|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return diff===0;}
export const json=(data,status=200,headers={})=>Response.json(data,{status,headers:{'Cache-Control':'no-store',...headers}});
export async function bounded(response,max=1024*1024){const reader=response.body?.getReader();if(!reader)return '';const chunks=[];let size=0;while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>max){await reader.cancel();fail(413,'Response or request exceeds the size limit.');}chunks.push(value);}const all=new Uint8Array(size);let offset=0;for(const part of chunks){all.set(part,offset);offset+=part.length;}return new TextDecoder().decode(all);}
export async function input(request,schema){if(!(request.headers.get('content-type')||'').includes('application/json'))fail(415,'Send application/json.');let body;try{body=JSON.parse(await bounded(request,65536));}catch(e){if(e.status)throw e;fail(422,'Invalid JSON body.');}const result=schema.safeParse(body);if(!result.success)fail(422,'Invalid input: '+result.error.issues.map(x=>x.path.join('.')+': '+x.message).join('; ').slice(0,1000));return result.data;}
export const attachment=(data,name)=>json(data,200,{'Content-Disposition':`attachment; filename="${name}"`});
