/* Saved case reader. No model endpoints, config, free-form submission or storage. */
(() => {
  const ids=['soybean-trade','soybean-oil','policy-materials','missing-month'];
  // The case list remains navigable while its catalog is loading.
  const previews=[
    {id:ids[0],kind:'real_agent_run',title:{zh:'大豆进口，接着问出口',en:'Soybean imports, then exports'},description:{zh:'查看连续追问，以及进口和出口的图表报告。',en:'Follow the conversation and read import and export charts.'}},
    {id:ids[1],kind:'real_agent_run',title:{zh:'豆油进口查询',en:'Soybean oil imports'},description:{zh:'按商品名称查找豆油，查看十二个月的进口变化。',en:'Look up soybean oil and view twelve months of imports.'}},
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
  let manifest=null,selected=null,version=0,catalogState='loading';const cache=new Map();let opened=[];
  const href=(id,alias,hash='cases')=>`?case=${id}${alias?'&report='+alias:''}&lang=${english()?'en':'zh'}#${hash}`;
  const link=(label,url,className)=>{const node=make('a',label,className);node.href=url;bindCaseLink(node,url);return node;};
  const unavailable=()=>{
    editedNote.hidden=true;
    window.tradeintelCaseActive=true;window.tradeintelLiveReportTitle=tr('案例暂不可用','Case unavailable');
    document.title=`${window.tradeintelLiveReportTitle} · TradeIntel`;
    $('return-to-conversation').href=location.pathname+`?lang=${english()?'en':'zh'}#cases`;
    $('return-to-conversation').textContent=tr('← 返回案例列表','← Back to cases');
    record.replaceChildren(make('h2',tr('案例暂不可用','Case unavailable')),make('p',tr('没有找到这份存档，请返回案例列表选择。','This archive could not be found. Return to the case list to choose another.')));
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
    heading.replaceChildren(make('p',tr('TRADEINTEL / 案例','TRADEINTEL / EXAMPLES'),'eyebrow'),make('h1',tr('使用案例','Use cases')),
      make('p',tr('查看提问、处理过程和结果报告。部分案例展示缺少数据时的处理。','Explore questions, the steps taken, and the resulting reports, including requests with unavailable data.')));
    cards.setAttribute('aria-label',tr('案例','Cases'));
    cards.replaceChildren();
    const groups=[
      {label:tr('商品查询与追问','Product queries and follow-ups'),ids:['soybean-trade','soybean-oil']},
      {label:tr('政策与贸易','Policy and trade'),ids:['policy-materials']},
      {label:tr('缺数据处理','Missing data'),ids:['missing-month']}
    ];
    const purposes={
      'soybean-trade':tr('连续追问','Follow-up questions'),
      'soybean-oil':tr('商品区分','Product lookup'),
      'policy-materials':tr('政策与进口图表','Policy and import charts'),
      'missing-month':tr('月份不可用','Unavailable month')
    };
    const explanations={
      'soybean-trade':tr('先问大豆进口，再接着问出口。查看助手如何接续前一个问题，并给出对应报告。','Ask about soybean imports, then follow up about exports. See how the assistant carries the conversation forward and returns the relevant reports.'),
      'soybean-oil':tr('按商品名称查找豆油的官方商品范围，阅读对应的十二个月进口图表报告。','Look up the official product scope for soybean oil and read its twelve-month import report.'),
      'policy-materials':tr('阅读关税公告背景、五类商品的进口图表，以及相关数据出处。','Read tariff-notice context, import charts for five product codes, and the data sources.'),
      'missing-month':tr('查看所问月份尚未收录时，助手如何说明数据缺口。','See how the assistant explains a gap when the requested month has not been included.')
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
        const row=make('div',undefined,'case-picker-row');
        const explanation=make('p',explanations[id],'case-picker-description');
        explanation.id=`case-description-${id}`;small.setAttribute('aria-describedby',explanation.id);
        row.append(small,explanation);choices.append(row);
      }
      section.append(choices);cards.append(section);
    }
    for(const status of [catalogStatus]){
      status.replaceChildren();status.hidden=catalogState==='ready';
      if(catalogState==='loading')status.append(make('p',tr('正在读取案例目录…','Loading the case catalog…')));
      if(catalogState==='error'){
        status.append(make('p',tr('案例目录未能加载。请重试；如果直接打开了本地文件，请按快速开始启动网页服务。','The case catalog could not be loaded. Retry, or start the web server from Quickstart if you opened a local file directly.')));
        const retry=make('button',tr('重新加载','Retry'),'button outline');retry.type='button';retry.addEventListener('click',loadCatalog);status.append(retry);
      }
    }
    if(!local){
      if($('workspace'))$('workspace').hidden=true;
      document.querySelectorAll('.nav a[href="#workspace"]').forEach(a=>{a.hidden=true;});
    }
  }
  function showRecord(caseData,entry){
    if(entry.id==='policy-materials'){
      record.replaceChildren(make('p',tr('政策报告示例','POLICY REPORT EXAMPLE'),'eyebrow'),
        make('h2',text(entry.title)),
        make('p',tr('报告汇集美国钨与光伏材料的附加关税公告、五类商品的进口金额和中国来源份额。','The report brings together an additional-duty notice for tungsten and solar materials, import values for five product codes, and China-origin shares.'),'policy-intro'));
      const topics=make('div',undefined,'policy-case-topics');
      for(const [zhTitle,enTitle,zhBody,enBody] of [
        ['公告涉及什么','What the notice covers','列明的商品、附加税率和生效时间，以及适用时需要核对的条件。','Listed products, additional duties, effective dates, and conditions to check.'],
        ['进口数据怎么看','What the import data shows','按五类商品分别查看2026年2月至7月的进口金额，以及其中来自中国的份额。','Import values for five product codes from February to July 2026, with the share sourced from China.'],
        ['报告里有什么','Inside the report','商品切换、逐月图表、完整数值表，以及公告和数据出处；可以打印或保存为PDF。','Product selection, monthly charts, exact-value tables, and notice and data sources. Print it or save it as a PDF.']
      ]){const topic=make('section');topic.append(make('h3',tr(zhTitle,enTitle)),make('p',tr(zhBody,enBody)));topics.append(topic);}
      record.append(topics,link(tr('阅读报告 →','Read the report →'),href(entry.id,'r1','report'),'button primary'),
        make('p',tr(`资料编辑报告 · ${entry.recorded_on} · 数据截至 ${entry.data_cutoff}`,`Compiled report · ${entry.recorded_on} · Data through ${entry.data_cutoff}`),'case-meta'));
      const notes=make('details',undefined,'policy-case-notes');notes.append(make('summary',tr('资料日期与口径','Dates and scope')),
        make('p',tr('公告列出的是附加税率；现行全部税率与适用条件需另行核对。贸易图表呈现进口金额，政策效果需要其他证据支持。','The notice lists additional duties. Current total duties and applicability require further checks; policy effects require evidence beyond the import values shown.')));
      record.append(notes);return;
    }
    record.replaceChildren(make('p',tr(`存档 ${entry.recorded_on} · 数据截至 ${entry.data_cutoff}`,`Recorded ${entry.recorded_on} · Data through ${entry.data_cutoff}`),'case-meta'),
      make('h2',text(entry.title)),make('p',text(entry.limitations),'case-limit'));
    if(entry.model)record.append(make('p',`${entry.model.request_name} · ${entry.model.reasoning}`,'case-meta'));
    if(english()&&caseData.turns.length)record.append(make('p','English translation of the saved Chinese exchange.','case-meta'));
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
    if(caseData.guard)record.append(make('p',tr('2026年8月尚未收录，本次未生成报告或图表。改查7月需要另行确认。','August 2026 had not been included, so no report or chart was generated. Using July instead requires confirmation.')));
    record.append(link(tr('本地运行说明 ↗','Local setup ↗'),'#project-start','text-link'));
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
          editedNote.textContent=tr(`资料编辑报告 · ${entry.recorded_on} · 数据截至 ${entry.data_cutoff}`,
            `Compiled report · ${entry.recorded_on} · Data through ${entry.data_cutoff}`);
          editedNote.hidden=false;
          layout.hidden=false;window.tradeintelLiveReportTitle=text(entry.title);
        }else{
          const report=data.reports.find(r=>r.report_id===alias);if(!report)throw Error('Unknown report');
          caseReport.replaceChildren();
          const view=data.reader_view||null;
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
