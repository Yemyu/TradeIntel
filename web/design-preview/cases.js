/* Saved case reader. No model endpoints, config, free-form submission or storage. */
(() => {
  const ids=['soybean-trade','soybean-oil','policy-materials','missing-month'];
  // Keep navigation visible while the saved-case catalog is loading.
  const previews=[
    {id:ids[0],kind:'real_agent_run',title:{zh:'大豆进口，接着问出口',en:'Soybean imports, then exports'},description:{zh:'查看连续追问，以及进口和出口的图表报告。',en:'Follow the conversation and read import and export charts.'}},
    {id:ids[1],kind:'real_agent_run',title:{zh:'豆油不是原料大豆',en:'Soybean oil is not raw soybeans'},description:{zh:'按商品名称查找豆油，查看十二个月的进口变化。',en:'Look up soybean oil and view twelve months of imports.'}},
    {id:ids[2],kind:'edited_evidence_report',title:{zh:'钨和光伏材料：政策与进口',en:'Tungsten and solar materials'},description:{zh:'阅读公告背景、进口金额和中国来源份额。',en:'Read notice context, import values, and China-origin shares.'}},
    {id:ids[3],kind:'guarded_run',title:{zh:'所问月份还没有数据',en:'The requested month is not available'},description:{zh:'查看没有对应月份数据时，助手如何说明缺口。',en:'See the response when the requested month is unavailable.'}}
  ];
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
  const catalogStatus=make('div',undefined,'case-catalog-status');catalogStatus.setAttribute('role','status');shell.append(catalogStatus);
  if($('workspace'))$('workspace').after(page);else document.querySelector('main').append(page);
  const home=make('section',undefined,'section wrap case-gallery');home.id='case-gallery';
  const homeHead=make('div',undefined,'section-heading');const homeCards=make('div',undefined,'case-grid');
  const homeStatus=make('div',undefined,'case-catalog-status');homeStatus.setAttribute('role','status');
  home.append(homeHead,homeCards,homeStatus);$('home').append(home);
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
    a.href=`?case=policy-materials&report=r1&lang=${english()?'en':'zh'}#report`;
    bindCaseLink(a,()=>`?case=policy-materials&report=r1&lang=${english()?'en':'zh'}#report`);
  });
  let manifest=null,selected=null,version=0,catalogState='loading';const cache=new Map();let opened=[];
  const href=(id,alias,hash='cases')=>`?case=${id}${alias?'&report='+alias:''}&lang=${english()?'en':'zh'}#${hash}`;
  const link=(label,url,className)=>{const node=make('a',label,className);node.href=url;bindCaseLink(node,url);return node;};
  const unavailable=()=>{
    editedNote.hidden=true;
    window.tradeintelCaseActive=true;window.tradeintelLiveReportTitle=tr('案例暂不可用','Case unavailable');
    document.title=`${window.tradeintelLiveReportTitle} · TradeIntel`;
    $('return-to-conversation').href=location.pathname+`?lang=${english()?'en':'zh'}#cases`;
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
    document.querySelectorAll('#home a[href*="case=policy-materials"], .nav a[href*="case=policy-materials"]').forEach(a=>{
      a.href=href('policy-materials','r1','report');
    });
    heading.replaceChildren(make('p',tr('TRADEINTEL / 案例','TRADEINTEL / EXAMPLES'),'eyebrow'),make('h1',tr('案例与报告','Conversations and reports')),
      make('p',tr('对话示例展示提问和追问；报告示例展示整理后的图表与政策资料；缺数据案例展示无法查询时的回答。','Browse saved conversations, a policy report with charts, and an example of handling unavailable data.')));
    homeHead.replaceChildren(make('h2',tr('四个案例','Four cases')),make('p',tr('看看助手如何追问、区分商品、查阅政策，以及处理缺少月份。','Explore follow-ups, product lookup, policy reading, and unavailable data.')));
    install.replaceChildren(make('h2',tr('在自己的电脑上使用','Run it on your computer')),
      make('p',tr('公开网站不用 API，只能阅读案例。要自己提问，请启动本地服务，再填自己的模型 API。数据查询本身不需要模型或 MySQL。','The public site needs no API and only reads saved cases. To ask your own questions, run the local service and configure your own model API. Data-only queries need neither a model nor MySQL.')),
      make('p',tr('本地查询还需要下载贸易数据包，解压并核验后再启动。数据包约64 MiB，安装步骤见快速开始；macOS已验证，Windows尚未验证。','Local queries also need the trade-data bundle. Download, extract and verify it before starting. The bundle is about 64 MiB; see Quickstart for installation. macOS was verified; Windows is unverified.')),
      link(tr('源码 ↗','Source ↗'),'https://github.com/Yemyu/TradeIntel/tree/main','text-link'),
      link(tr('快速开始 ↗','Quickstart ↗'),`https://github.com/Yemyu/TradeIntel/blob/main/docs/LOCAL_RUN${english()?'':'.zh-CN'}.md`,'text-link'),
      link(tr('下载数据 ↗','Download data ↗'),'https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002','text-link'));
    cards.setAttribute('aria-label',tr('案例','Cases'));
    cards.replaceChildren();homeCards.replaceChildren();
    const groups=[
      {label:tr('对话示例','Conversations'),ids:['soybean-trade','soybean-oil']},
      {label:tr('报告示例','Report example'),ids:['policy-materials']},
      {label:tr('缺数据处理','Missing data'),ids:['missing-month']}
    ];
    const purposes={
      'soybean-trade':tr('连续追问','Follow-up questions'),
      'soybean-oil':tr('商品区分','Product lookup'),
      'policy-materials':tr('政策与进口图表','Policy and import charts'),
      'missing-month':tr('月份不可用','Unavailable month')
    };
    const entries=manifest?.cases||previews;
    for(const group of groups){
      const section=make('section',undefined,'case-picker-group');
      section.append(make('h2',group.label));
      const choices=make('div',undefined,'case-picker-options');
      for(const id of group.ids){
        const entry=entries.find(item=>item.id===id);if(!entry)continue;
        const small=link('',href(id),'case-tab');
        small.append(make('small',purposes[id]),make('span',text(entry.title)));
        if(id===selected)small.setAttribute('aria-current','page');
        choices.append(small);
      }
      section.append(choices);cards.append(section);
    }
    for(const entry of manifest?.cases||previews){
      const category=groups.find(group=>group.ids.includes(entry.id)).label;
      const card=link('',href(entry.id),'case-tile');card.append(make('small',`${category} · ${purposes[entry.id]}`),
        make('h3',text(entry.title)),make('p',text(entry.description)),make('span',tr('查看记录 →','Open record →')));homeCards.append(card);
    }
    for(const status of [homeStatus,catalogStatus]){
      status.replaceChildren();status.hidden=catalogState==='ready';
      if(catalogState==='loading')status.append(make('p',tr('正在读取案例目录…','Loading the case catalog…')));
      if(catalogState==='error'){
        status.append(make('p',tr('案例目录未能加载。请重试；如果直接打开了本地文件，请按快速开始启动网页服务。','The case catalog could not be loaded. Retry, or start the web server from Quickstart if you opened a local file directly.')));
        const retry=make('button',tr('重新加载','Retry'),'button outline');retry.type='button';retry.addEventListener('click',loadCatalog);status.append(retry);
      }
    }
    if(!local){
      if($('workspace'))$('workspace').hidden=true;
      document.querySelectorAll('.nav a[href="#workspace"],#home a[href="#workspace"],.nav a[href="#cases"],#home a[href="#cases"]').forEach(a=>{a.href='#cases';a.textContent=tr('查看案例','View cases');});
    }
  }
  function showRecord(caseData,entry){
    if(entry.id==='policy-materials'){
      record.replaceChildren(make('p',tr('政策报告示例','POLICY REPORT EXAMPLE'),'eyebrow'),
        make('h2',text(entry.title)),
        make('p',tr('美国对部分中国原产的钨和光伏材料调整了附加关税。这份报告把公告规定和相关商品的进口数据放在一起，方便查阅。','The United States changed additional duties on certain tungsten and solar materials of Chinese origin. This report brings the notice and import data together for reference.'),'policy-intro'));
      const topics=make('div',undefined,'policy-case-topics');
      for(const [zhTitle,enTitle,zhBody,enBody] of [
        ['公告涉及什么','What the notice covers','列明的商品、附加税率和生效时间，以及适用时需要核对的条件。','Listed products, additional duties, effective dates, and conditions to check.'],
        ['进口数据怎么看','What the import data shows','按五类商品分别查看2026年2月至7月的进口金额，以及其中来自中国的份额。','Import values for five product codes from February to July 2026, with the share sourced from China.'],
        ['报告里有什么','Inside the report','商品切换、逐月图表、完整数值表，以及公告和数据出处；可以打印或保存为PDF。','Product selection, monthly charts, exact-value tables, and notice and data sources. Print it or save it as a PDF.']
      ]){const topic=make('section');topic.append(make('h3',tr(zhTitle,enTitle)),make('p',tr(zhBody,enBody)));topics.append(topic);}
      record.append(topics,link(tr('阅读报告 →','Read the report →'),href(entry.id,'r1','report'),'button primary'),
        make('p',tr('这是一份根据已保存资料整理的报告，没有对应的模型对话记录。','This report was compiled from saved material; there is no associated model conversation.'),'case-meta'));
      const notes=make('details',undefined,'policy-case-notes');notes.append(make('summary',tr('资料日期与口径','Dates and scope')),
        make('p',tr(`整理日期：${entry.recorded_on}。贸易数据截至 ${entry.data_cutoff}。公告中的附加税率不代表现行全部税率；进口金额图表不用于认定政策效果。`,`Compiled on ${entry.recorded_on}. Trade data through ${entry.data_cutoff}. The notice specifies additional rather than total current duties; import charts do not establish policy effects.`)));
      record.append(notes);return;
    }
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
  async function loadCatalog(){
    catalogState='loading';labels();
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);
    try{
      const response=await fetch('cases/index.json',{signal:controller.signal});
      if(!response.ok)throw Error('Missing manifest');
      const index=await response.json();
      if(index.schema!=='tradeintel-public-cases-v1'||!Array.isArray(index.cases)||index.cases.map(c=>c.id).join(',')!==ids.join(','))throw Error('Invalid manifest');
      manifest=index;catalogState='ready';await route();
    }catch(_){
      catalogState='error';labels();
      if(new URLSearchParams(location.search).has('case'))unavailable();
    }finally{clearTimeout(timer);}
  }
  loadCatalog();
})();
