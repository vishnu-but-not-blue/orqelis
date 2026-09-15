const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/i18n.js','utf8');
async function runtime(language,fail=false){
  const document={documentElement:{},querySelectorAll:()=>[],querySelector:()=>null,addEventListener:()=>{}};
  const context=vm.createContext({document,localStorage:{getItem:()=>language},fetch:async path=>{
    if(fail&&!path.endsWith('/en.json'))throw Error('offline');
    return {ok:true,json:async()=>JSON.parse(fs.readFileSync('app'+path,'utf8'))};
  }});
  vm.runInContext(source,context);
  await vm.runInContext('I18N.ready',context);
  return {context,document,evaluate:code=>vm.runInContext(code,context)};
}
for(const language of ['en','de','fr','es','it','nl','pl','pt']){
  test(language+': interpolation, escaping, errors and evidence boundaries',async()=>{
    const app=await runtime(language);
    assert.equal(app.document.documentElement.lang,language);
    const catalog=JSON.parse(fs.readFileSync('app/static/locales/'+language+'.json'));
    assert.equal(app.evaluate('t("Work email")'),catalog['Work email']);
    assert.equal(app.evaluate('t("A clearer view, {0}.","Original {1} <b>company</b>")'),catalog['A clearer view, {0}.'].replace('{0}','Original {1} <b>company</b>'));
    const result=app.evaluate('htmlMessage("Evidence {0}","&lt;script&gt;{1}")');
    assert.ok(result.includes('&lt;script&gt;{1}'));
    assert.ok(!result.includes('&amp;lt;'));
    assert.ok(!app.evaluate('htmlMessage("<img src=x onerror=alert(1)>")').includes('<img'));
    assert.equal(app.evaluate('I18N.error({error:{message:"The sign-in code is invalid or expired."}},401)'),catalog['The sign-in code is invalid or expired.']);
    assert.equal(app.evaluate('I18N.error({detail:"untrusted provider output"},422)'),catalog['Check the form values and try again.']);
    assert.equal(app.evaluate('I18N.generated("Unrecognized original source text {0}")'),'Unrecognized original source text {0}');
  });
}
test('unknown language and blocked catalog safely default to English',async()=>{
  assert.equal((await runtime('../../secret')).document.documentElement.lang,'en');
  assert.equal((await runtime('de',true)).document.documentElement.lang,'en');
});
