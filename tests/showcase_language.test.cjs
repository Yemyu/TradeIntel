const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/design-preview/app.js'),'utf8');
// Execute the production initialization and click handler, without a WebGL renderer.
const languageCode=source.slice(source.indexOf("let language = 'zh';"),source.indexOf('const reduced ='));
function environment(search,stored='zh',storageBlocked=false){
  const toggle={textContent:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;},addEventListener(_event,fn){this.click=fn;}};
  const doc={documentElement:{lang:'zh-CN'},querySelectorAll(){return [];}};
  const location={pathname:'/TradeIntel/',search,hash:'#report'};
  const storage={value:stored,getItem(){if(storageBlocked)throw Error('blocked');return this.value;},setItem(_k,v){if(storageBlocked)throw Error('blocked');this.value=v;}};
  const context=vm.createContext({document:doc,location,localStorage:storage,URLSearchParams,Event,
    $:id=>id==='language-toggle'?toggle:null,motionLabel(){},route(){},render(){},
    history:{replaceState(_state,_title,url){const u=new URL(url,'https://example.test');location.search=u.search;location.hash=u.hash;}},
    dispatchEvent(){}});
  context.window=context;vm.runInContext(languageCode+'\napplyLanguage();',context);
  return {doc,location,toggle,storage};
}
test('URL language overrides the saved preference',()=>{
  assert.equal(environment('?lang=en','zh').doc.documentElement.lang,'en');
  assert.equal(environment('?lang=zh','en').doc.documentElement.lang,'zh-CN');
});
test('invalid or absent URL language retains preference; blocked storage still works',()=>{
  assert.equal(environment('?lang=xx','en').doc.documentElement.lang,'en');
  assert.equal(environment('','en').doc.documentElement.lang,'en');
  assert.equal(environment('?lang=en','zh',true).doc.documentElement.lang,'en');
  assert.equal(environment('','en',true).doc.documentElement.lang,'zh-CN');
});
test('switching language preserves the selected case, report and hash',()=>{
  const e=environment('?case=soybean-oil&report=r1&lang=en');e.toggle.click();
  const q=new URLSearchParams(e.location.search);
  assert.equal(q.get('case'),'soybean-oil');assert.equal(q.get('report'),'r1');
  assert.equal(q.get('lang'),'zh');assert.equal(e.location.hash,'#report');
  assert.equal(e.doc.documentElement.lang,'zh-CN');assert.equal(e.storage.value,'zh');
  const fresh=environment(e.location.search,'en');assert.equal(fresh.doc.documentElement.lang,'zh-CN');
});
