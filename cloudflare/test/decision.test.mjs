import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {analyzeLots,evaluate} from '../src/decision.mjs';
import * as S from '../src/schemas.mjs';
const fixtures=JSON.parse(await readFile(new URL('./fixtures/decision.json',import.meta.url)));
function comparable(v){if(Array.isArray(v))return v.map(comparable);if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).filter(([k])=>!['algorithm_version','analyzed_at'].includes(k)).map(([k,x])=>[k,comparable(x)]));return v;}
for(const [i,f] of fixtures.entries())test(`Python decision parity ${i+1}`,()=>{assert.deepEqual(comparable(analyzeLots(f.notice,f.profile,f.evidence,new Date(f.at))),comparable(f.expected));});
test('manual declarations never prove a hard gate',()=>{const r={capability:'ISO 27001',category:'CERTIFICATION',hard_gate:true};for(const state of ['UNVERIFIED','USER_CONFIRMED'])assert.equal(evaluate(r,[{capability:'ISO 27001',state,document_id:null}],null).state,'UNKNOWN');});
test('profile validation rejects invalid costs and excessive lists',()=>{assert.equal(S.profile.safeParse({hourly_cost:-1}).success,false);assert.equal(S.profile.safeParse({operating_countries:Array(51).fill('DE')}).success,false);assert.equal(S.profile.safeParse({min_contract:2,max_contract:1}).success,false);});
test('evidence validation rejects reversed dates and invalid years',()=>{assert.equal(S.evidence.safeParse({capability:'TURNOVER',valid_from:'2027-01-01',valid_until:'2026-01-01'}).success,false);assert.equal(S.evidence.safeParse({capability:'TURNOVER',annual_values:{oops:42}}).success,false);});
