const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/design-preview/app.js'),'utf8');
// Execute the production initialization and click handler, without a WebGL renderer.
const languageCode=source.slice(source.indexOf("let language = 'zh';"),source.indexOf('const reduced ='));
const routeCode=source.slice(source.indexOf("let page = 'home';"),source.indexOf("document.querySelectorAll('[data-scroll]')"));
function environment(search,stored='zh',storageBlocked=false,hash='#report'){
  const events={},scrolls=[];
  const toggle={textContent:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;},addEventListener(_event,fn){this.click=fn;}};
  const link={href:'README.zh-CN.md',dataset:{hrefEn:'README.md'},getAttribute(){return this.href;},setAttribute(_name,value){this.href=value;}};
  const pages=Object.fromEntries(['home','workspace','cases','report'].map(id=>[id,{id,hidden:false}]));
  const sections=Object.fromEntries(['project-capabilities','project-workflow','project-data','project-stack','project-tests','project-start'].map(id=>[id,
    {id,scrollIntoView(options){assert.equal(pages.home.hidden,false);scrolls.push({kind:'section',id,...options});}}]));
  const nav=['home','workspace','cases'].map(id=>({hash:'#'+id,attrs:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];}}));
  const doc={documentElement:{lang:'zh-CN'},querySelectorAll(selector){return selector==='[data-href-en]'?[link]:
    selector==='.page'?Object.values(pages):selector==='.nav nav a'?nav:[];}};
  const location={pathname:'/TradeIntel/',search,hash};
  const storage={value:stored,getItem(){if(storageBlocked)throw Error('blocked');return this.value;},setItem(_k,v){if(storageBlocked)throw Error('blocked');this.value=v;}};
  const context=vm.createContext({document:doc,location,localStorage:storage,URLSearchParams,Event,
    $:id=>id==='language-toggle'?toggle:sections[id]||null,motionLabel(){},render(){},
    history:{replaceState(_state,_title,url){const u=new URL(url,'https://example.test');location.search=u.search;location.hash=u.hash;}},
    addEventListener(name,fn){events[name]=fn;},scrollTo(options){scrolls.push({kind:'top',...options});},dispatchEvent(){}});
  context.window=context;vm.runInContext(languageCode+'\n'+routeCode+'\napplyLanguage();',context);
  return {doc,location,toggle,storage,link,pages,nav,events,scrolls};
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
test('documentation links follow the selected language and restore Chinese targets',()=>{
  const e=environment('?lang=en');
  assert.equal(e.link.href,'README.md');
  e.toggle.click();assert.equal(e.link.href,'README.zh-CN.md');
});
test('a case reader entering a home section shows home and keeps its scroll target across language changes',()=>{
  const e=environment('?case=soybean-oil&lang=zh','zh',false,'#cases');
  assert.equal(e.pages.cases.hidden,false);assert.equal(e.pages.home.hidden,true);
  e.location.hash='#project-start';const before=e.scrolls.length;e.events.hashchange();
  assert.equal(e.pages.home.hidden,false);assert.equal(e.pages.cases.hidden,true);assert.equal(e.pages.report.hidden,true);
  assert.equal(e.nav[0].attrs['aria-current'],'page');assert.equal(e.nav[2].attrs['aria-current'],undefined);
  assert.deepEqual(e.scrolls.slice(before),[{kind:'section',id:'project-start',block:'start',behavior:'instant'}]);
  e.toggle.click();assert.equal(e.location.hash,'#project-start');assert.equal(e.doc.documentElement.lang,'en');
  assert.equal(new URLSearchParams(e.location.search).get('case'),'soybean-oil');
  assert.deepEqual(e.scrolls.at(-1),{kind:'section',id:'project-start',block:'start',behavior:'instant'});
  assert.match(e.doc.title,/International trade research assistant/);
});
test('home section deep links scroll on initialization while top-level and unknown routes start at the top',()=>{
  const section=environment('?lang=en','zh',false,'#project-data');
  assert.equal(section.pages.home.hidden,false);assert.ok(section.scrolls.every(item=>item.kind==='section'&&item.id==='project-data'));
  for(const hash of ['#home','#workspace','#cases','#report','#unknown']){
    const e=environment('','zh',false,hash);
    assert.ok(e.scrolls.every(item=>item.kind==='top'&&item.top===0));
    const active=hash==='#unknown'?'home':hash.slice(1);
    for(const [id,page]of Object.entries(e.pages))assert.equal(page.hidden,id!==active);
  }
});
