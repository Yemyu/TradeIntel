// Real case controller + renderer, with offline DOM/fetch substitutes.
const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const web=path.join(__dirname,'../web/design-preview');
const scripts=['report-view.js','cases.js'].map(f=>fs.readFileSync(path.join(web,f),'utf8')).join('\n');
const index=JSON.parse(fs.readFileSync(path.join(web,'cases/index.json'),'utf8'));
const cases=Object.fromEntries(index.cases.map(c=>[c.id,JSON.parse(fs.readFileSync(path.join(web,c.asset),'utf8'))]));
function env(search='?case=soybean-trade&report=r2',hash='#report',local=false,missing=false,catalogFailure=false){
  const ids=new Map(),created=[],events={},calls=[];
  function node(tag='div'){
    const n={tag,children:[],attrs:{},hidden:false,style:{},ownerDocument:doc,
      append(...children){for(const c of children)c.parent=this;this.children.push(...children);},
      prepend(...children){this.children.unshift(...children);},
      replaceChildren(...children){this.children=[];this.text='';this.append(...children);},
      after(child){doc.main.append(child);},before(child){doc.report.append(child);},
      setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return k==='href'?this.href:this.attrs[k];},addEventListener(k,f){this.listeners||={};this.listeners[k]=f;},
      querySelector(selector){return selector==='.report-layout'?layout:null;},querySelectorAll(){return [];},
      get textContent(){return (this.text||'')+this.children.map(x=>x.textContent).join('');},
      set textContent(x){this.children=[];this.text=String(x);},
      set id(x){this.identifier=x;ids.set(x,this);},get id(){return this.identifier;}};
    created.push(n);return n;
  }
  const doc={documentElement:{lang:'zh-CN',dataset:{runtime:local?'local':'showcase'}},
    getElementById(id){return ids.get(id);},createElement:tag=>node(tag),
    querySelector(selector){return selector==='main'?doc.main:null;},
    querySelectorAll(selector){return selector==='.nav a[href="#workspace"]'?[localLink]:[];}};
  doc.main=node('main');doc.report=node('section');doc.report.id='report';
  for(const id of ['workspace','home','return-to-conversation']){const n=node();n.id=id;doc.main.append(n);}
  const layout=node();doc.report.append(layout);const reportSummary=node('header');reportSummary.id='report-summary';layout.append(reportSummary);
  const localLink=node('a');localLink.href='#workspace';
  const location={pathname:local?'/preview/':'/TradeIntel/preview/',search,hash};
  const context=vm.createContext({document:doc,location,URLSearchParams,Event,AbortController,setTimeout,clearTimeout,
    history:{pushState(_state,_title,url){const parsed=new URL(url,'http://example.test');location.pathname=parsed.pathname;location.search=parsed.search;location.hash=parsed.hash;}},
    addEventListener(name,f){(events[name]||=[]).push(f);},
    dispatchEvent(event){for(const fn of events[event.type]||[])fn(event);},
    localStorage:{getItem(){throw Error('Case reader must not read live storage');},setItem(){throw Error('Case reader must not write storage');}},
    fetch:async url=>{calls.push(url);if(catalogFailure&&url==='cases/index.json')throw Error('Network unavailable');const name=url.match(/^cases\/([a-z-]+)\.json$/)?.[1];
      return {ok:url==='cases/index.json'||(!missing&&!!cases[name]),json:async()=>structuredClone(url==='cases/index.json'?index:cases[name])};}});
  context.window=context;vm.runInContext(scripts,context);
  return {context,doc,ids,calls,layout,events,localLink,created,recoverCatalog(){catalogFailure=false;},async flush(){await new Promise(resolve=>setImmediate(resolve));}};
}
test('home has four case links before the catalog request completes',async()=>{
  const e=env('','#home');
  const gallery=e.ids.get('case-gallery');
  assert.equal(gallery.children[1].children.length,4);
  assert.match(gallery.textContent,/正在读取案例目录/);
  await e.flush();assert.equal(gallery.children[2].hidden,true);
});
test('catalog network failure keeps home navigable with a translated retry and can recover',async()=>{
  const e=env('','#home',false,false,true);await e.flush();
  const gallery=e.ids.get('case-gallery');
  assert.equal(gallery.children[1].children.length,4);
  assert.match(gallery.textContent,/案例目录未能加载/);
  assert.equal(e.context.tradeintelCaseActive,undefined);
  e.doc.documentElement.lang='en';e.context.dispatchEvent(new Event('tradeintel:language'));await e.flush();
  assert.match(gallery.textContent,/catalog could not be loaded/);
  e.recoverCatalog();gallery.children[2].children[1].listeners.click();await e.flush();
  assert.equal(gallery.children[2].hidden,true);assert.equal(gallery.children[1].children.length,4);
  assert.deepEqual(e.calls,['cases/index.json','cases/index.json']);
});
test('static subpath loads only whitelisted case resources and shows the selected export',async()=>{
  const e=env();await e.flush();assert.deepEqual(e.calls,['cases/index.json','cases/soybean-trade.json']);
  const result=e.ids.get('case-result');assert.equal(result.hidden,false);assert.match(result.textContent,/889,379,312/);
  assert.ok(!e.created.some(n=>['input','textarea','form','select'].includes(n.tag)));
});
test('language and refresh retain the case alias without local storage or API requests',async()=>{
  const e=env();await e.flush();e.doc.documentElement.lang='en';
  e.context.dispatchEvent(new Event('tradeintel:language'));await e.flush();
  assert.match(e.ids.get('case-result').textContent,/U.S. exports/);assert.match(e.ids.get('case-result').textContent,/889,379,312/);
  assert.equal(e.calls.length,2);const fresh=env();await fresh.flush();assert.match(fresh.ids.get('case-result').textContent,/889,379,312/);
});
test('missing-month case has a real controlled explanation and no invented report/chart',async()=>{
  const e=env('?case=missing-month','#cases');await e.flush();
  assert.match(e.ids.get('cases').textContent,/缺少 2026-08/);assert.match(e.ids.get('cases').textContent,/模型尝试改查7月，被程序拦截/);
  assert.equal(e.ids.get('case-result').hidden,true);assert.equal(e.ids.get('case-result').textContent,'');
  assert.ok(!e.created.some(n=>n.tag==='a'&&n.href?.includes('&report=')));
});
test('policy archive uses its fixed report and never fabricates a model dialogue',async()=>{
  const e=env('?case=policy-materials&report=r1');await e.flush();assert.equal(e.layout.hidden,false);
  assert.equal(e.ids.get('case-result').hidden,true);assert.match(e.ids.get('cases').textContent,/没有对应的模型对话记录/);
  assert.equal(e.ids.get('case-edited-note').hidden,false);
  assert.match(e.ids.get('case-edited-note').textContent,/存档资料编辑稿 · 2026-10-01/);
  assert.match(e.ids.get('case-edited-note').textContent,/不是当前 Agent/);
});
test('policy example explains its background and contents before linking to the report in both languages',async()=>{
  const e=env('?case=policy-materials','#cases');await e.flush();
  const page=e.ids.get('cases');assert.match(page.textContent,/案例与报告/);
  for(const phrase of ['公告涉及什么','进口数据怎么看','报告里有什么','2026年2月至7月'])assert.ok(page.textContent.includes(phrase));
  assert.ok(!e.created.some(n=>n.className==='chat-message user-message'));
  assert.ok(e.created.some(n=>n.href==='?case=policy-materials&report=r1&lang=zh#report'));
  e.doc.documentElement.lang='en';e.context.dispatchEvent(new Event('tradeintel:language'));await e.flush();
  assert.match(page.textContent,/What the notice covers/);assert.match(page.textContent,/Inside the report/);
});
test('invalid identity, missing JSON and wrong alias show unavailable instead of another report',async()=>{
  for(const [search,missing] of [['?case=unknown',false],['?case=soybean-trade&report=r99',false],['?case=soybean-trade&report=r1',true]]){
    const e=env(search,'#report',false,missing);await e.flush();assert.equal(e.ids.get('case-result').textContent,'案例暂不可用');assert.equal(e.layout.hidden,true);
    assert.equal(e.doc.title,'案例暂不可用 · TradeIntel');
    assert.equal(e.ids.get('return-to-conversation').href,'/TradeIntel/preview/?lang=zh#cases');
  }
});
test('returning from a local case emits a GET-restoration signal and preserves the session store',async()=>{
  const e=env('?case=soybean-trade','#cases',true);await e.flush();let restores=0;
  e.context.addEventListener('tradeintel:return-local',()=>restores++);
  e.localLink.listeners.click({preventDefault(){}});await e.flush();
  assert.equal(restores,1);assert.equal(e.context.location.search,'');assert.equal(e.context.location.hash,'#workspace');
  assert.equal(e.context.tradeintelCaseActive,false);assert.equal(e.calls.length,2);
});
test('local case links use in-page navigation so conversation memory and unsent drafts survive',async()=>{
  const e=env('','#home',true);await e.flush();e.context.unsentDraft='not sent';let prevented=0;
  const card=e.created.find(n=>n.tag==='a'&&n.href==='?case=soybean-oil&lang=zh#cases');
  assert.ok(card.listeners?.click);card.listeners.click({preventDefault(){prevented++;}});await e.flush();
  assert.equal(prevented,1);assert.equal(e.context.unsentDraft,'not sent');
  assert.equal(e.context.location.search,'?case=soybean-oil&lang=zh');assert.equal(e.context.location.hash,'#cases');
  assert.match(e.ids.get('cases').textContent,/27,503,913/);
  assert.deepEqual(e.calls,['cases/index.json','cases/soybean-oil.json']);
  card.listeners.click({metaKey:true,preventDefault(){throw Error('Modified click must retain normal browser behaviour');}});
  const report=e.created.find(n=>n.tag==='a'&&n.href==='?case=soybean-oil&report=r1&lang=zh#report');
  report.listeners.click({preventDefault(){}});await e.flush();assert.equal(e.context.location.hash,'#report');
  e.ids.get('return-to-conversation').listeners.click({preventDefault(){}});await e.flush();
  assert.equal(e.context.location.hash,'#cases');assert.equal(e.context.unsentDraft,'not sent');
});
