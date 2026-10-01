/* Saved case reader. No model endpoints, config, free-form submission or storage. */
(() => {
  const ids=['soybean-trade','soybean-oil','policy-materials','missing-month'];
  const $=id=>document.getElementById(id);
  const local=document.documentElement.dataset.runtime==='local'&&['/preview/','/preview/index.html'].includes(location.pathname);
  const english=()=>document.documentElement.lang==='en';
  const tr=(zh,en)=>english()?en:zh;
  const text=value=>english()?value.en:value.zh;
  const make=(tag,value,className)=>{const node=document.createElement(tag);if(value!==undefined)node.textContent=value;if(className)node.className=className;return node;};
  const page=make('section',undefined,'page');page.id='cases';page.hidden=true;
  const shell=make('div',undefined,'case-shell wrap');page.append(shell);
  const heading=make('header',undefined,'case-heading');
  const cards=make('nav',undefined,'case-picker');cards.setAttribute('aria-label','案例');
  const record=make('div',undefined,'case-record');shell.append(heading,cards,record);
  if($('workspace'))$('workspace').after(page);else document.querySelector('main').append(page);
  const home=make('section',undefined,'section wrap case-gallery');home.id='case-gallery';
  const homeHead=make('div',undefined,'section-heading');const homeCards=make('div',undefined,'case-grid');
  home.append(homeHead,homeCards);$('home').append(home);
  const install=make('section',undefined,'section wrap local-install');install.id='local-install';$('home').append(install);
  const caseReport=make('article',undefined,'live-result wrap');caseReport.id='case-result';caseReport.hidden=true;
  $('report').querySelector('.report-layout').before(caseReport);
  const editedNote=make('p',undefined,'case-meta');editedNote.id='case-edited-note';editedNote.hidden=true;
  $('report-summary')?.prepend(editedNote);
  function bindCaseLink(node,url){
    if(!local)return;
    node.addEventListener('click',event=>{
      const target=typeof url==='function'?url():url;
      if(typeof target!=='string'||!target.startsWith('?case='))return;
      if(event.defaultPrevented||event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      event.preventDefault();history.pushState(null,'',target);
      window.dispatchEvent(new Event('hashchange'));
    });
  }
  bindCaseLink($('return-to-conversation'),()=>$('return-to-conversation').getAttribute('href'));
  document.querySelectorAll(local?'#home a[href="#report"]':'#home a[href="#report"], .nav a[href="#report"]').forEach(a=>{
    a.href='?case=policy-materials&report=r1#report';
    bindCaseLink(a,'?case=policy-materials&report=r1#report');
  });
  let manifest=null,selected=null,version=0;const cache=new Map();let opened=[];
  const href=(id,alias,hash='cases')=>`?case=${id}${alias?'&report='+alias:''}#${hash}`;
  const link=(label,url,className)=>{const node=make('a',label,className);node.href=url;bindCaseLink(node,url);return node;};
  const unavailable=()=>{
    editedNote.hidden=true;
    window.tradeintelCaseActive=true;window.tradeintelLiveReportTitle=tr('案例暂不可用','Case unavailable');
    document.title=`${window.tradeintelLiveReportTitle} · TradeIntel`;
    $('return-to-conversation').href=location.pathname+'#cases';
    $('return-to-conversation').textContent=tr('← 返回案例列表','← Back to cases');
    record.replaceChildren(make('h2',tr('案例暂不可用','Case unavailable')),make('p',tr('没有找到这份存档。请从四个案例中选择；不会改查其他商品。','This archive could not be found. Choose one of the four cases; no other product is substituted.')));
    caseReport.replaceChildren(make('h1',tr('案例暂不可用','Case unavailable')));caseReport.hidden=location.hash!=='#report';
    $('report').querySelector('.report-layout').hidden=true;
    window.dispatchEvent(new Event('tradeintel:case-report'));
  };
  async function get(id){
    if(!ids.includes(id))throw Error('Invalid case');
    if(!cache.has(id))cache.set(id,fetch(`cases/${id}.json`).then(r=>{if(!r.ok)throw Error('Missing case');return r.json();}).then(c=>{
      if(c.schema!=='tradeintel-public-case-v1'||c.id!==id||!Array.isArray(c.reports)||!Array.isArray(c.turns))throw Error('Invalid case file');return c;
    }));
    return cache.get(id);
  }
  function labels(){
    heading.replaceChildren(make('p',tr('案例记录','CASE RECORDS'),'eyebrow'),make('h1',tr('看看它怎么回答','See how it responds')),
      make('p',tr('这里是已保存的运行记录和报告，不是在线提问。','Saved runs and reports, not a live assistant.')));
    homeHead.replaceChildren(make('h2',tr('四个案例','Four cases')),make('p',tr('两次真实查询、一份政策资料报告，以及一次缺数拦截。','Real queries, an edited policy report, and a blocked missing-month request.')));
    install.replaceChildren(make('h2',tr('在自己的电脑上使用','Run it on your computer')),
      make('p',tr('公开网站不用 API，只能阅读案例。要自己提问，请启动本地服务，再填自己的模型 API。数据查询本身不需要模型或 MySQL。','The public site needs no API and only reads saved cases. To ask your own questions, run the local service and configure your own model API. Data-only queries need neither a model nor MySQL.')),
      make('p',tr('数据包尚未公开；普通克隆还不能直接查询。源码及安装说明已提供，数据下载地址须在正式发布时补齐。当前安装验证限 macOS；Windows 尚未验证。','The data bundle is not public yet; cloning alone does not enable queries. Source and setup instructions are available. A data link is still required before public release. Installation was verified on macOS; Windows is unverified.')),
      link(tr('源码 ↗','Source ↗'),'https://github.com/Yemyu/TradeIntel','text-link'),
      link(tr('安装说明 ↗','Setup guide ↗'),'https://github.com/Yemyu/TradeIntel/blob/main/docs/LOCAL_RUN.zh-CN.md','text-link'));
    cards.replaceChildren();homeCards.replaceChildren();
    for(const entry of manifest?.cases||[]){
      const small=link(text(entry.title),href(entry.id), 'case-tab');if(entry.id===selected)small.setAttribute('aria-current','page');cards.append(small);
      const card=link('',href(entry.id),'case-tile');card.append(make('small',tr(entry.kind==='real_agent_run'?'真实运行':entry.kind==='guarded_run'?'程序拦截':'资料编辑稿',entry.kind==='real_agent_run'?'REAL RUN':entry.kind==='guarded_run'?'PROGRAM GUARD':'EDITED REPORT')),
        make('h3',text(entry.title)),make('p',text(entry.description)),make('span',tr('查看记录 →','Open record →')));homeCards.append(card);
    }
    if(!local){
      if($('workspace'))$('workspace').hidden=true;
      document.querySelectorAll('.nav a[href="#workspace"],#home a[href="#workspace"],.nav a[href="#cases"],#home a[href="#cases"]').forEach(a=>{a.href='#cases';a.textContent=tr('查看案例','View cases');});
    }
  }
  function showRecord(caseData,entry){
    record.replaceChildren(make('p',tr(`存档 ${entry.recorded_on} · 数据截至 ${entry.data_cutoff}`,`Recorded ${entry.recorded_on} · Data through ${entry.data_cutoff}`),'case-meta'),
      make('h2',text(entry.title)),make('p',text(entry.limitations),'case-limit'));
    if(entry.model)record.append(make('p',`${entry.model.request_name} · ${entry.model.reasoning}`,'case-meta'));
    if(english()&&caseData.turns.length)record.append(make('p','English is a reading translation of the saved Chinese exchange, not a new model run.','case-meta'));
    for(const turn of caseData.turns){
      const message=make('section',undefined,`chat-message ${turn.role==='user'?'user-message':'assistant-message'}`);
      message.append(make('small',turn.role==='user'?tr('你','You'):tr('研究助手','Research assistant')),make('p',text(turn.text)));
      if(turn.reports.length){const list=make('div',undefined,'report-cards');
        for(const alias of turn.reports){const report=caseData.reports.find(r=>r.report_id===alias);if(!report)continue;
          const s=report.scope;const title=tr(s.flow==='export'?'出口':'进口',s.flow==='export'?'Exports':'Imports')+' · '+tr(s.partner==='CHINA'?'中国':s.flow==='export'?'全部目的地':'全部来源',s.partner==='CHINA'?'China':s.flow==='export'?'All destinations':'All origins');
          const card=link('',href(entry.id,alias,'report'),'report-card');card.append(make('strong',title+(alias===turn.primary_report?tr('（主报告）',' (main)'):tr('（附加）',' (additional)'))),make('span',`${english()?s.official_product_en:s.product_label} · ${s.start_month}—${s.end_month}`));list.append(card);
        }message.append(list);
      }
      if(turn.steps.length){const steps=make('details');steps.append(make('summary',tr('已执行步骤','Recorded steps')));
        const list=make('ol');for(const step of turn.steps)list.append(make('li',text(step.label)+(step.status==='unavailable'?tr('：没有可用数据',' — unavailable'):'')));steps.append(list);message.append(steps);}
      record.append(message);
    }
    if(entry.id==='policy-materials')record.append(make('p',tr('这份资料报告没有对话记录。可切换五个商品，查看图表和公告背景。','This edited report has no dialogue. View charts and notice context for five product codes.')),
      link(tr('阅读政策与进口报告 →','Read the policy and import report →'),href(entry.id,'r1','report'),'button primary'));
    if(caseData.guard)record.append(make('p',tr('本次没有生成报告或图表。需要另行明确是否改查7月；存档不会替你重新查询。','No report or chart was generated. A new request would need explicit permission to use July; this archive does not run a replacement query.')));
    record.append(link(tr('本地运行说明 ↗','Local setup ↗'),'#home','text-link'));
  }
  async function route(){
    page.hidden=location.hash!=='#cases';
    editedNote.hidden=true;
    const current=++version;const params=new URLSearchParams(location.search);const id=params.get('case');
    if(!id){selected=null;window.tradeintelCaseActive=false;labels();
      if(location.hash==='#workspace'&&!local){location.hash='cases';return;}
      if(location.hash==='#cases')record.replaceChildren(make('p',tr('选择一个案例，查看原来的问答和报告。','Choose a case to read its saved exchange and report.')));
      return;
    }
    selected=id;window.tradeintelCaseActive=true;labels();
    record.replaceChildren(make('p',tr('正在读取存档…','Loading the archive…')));
    const layout=$('report').querySelector('.report-layout');layout.hidden=true;caseReport.hidden=true;
    window.dispatchEvent(new Event('tradeintel:case-report'));
    try{
      if(!manifest||params.getAll('case').length!==1||params.getAll('report').length>1||!ids.includes(id))throw Error('Invalid selection');
      const data=await get(id);if(current!==version)return;
      const entry=manifest.cases.find(c=>c.id===id);showRecord(data,entry);
      const alias=params.get('report');
      $('return-to-conversation').href=href(id);$('return-to-conversation').textContent=tr('← 返回案例','← Back to case');
      if(location.hash==='#report'){
        if(id==='policy-materials'&&alias==='r1'){
          editedNote.textContent=tr(`存档资料编辑稿 · ${entry.recorded_on} · 数据截至 ${entry.data_cutoff} · 不是当前 Agent 生成的回答`,
            `Edited archive · ${entry.recorded_on} · Data through ${entry.data_cutoff} · Not a current Agent response`);
          editedNote.hidden=false;
          layout.hidden=false;window.tradeintelLiveReportTitle=text(entry.title);
        }else{
          const report=data.reports.find(r=>r.report_id===alias);if(!report)throw Error('Unknown report');
          caseReport.replaceChildren();
          const view=data.reader_view?{...data.reader_view,facts:data.reader_view.facts.filter(f=>f.report_id===alias)}:null;
          window.tradeintelLiveReportTitle=globalThis.TradeIntelReportView.renderTradeReport(caseReport,report,{language:english()?'en':'zh',readerView:view});
          caseReport.prepend(make('p',tr(`案例存档 · ${entry.recorded_on} · 非实时数据`,`Saved case · ${entry.recorded_on} · Not live data`),'case-meta'));caseReport.hidden=false;
        }
        document.title=`${window.tradeintelLiveReportTitle} · TradeIntel`;
      }
    }catch(_){if(current===version)unavailable();}
  }
  function returnLocal(){
    if(!local||!window.tradeintelCaseActive)return;
    history.pushState(null,'',location.pathname+'#workspace');window.tradeintelCaseActive=false;selected=null;
    caseReport.hidden=true;$('return-to-conversation').href='#workspace';$('return-to-conversation').textContent=tr('← 返回对话','← Back to conversation');
    window.dispatchEvent(new Event('tradeintel:return-local'));window.dispatchEvent(new Event('hashchange'));
  }
  document.querySelectorAll('.nav a[href="#workspace"]').forEach(a=>a.addEventListener('click',e=>{if(local&&window.tradeintelCaseActive){e.preventDefault();returnLocal();}}));
  // The mobile case reader uses normal links, not a second conversation store.
  addEventListener('hashchange',route);addEventListener('popstate',route);addEventListener('tradeintel:language',route);
  addEventListener('beforeprint',()=>{opened=[...$('report').querySelectorAll('details:not([open])')];for(const d of opened)d.open=true;});
  addEventListener('afterprint',()=>{for(const d of opened)d.open=false;opened=[];});
  fetch('cases/index.json').then(r=>{if(!r.ok)throw Error('Missing manifest');return r.json();}).then(index=>{
    if(index.schema!=='tradeintel-public-cases-v1'||index.cases.map(c=>c.id).join(',')!==ids.join(','))throw Error('Invalid manifest');manifest=index;route();
  }).catch(()=>{labels();unavailable();});
})();
