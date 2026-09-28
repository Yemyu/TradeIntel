// The real product flow is available only when this page is served by web_app.
if (location.pathname.startsWith('/preview')) {
  const english=()=>document.documentElement?.lang==='en';
  const tr=(zh,en)=>english()?en:zh;
  const setCopy=(selector,zh,en)=>{const element=document.querySelector(selector);
    if(element){element.textContent=tr(zh,en);element.dataset.en=en;}};
  setCopy('#home .section-heading > p','本地服务可查询已接入的商品数据；下方案例仍是示例。',
    'The local service can query supported trade data; the case below remains a sample.');
  setCopy('.hero-note','可在工作台查询已接入的商品数据；下方另有一份示例报告。',
    'Use the workspace to query supported trade data; a saved sample report is also available below.');
  setCopy('#workspace .composer > p:not(.eyebrow)',
    '输入商品和进出口问题；确认范围后，页面会查询已发布数据并生成图表。模型解释需要另行点击。',
    'Ask about a product and trade direction. Confirm the scope to retrieve published data and charts; model explanation is a separate, optional step.');
  setCopy('#question-form .compose-bottom > span','数据报告不用模型；模型解读是试用功能，回答请核对，调用可能产生费用。',
    'The data report works without a model. Model explanations are experimental; check them before use. Calls may incur charges.');
  setCopy('#question-form button[type=submit]','查询可用范围 ↗','Check the available scope ↗');
  const questionInput=document.querySelector('#question');
  if(questionInput){questionInput.placeholder=tr('例如：最近美国大豆出口有什么变化？',
      'For example: How have recent U.S. soybean exports changed?');
    questionInput.dataset.en='For example: How have recent U.S. soybean exports changed?';}
  const suggestion=document.querySelector('.suggestions button[data-question]');
  if(suggestion){suggestion.textContent=tr('最近美国大豆出口有什么变化？',
      'How have recent U.S. soybean exports changed?');
    suggestion.dataset.en='How have recent U.S. soybean exports changed?';
    suggestion.setAttribute('data-question','最近美国大豆出口有什么变化？');}
  const $ = id => document.getElementById(id);
  const make = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const flow = {sessionId: localStorage.getItem('tradeintel_live_session') || '', proposal: null,
    tradeProposal: null, tradeChoices: null, tradeReport: null, directionChoice: null, taskId: null};
  const status = make('p', '', 'live-status');
  status.setAttribute('role', 'status');
  $('question-form').after(status);
  const settings=make('details',undefined,'model-settings');
  settings.append(make('summary',tr('模型设置','Model settings')));
  const settingsForm=make('form');
  const provider=make('select');provider.setAttribute('aria-label',tr('模型服务','Model provider'));
  for(const [value,zh,en] of [['glm','智谱 GLM','Zhipu GLM'],['deepseek','DeepSeek','DeepSeek'],
    ['qianwen','千问平台','Qianwen']]){
    const option=make('option',tr(zh,en));option.value=value;option.dataset.zh=zh;option.dataset.en=en;provider.append(option);
  }
  const preset=make('select');preset.setAttribute('aria-label',tr('常用型号','Model preset'));
  const modelName=make('input');modelName.type='text';modelName.value='';
  modelName.placeholder='Model ID';modelName.setAttribute('aria-label','Model ID');
  const reasoning=make('select');reasoning.setAttribute('aria-label',tr('推理档位','Reasoning level'));
  for(const [value,zh,en] of [['default','服务商默认','Provider default'],['none','关闭思考','Off'],
    ['low','低','Low'],['high','高','High'],['max','最高','Max']]){
    const option=make('option',tr(zh,en));option.value=value;option.dataset.zh=zh;option.dataset.en=en;reasoning.append(option);
  }
  const secret=make('input');secret.type='password';secret.autocomplete='new-password';
  secret.placeholder=tr('新的 API Key','New API key');secret.setAttribute('aria-label',tr('新的 API Key','New API key'));
  const saveButton=make('button',tr('保存设置','Save settings'),'button outline');
  const testButton=make('button',tr('测试连接','Test connection'),'button outline');testButton.type='button';
  let modelOptions={glm:['glm-4.7','glm-4.6v','glm-4.5-air'],deepseek:['deepseek-flash','deepseek-v4-pro'],qianwen:[]};
  function optionsForProvider(){
    const previous=modelName.value;
    preset.replaceChildren();
    for(const id of modelOptions[provider.value]||[]){const option=make('option',id);option.value=id;preset.append(option);}
    const custom=make('option',tr('手动填写型号','Enter a model ID'));custom.value='custom';preset.append(custom);
    const matching=(modelOptions[provider.value]||[]).includes(previous);
    preset.value=matching?previous:(preset.options.length>1?preset.options[0].value:'custom');
    modelName.value=matching?previous:(preset.value==='custom'?'':preset.value);
    reasoning.disabled=provider.value!=='deepseek';if(reasoning.disabled)reasoning.value='default';
  }
  provider.addEventListener('change',()=>{modelName.value='';optionsForProvider();});
  preset.addEventListener('change',()=>{if(preset.value!=='custom')modelName.value=preset.value;});
  modelName.addEventListener('input',()=>{preset.value=(modelOptions[provider.value]||[]).includes(modelName.value)?modelName.value:'custom';});
  settingsForm.append(provider,preset,modelName,reasoning,secret,saveButton,testButton);
  const settingsHint=make('p',tr('可只改同一服务商的型号而不重填密钥；换服务商时需填新密钥。连接测试会发送极短请求，服务商可能计费。',
    'You can change the model within one provider without re-entering the key. Switching providers requires a new key. Connection tests send a short request and may incur charges.'),'muted');
  settings.append(settingsForm,settingsHint);
  function localizeSettings(){
    settings.querySelector('summary').textContent=tr('模型设置','Model settings');
    provider.setAttribute('aria-label',tr('模型服务','Model provider'));
    for(const option of provider.options)option.textContent=english()?option.dataset.en:option.dataset.zh;
    preset.setAttribute('aria-label',tr('常用型号','Model preset'));
    reasoning.setAttribute('aria-label',tr('推理档位','Reasoning level'));
    for(const option of reasoning.options)option.textContent=english()?option.dataset.en:option.dataset.zh;
    const custom=[...preset.options].find(option=>option.value==='custom');
    if(custom)custom.textContent=tr('手动填写型号','Enter a model ID');
    secret.placeholder=tr('新的 API Key','New API key');secret.setAttribute('aria-label',secret.placeholder);
    saveButton.textContent=tr('保存设置','Save settings');testButton.textContent=tr('测试连接','Test connection');
    settingsHint.textContent=tr('可只改同一服务商的型号而不重填密钥；换服务商时需填新密钥。连接测试会发送极短请求，服务商可能计费。',
      'You can change the model within one provider without re-entering the key. Switching providers requires a new key. Connection tests send a short request and may incur charges.');
  }
  status.after(settings);
  const report = make('section', undefined, 'live-result wrap');
  report.id = 'live-result';
  report.hidden = true;
  const reportStatus=make('p','', 'live-status report-live-status');
  reportStatus.setAttribute('role','status');
  report.append(reportStatus);
  let printOpenedDetails=[];
  addEventListener('beforeprint',()=>{
    printOpenedDetails=[...report.querySelectorAll('details:not([open])')];
    for(const detail of printOpenedDetails)detail.open=true;
  });
  addEventListener('afterprint',()=>{
    for(const detail of printOpenedDetails)detail.open=false;
    printOpenedDetails=[];
  });
  $('report').querySelector('.report-layout').before(report);
  let liveVisible = false;
  const staticReport = $('report').querySelector('.report-layout');
  const setReportMode = show => {liveVisible = show; report.hidden = !show; staticReport.hidden = show;};
  addEventListener('hashchange', () => setReportMode(liveVisible));
  const setStatus = message => {
    status.textContent = message;
    if(!['announcement-statistics-report-v1','announcement-context-report-v1'].includes(flow.tradeReport?.kind))
      reportStatus.textContent=message;
  };
  settingsForm.addEventListener('submit',async event=>{
    event.preventDefault();saveButton.disabled=true;
    try {const result=await api('/api/model/config',{provider:provider.value,
      model:modelName.value.trim(),api_key:secret.value.trim(),reasoning:reasoning.value});
      secret.value='';
      setStatus(tr(`已保存 ${result.model}；请点“测试连接”确认能否调用。`,
        `Saved ${result.model}. Use “Test connection” to check access.`));
    }catch(error){setStatus(error.message);}finally{saveButton.disabled=false;}
  });
  testButton.addEventListener('click',async()=>{
    testButton.disabled=true;setStatus(tr('正在测试模型连接……','Testing the model connection…'));
    try {const result=await api('/api/model/test',{});
      setStatus(`${english()?(result.status==='connected'?'Short connection test succeeded; a full report still needs validation.':`Provider response: ${result.message}`):result.message}${result.provider_code?tr(` 错误码：${result.provider_code}。`,` Code: ${result.provider_code}.`):''}${result.provider_param?tr(` 参数：${result.provider_param}。`,` Parameter: ${result.provider_param}.`):''}`);
    }catch(error){setStatus(error.message);}finally{testButton.disabled=false;}
  });
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    const result = await response.json();
    if (!response.ok || result.status === 'error') throw Error(result.message || `请求失败：${response.status}`);
    return result;
  }
  const latest = session => Object.values(session.tasks || {}).sort((a,b) =>
    Number(b.task_id.split('-')[1]) - Number(a.task_id.split('-')[1]))[0];
  const fmt = n => Number(n).toLocaleString(english()?'en-US':'zh-CN');
  const addParagraph = (parent,text) => parent.append(make('p',text));
  function showAnnouncementStatisticsReport(result,{navigate=true}={}){
    if(result?.kind!=='announcement-statistics-report-v1'||!Array.isArray(result.monthly))return false;
    flow.tradeReport=result;flow.tradeProposal=null;flow.tradeChoices=null;flow.directionChoice=null;
    report.replaceChildren();report.append(reportStatus);
    reportStatus.textContent=tr('以下数据报告按已发布的贸易数据生成，不调用模型。',
      'This report is generated from published trade data without calling a model.');
    const policy=result.policy||{},scope=result.scope||{};
    const officialTitle=policy.title||policy.fields?.find(item=>item.field==='title'&&item.status==='known')?.value||'';
    const displayTitle=tr('公告所涉商品的美国进口情况','U.S. imports of products in this notice');
    window.tradeintelLiveReportTitle=displayTitle;
    document.title=`${displayTitle} · TradeIntel`;
    try{localStorage.setItem('tradeintel_live_trade_report',JSON.stringify(result));
      if(result.report_id)localStorage.setItem('tradeintel_live_trade_report_id',result.report_id);
      localStorage.setItem('tradeintel_last_report_type','trade');}catch(_){}
    report.append(make('p',tr('公告与贸易数据','Notice and trade data'),'eyebrow'),make('h1',displayTitle));
    if(officialTitle)report.append(make('p',tr('公告原题：','Official notice: ')+officialTitle,'official-notice-title'));
    addParagraph(report,tr(`${scope.start_month} 至 ${scope.end_month} · 中国来源的美国消费进口。图中只汇总当月有观测的 HTS10 细码。`,
      `${scope.start_month} to ${scope.end_month} · U.S. imports for consumption from China. Charts sum only HTS10 lines observed that month.`));
    const applicability=make('aside',undefined,'announcement-applicability-note');
    applicability.append(make('strong',tr('税率说明','About the rate shown in this notice')));
    addParagraph(applicability,tr('下面是这份公告发布时写的税率，不等于图表月份或今天实际适用的税率。后来的调整和排除，我们还没有核对。',
      'The rates below are what this notice said when published. We have not checked later amendments or exclusions, so do not treat them as rates for the charted months or today.'));
    if(scope.notice_time_relation==='before_recorded_effective_month')
      addParagraph(applicability,tr('所选贸易月份都早于这份公告原文记载的生效月份；这些数字只提供更早时期的商品贸易背景，不是政策实施后的结果。',
        'All selected trade months precede the effective month recorded in this notice. These figures are earlier trade context, not post-policy results.'));
    report.append(applicability);
    if(scope.unselected_whole_codes?.length||scope.excluded_partial_entries?.length)
      addParagraph(report,tr(`本次只查所选商品；另有 ${scope.unselected_whole_codes?.length||0} 个完整税号未选，${scope.excluded_partial_entries?.length||0} 个部分编码不纳入统计。`,
        `This report covers only the selected products; ${scope.unselected_whole_codes?.length||0} complete codes were not selected and ${scope.excluded_partial_entries?.length||0} partial codes are excluded.`));
    const months=result.monthly,latest=months.at(-1);
    const summary=make('section',undefined,'live-section');summary.append(make('h2',tr('最近月份','Latest month')));
    if(latest?.observed_value_usd===null||latest?.observed_value_usd===undefined)
      addParagraph(summary,tr(`${latest?.month||scope.end_month} 没有可用的贸易金额。`,`No trade value is available for ${latest?.month||scope.end_month}.`));
    else addParagraph(summary,tr(`${latest.month} 已观测金额合计 ${fmt(latest.observed_value_usd)} 美元；${latest.complete_codes}/${latest.selected_codes} 个商品范围的细码完整。金额不代表政策适用金额。`,
      `${latest.month}: observed values sum to ${fmt(latest.observed_value_usd)} USD; detailed codes are complete for ${latest.complete_codes} of ${latest.selected_codes} products. This is not a policy liability.`));
    report.append(summary);
    const chart=make('section',undefined,'live-section');chart.append(make('h2',tr('逐月进口金额','Monthly import values')));
    addParagraph(chart,tr('柱形显示当月已观测金额之和。若商品细码不完整，金额可能低于实际总额；空白月份表示没有可用记录，不按零处理。',
      'Bars sum observed values for each month. Incomplete product codes may understate the total; a blank month means no published record, not zero.'));
    const max=Math.max(1,...months.map(item=>item.observed_value_usd||0));const bars=make('div',undefined,'trade-bars');
    for(const item of months){const line=make('div',undefined,'trade-bar-row');line.append(make('span',item.month));
      const track=make('div',undefined,'trade-bar-track');const fill=make('div',undefined,'trade-bar-fill');
      fill.style.width=`${Math.max(0,(item.observed_value_usd||0)/max*100)}%`;track.append(fill);
      const complete=item.complete_codes===item.selected_codes&&item.status==='queryable_aggregate';
      line.append(track,make('span',item.observed_value_usd===null?tr('无记录','No record'):
        `${fmt(item.observed_value_usd)} ${tr('美元','USD')}${complete?'':tr(' · 未完整',' · incomplete')}`));bars.append(line);}
    chart.append(bars);
    const tableDetails=make('details',undefined,'monthly-data');tableDetails.append(make('summary',tr('最近月份逐商品明细','Latest month by product')));
    const table=make('table'),thead=make('thead'),head=make('tr');
    [tr('HTS8','HTS8'),tr('已观测金额（美元）','Observed value (USD)'),tr('与前月差额（美元）','Change from previous month (USD)'),tr('官方细码：应有 / 匹配 / 有观测','Official codes: expected / matched / observed'),tr('状态','Status')]
      .forEach(value=>head.append(make('th',value)));thead.append(head);table.append(thead);
    const body=make('tbody');for(const item of latest?.rows||[]){const row=make('tr');
      const change=item.month_change_status==='comparable'&&item.month_change_usd!==null
        ?`${item.month_change_usd>0?'+':''}${fmt(item.month_change_usd)}`:'—';
      row.append(make('td',item.hts8),make('td',item.observed_value_usd===null?'—':fmt(item.observed_value_usd)),make('td',change),
        make('td',item.expected_count===null?tr('目录不可用','catalog unavailable'):
          `${item.expected_count} / ${item.matched_count} / ${item.observed_count}`),
        make('td',item.complete?tr('完整','Complete'):tr('不完整或未知','Incomplete or unknown')));body.append(row);}
    table.append(body);const scroll=make('div',undefined,'table-scroll');scroll.append(table);tableDetails.append(scroll);chart.append(tableDetails);report.append(chart);
    const missing=make('details',undefined,'monthly-data');missing.append(make('summary',tr('查看缺失的细分编码','View missing detailed codes')));
    for(const item of latest?.rows||[])if(!item.complete){
      const absent=item.absent_codes||[],unobserved=item.unobserved_codes||[];
      addParagraph(missing,`${item.hts8}：${absent.length?tr('未出现在数据中','absent from data')+' '+absent.join(', '):''}${absent.length&&unobserved.length?'；':''}${unobserved.length?tr('存在记录但无中国来源观测','present but without a China observation')+' '+unobserved.join(', '):''}${item.classification_available?'':tr('；该月官方商品目录不可用','; official classification is unavailable for this month')}`);
    }
    if(latest?.rows?.some(item=>!item.complete)){tableDetails.append(missing);}
    const policySection=make('section',undefined,'live-section');policySection.append(make('h2',tr('这份公告原文写了什么','What this notice says')));
    const labels={title:['标题','Title'],publication_date:['公布日期','Publication date'],effective_date:['原文记载的生效日期','Effective date stated in the notice'],origin:['原产地','Origin'],hts_codes:['商品范围','Product scope'],rates:['原文记载的附加税率','Additional rates stated in the notice'],rate_meaning:['税率含义','Rate meaning'],conditions:['条件','Conditions'],exceptions:['例外','Exceptions'],revisions:['修订','Revisions'],clock_24h:['时间','Time'],timezone:['时区','Time zone'],entry_events:['适用事件','Entry events']};
    const policyValueDetails=make('details',undefined,'monthly-data announcement-policy-details');
    policyValueDetails.append(make('summary',tr('查看商品税号与公告原文税率明细','View product codes and rates in this notice')));
    const legalTextDetails=make('details',undefined,'monthly-data announcement-legal-details');
    legalTextDetails.append(make('summary',tr('查看完整条件、例外和修订条款','Read full conditions, exceptions and revisions')));
    for(const field of policy.fields||[]){const [zh,en]=labels[field.field]||[field.field,field.field];
      if(field.status!=='known'){
        addParagraph(policySection,`${tr(zh,en)}：${field.status==='conflict'?tr('公告文本存在冲突，需人工判断','The notice text conflicts; manual review is needed'):tr('尚未确认','Not confirmed')}`);
        continue;
      }
      if(field.field==='hts_codes'&&Array.isArray(field.value)){
        addParagraph(policySection,`${tr('商品范围','Product scope')}：${tr(`已确认 ${field.value.length} 个完整 HTS8 商品编码，明细可展开查看。`,`Confirmed ${field.value.length} whole HTS8 product codes; expand to view the list.`)}`);
        addParagraph(policyValueDetails,`${tr('已确认的完整 HTS8 商品编码','Confirmed whole HTS8 product codes')}：${field.value.map(item=>item.code).join('、')}`);
      }else if(field.field==='rates'&&field.value&&typeof field.value==='object'&&!Array.isArray(field.value)){
        const groups=new Map();
        for(const [code,rate] of Object.entries(field.value)){
          const key=String(rate);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(code);
        }
        addParagraph(policySection,`${tr('公告原文记载的附加税率','Additional rates stated in this notice')}：${groups.size===1
          ?tr(`${[...groups.keys()][0]}%（${Object.keys(field.value).length} 个税号）`,`${[...groups.keys()][0]}% (${Object.keys(field.value).length} product codes)`)
          :tr(`共 ${groups.size} 档，税号明细可展开查看。`,`${groups.size} rate levels; expand to view the product-code details.`)}`);
        for(const [rate,codes] of groups)addParagraph(policyValueDetails,`${tr('公告原文记载的附加税率','Additional rate stated in this notice')} ${rate}%：${codes.join('、')}`);
      }else if(['conditions','exceptions','revisions'].includes(field.field)){
        addParagraph(policySection,`${tr(zh,en)}：${tr('已登记，完整条款可展开查看。','Recorded; expand to read the full text.')}`);
        const values=Array.isArray(field.value)?field.value:[field.value];
        for(const item of values){const paragraph=make('p',`${tr(zh,en)}：${item}`,'announcement-legal-text');legalTextDetails.append(paragraph);}
      }else if(Array.isArray(field.value))addParagraph(policySection,`${tr(zh,en)}：${field.value.join('；')}`);
      else if(field.value&&typeof field.value==='object')addParagraph(policySection,`${tr(zh,en)}：${Object.entries(field.value).map(([key,value])=>`${key}：${value}`).join('；')}`);
      else addParagraph(policySection,`${tr(zh,en)}：${field.value}`);
    }
    if(policyValueDetails.querySelector('p'))policySection.append(policyValueDetails);
    if(legalTextDetails.querySelector('p'))policySection.append(legalTextDetails);
    if(policy.source_provenance==='user_supplied_unverified')addParagraph(policySection,tr('来源文字由用户粘贴，网址尚未核验。','The text was pasted by the user; its URL has not been verified.'));
    const citations=make('details',undefined,'monthly-data');citations.append(make('summary',tr('查看字段原文引文','View quoted source text')));
    for(const item of policy.citations||[]){const label=labels[item.field]||[item.field,item.field];
      addParagraph(citations,`${tr(label[0],label[1])} · ${item.section_id||''}：${item.quote||''}`);}
    if(policy.source_url&&/^https:\/\//.test(policy.source_url)){const link=make('a',tr('打开公告来源','Open notice source'));link.href=policy.source_url;link.target='_blank';link.rel='noopener noreferrer';citations.append(link);}
    policySection.append(citations);report.append(policySection);
    const sources=make('section',undefined,'live-section');sources.append(make('h2',tr('数据来源','Data sources')));
    const sourceDetails=make('details',undefined,'monthly-data');
    const sourceMonthCount=(result.sources||[]).reduce((count,source)=>count+(source.months?.length||0),0);
    sourceDetails.append(make('summary',tr(`查看 ${sourceMonthCount} 个月的贸易数据来源`,`View trade-data sources for ${sourceMonthCount} months`)));
    for(const source of result.sources||[]){const months=(source.months||[]).join('、');
      const label=make('a',tr(`${months} 美国人口普查局月度贸易数据`,`${months} U.S. Census monthly trade data`));
      label.href=source.url;label.target='_blank';label.rel='noopener noreferrer';sourceDetails.append(label);}
    if(result.sources?.length)sources.append(sourceDetails);
    if(policy.source_url&&/^https:\/\//.test(policy.source_url)){const link=make('a',tr('公告原文','Notice text'));link.href=policy.source_url;link.target='_blank';link.rel='noopener noreferrer';sources.append(link);}
    report.append(sources);
    const notes=make('section',undefined,'live-section');notes.append(make('h2',tr('数据说明','Data notes')));
    const noteTranslations={
      '图表金额为该月已观测的中国来源消费进口额；缺失细分行不补零。':'Chart values sum observed U.S. imports for consumption from China; missing detailed lines are not treated as zero.',
      '公告原文的税率不代表所选月份的实际适用税率；后续修订与排除尚未核对。':'Rates in the source notice are not verified as applicable in the selected months; later amendments and exclusions have not been checked.',
      '它不是逐笔适用税额、政策造成的贸易变化或因果效果。':'These figures are not transaction-level duties, policy-caused trade changes, or causal effects.',
      '跨年商品编码可比性尚未核验；报告不计算跨年增幅。':'Cross-year product-code comparability has not been verified; no year-over-year growth is calculated.'};
    for(const note of result.notes||[])addParagraph(notes,english()?(noteTranslations[note]||note):note);report.append(notes);
    setReportMode(true);
    if(navigate)location.hash='report';
    return true;
  }
  function showAnnouncementContextReport(result,{navigate=true}={}){
    if(result?.kind!=='announcement-context-report-v1'||
       !['parent','country','source_only'].includes(result.context_type)||
       !Array.isArray(result.monthly)||!result.policy||!result.scope)return false;
    flow.tradeReport=result;flow.tradeProposal=null;flow.tradeChoices=null;flow.directionChoice=null;
    report.replaceChildren();report.append(reportStatus);
    const policy=result.policy,scope=result.scope,sourceOnly=result.context_type==='source_only';
    reportStatus.textContent=sourceOnly?
      tr('这张事实卡只整理已确认的公告原文，不查询贸易数据或调用模型。',
        'This fact card uses confirmed notice text only. It does not query trade data or call a model.'):
      tr('这份报告来自已确认的公告原文及本地数据，不调用模型。',
        'This report uses confirmed notice text and local data. It does not call a model.');
    const title=sourceOnly?tr('公告原文事实卡','Notice facts'):
      result.context_type==='parent'?tr('公告与上层商品进口背景','Notice and broader product imports'):
        tr('公告与中国大陆进口背景','Notice and China-origin import background');
    window.tradeintelLiveReportTitle=title;
    document.title=`${title} · TradeIntel`;
    try{localStorage.setItem('tradeintel_live_trade_report',JSON.stringify(result));
      if(result.report_id)localStorage.setItem('tradeintel_live_trade_report_id',result.report_id);
      localStorage.setItem('tradeintel_last_report_type','trade');}catch(_){}
    report.append(make('p',sourceOnly?tr('公告原文','Notice text'):
      tr('公告原文与贸易数据','Notice text and trade data'),'eyebrow'),make('h1',title));
    const policySection=make('section',undefined,'live-section');
    policySection.append(make('h2',tr('公告说的是什么','What the notice says')));
    addParagraph(policySection,policy.policy_population||tr('公告对象尚未说明。','Notice scope was not recorded.'));
    const fieldLabels={title:['标题','Title'],publication_date:['公布日期','Publication date'],
      effective_date:['原文生效日期','Effective date in the notice'],origin:['原产地','Origin'],
      hts_codes:['商品范围','Products'],rates:['原文税率','Rates in the notice'],
      rate_meaning:['税率性质','Rate type'],conditions:['适用条件','Conditions'],
      exceptions:['例外','Exceptions'],revisions:['修订','Amendments'],
      entry_events:['入境事件','Entry events'],clock_24h:['时刻','Time'],timezone:['时区','Time zone']};
    const factDetails=make('details',undefined,'monthly-data');
    factDetails.append(make('summary',tr('查看已确认字段与原文引文','Confirmed fields and source quotes')));
    const visibleFields=new Set(['title','effective_date','origin','conditions','exceptions','rates']);
    for(const field of policy.confirmed_fields||[]){
      const labels=fieldLabels[field.field]||[field.field,field.field];
      const label=tr(labels[0],labels[1]);
      const value=field.status==='known'?(typeof field.value==='string'?field.value:
        Array.isArray(field.value)?field.value.join('；'):JSON.stringify(field.value)):field.status==='conflict'?
        tr('原文存在冲突，需复核。','Source text conflicts; review is needed.'):
        tr('尚未确认。','Not confirmed.');
      if(visibleFields.has(field.field)){
        if(Array.isArray(field.value)&&field.status==='known'){
          addParagraph(policySection,`${label}：`);
          const list=make('ul');for(const item of field.value)list.append(make('li',String(item)));
          policySection.append(list);
        }else addParagraph(policySection,`${label}：${value}`);
      }
      if(Array.isArray(field.value)&&field.status==='known'){
        addParagraph(factDetails,`${label} · ${field.status}：`);
        const list=make('ul');for(const item of field.value)list.append(make('li',String(item)));
        factDetails.append(list);
      }else addParagraph(factDetails,`${label} · ${field.status}：${value}${field.reason?`（${field.reason}）`:''}`);
      for(const evidence of field.evidence||[])
        addParagraph(factDetails,`${evidence.section_id}：${evidence.quote}`);
    }
    for(const evidence of policy.evidence||[])
      addParagraph(factDetails,`${tr('关联判断引文','Linkage quote')} · ${evidence.section_id}：${evidence.quote}`);
    policySection.append(factDetails);
    if(english()&&(policy.confirmed_fields||[]).some(field=>
      /[\u3400-\u9fff]/.test(JSON.stringify(field.value)||'')))
      addParagraph(policySection,'The confirmed field content remains in the language in which it was entered; switching the interface does not translate it.');
    if(policy.source_provenance!=='verified_official')
      addParagraph(policySection,tr('原文和网址由使用者提供或尚未独立核验，请对照官方文件。',
        'The pasted source text or URL has not been independently verified. Check the official document.'));
    report.append(policySection);
    const boundary=make('aside',undefined,'announcement-applicability-note');
    boundary.append(make('strong',sourceOnly?tr('税率适用仍需核对','Rate applicability still needs checking'):
      tr('税率和金额的边界','What these rates and values mean')));
    addParagraph(boundary,sourceOnly?
      tr('原公告记载的税率，不等于今天实际适用的税率。这张卡没有可对应的贸易金额。',
        'A rate in the source notice is not verified as applicable today. This card has no linked trade value.'):
      tr('原公告记载的税率，不等于这些月份或今天实际适用的税率。下面的贸易金额也不是政策覆盖额或政策效果。',
        'A rate in the source notice is not verified as applicable in these months or today. Trade values below are not policy coverage or policy effects.'));
    report.append(boundary);
    const context=make('section',undefined,'live-section');
    context.append(make('h2',tr('能查到什么贸易数据','What the trade data can show')));
    addParagraph(context,scope.statistical_population||tr('现有月度商品表不能可靠对应这份公告的对象。',
      'The monthly product table cannot reliably represent the population in this notice.'));
    for(const item of scope.unobserved_eligibility||[])
      addParagraph(context,`${tr('月表不能核对','Not observable in the monthly table')}：${item.description}`);
    if(scope.origin_alignment==='mainland_subset_of_china_hk')
      addParagraph(context,tr('公告涉及中国和香港；本图只显示中国大陆来源，不含香港。',
        'The notice covers China and Hong Kong; the chart shows only the China country code, not Hong Kong.'));
    report.append(context);
    if(sourceOnly){
      const noChart=make('section',undefined,'live-section');
      noChart.append(make('h2',tr('这里不画贸易图','No trade chart for this notice')));
      addParagraph(noChart,tr('现有月度商品表不能完整识别这份公告所指的对象，因此不绘制贸易金额图。',
        'The monthly product table cannot identify the full population covered by this notice, so this card does not draw a trade value chart.'));
      report.append(noChart);
    }else{
      const months=result.monthly;
      const numberFor=item=>result.context_type==='parent'?item.whole_parent_value_usd:
        item.china_mainland_import_value_usd;
      const label=result.context_type==='parent'?
        tr(`整个 ${scope.context_code} 商品组的中国大陆来源进口额`,
          `China-origin imports for the whole ${scope.context_code} product group`):
        tr('已发布月包中的中国大陆来源进口额','China-origin imports in the published monthly files');
      const chart=make('section',undefined,'live-section');
      chart.append(make('h2',label));
      addParagraph(chart,result.context_type==='parent'?
        tr('这是更宽的商品组，包含公告没有覆盖的货品；缺少细码的月份不显示金额。',
          'This broader product group includes goods outside the notice. Months with incomplete detailed codes have no value.'):
        tr('金额由官方原始月包逐商品复算；香港单列来源没有并入。',
          'Values were reconciled product by product to the retained source files. Hong Kong is not included.'));
      const max=Math.max(1,...months.map(item=>numberFor(item)||0));
      const bars=make('div',undefined,'trade-bars');
      for(const item of months){
        const value=numberFor(item);const line=make('div',undefined,'trade-bar-row');
        line.append(make('span',item.month));
        const track=make('div',undefined,'trade-bar-track');
        const fill=make('div',undefined,'trade-bar-fill');
        fill.style.width=value===null||value===undefined?'0%':`${Math.max(0,value/max*100)}%`;
        track.append(fill);line.append(track,make('span',value===null||value===undefined?
          tr('细码不完整，未显示金额','Incomplete detailed codes; no value shown'):
          `${fmt(value)} ${tr('美元','USD')}`));bars.append(line);
      }
      chart.append(bars);report.append(chart);
    }
    const sources=make('details',undefined,'live-section monthly-data');
    sources.append(make('summary',tr('来源与核对方法','Sources and checks')));
    if(policy.source_url&&/^https:\/\//.test(policy.source_url)){
      const link=make('a',tr('查看公告来源','Open notice source'));
      link.href=policy.source_url;link.target='_blank';link.rel='noopener noreferrer';sources.append(link);
    }
    for(const source of sourceOnly?[]:(result.sources||[])){
      if(source.url&&/^https:\/\//.test(source.url)){
        const link=make('a',`${source.month||''} ${tr('贸易数据原包','trade source file')}`);
        link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';sources.append(link);
      }
    }
    addParagraph(sources,sourceOnly?
      tr('本卡逐字段保存原公告文字和引文；没有查询贸易数据，也没有生成数据版本或复算金额。',
        'This card preserves confirmed notice fields and their quotations. It did not query trade data or calculate trade values.'):
      tr('本报告绑定原公告和数据版本；上层商品按官方子码核对，国家背景与留存原始月包逐商品复算。',
        'This report is bound to a notice and data version. Product groups are checked against official detailed codes; country context is reconciled with retained source files.'));
    const sourceNoteTranslations={
      '这是一张公告原文事实卡，不是贸易金额报告。':'This is a notice fact card, not a trade value report.',
      '已确认字段只反映原公告文字，不代表现行税率或当前适用状态。':'Confirmed fields describe the source notice, not current rates or applicability.',
      '未知字段及无法从贸易表观察的资格条件保留原样，不补零也不推断政策效果。':'Unknown fields and conditions absent from the trade table remain unresolved; no zeroes or policy effects are inferred.'};
    for(const note of result.notes||[])addParagraph(sources,
      english()?(sourceNoteTranslations[note]||note):note);
    report.append(sources);
    setReportMode(true);if(navigate)location.hash='report';return true;
  }
  const englishTrend = series => {
    const measured=series.filter(row=>row.status==='observed'&&Number.isFinite(row.value_usd));
    if(!measured.length)return 'No published monthly value is available for this range.';
    if(measured.length===1)return `Only ${measured[0].month} has a published value; one month does not establish a trend.`;
    const first=measured[0],last=measured.at(-1);
    const high=Math.max(...measured.map(row=>row.value_usd));
    const low=Math.min(...measured.map(row=>row.value_usd));
    const highs=measured.filter(row=>row.value_usd===high).map(row=>row.month).join(', ');
    const lows=measured.filter(row=>row.value_usd===low).map(row=>row.month).join(', ');
    const change=last.value_usd-first.value_usd;
    return `Across ${measured.length} published months, ${last.month} is ${fmt(Math.abs(change))} USD ${change>=0?'above':'below'} ${first.month}. `+
      `The highest value was ${fmt(high)} USD (${highs}); the lowest was ${fmt(low)} USD (${lows}). These values alone do not establish a cause.`;
  };
  const englishNote = note => ({
    '本报告只使用美国商品总出口额（国产出口与再出口之和，FAS），不包含进口。':
      'This report uses U.S. total exports (domestic exports plus re-exports, FAS); it does not include imports.',
    '本报告只使用美国消费进口额，不包含出口。':
      'This report uses U.S. imports for consumption; it does not include exports.',
    '金额变化可能来自数量或价格，不能仅凭金额判断政策效果。':
      'Value changes may reflect quantity or price. These values alone cannot establish a policy effect.',
    '金额变化可能来自进口数量或价格；仅凭金额不能判断政策效果。':
      'Value changes may reflect import quantity or price. These values alone cannot establish a policy effect.',
    '金额变化不等于商品数量变化，也不能单凭本报告归因于某项政策。':
      'A change in value is not necessarily a change in quantity and cannot, by itself, be attributed to a policy.'
  })[note] || `Data note (original Chinese): ${note}`;
  const directionEnglish = value => ({'增加':'increased','减少':'decreased','持平':'was unchanged'})[value]||'changed';
  function englishRelation(card){
    const flow=card.flow==='export'?'Export value':'Import value';
    if(card.id==='both.latest_relation'){
      return `In ${card.months.at(-1)}, import value ${directionEnglish(card.import_direction)} and export value ${directionEnglish(card.export_direction)} from the previous month. The two directions moved ${card.relation==='同向'?'in the same direction':'in different directions'}; these measures are shown separately, not subtracted.`;
    }
    if(card.id.endsWith('.recent_run'))return `By ${card.months.at(-1)}, ${flow.toLowerCase()} had ${card.direction==='增加'?'increased':'decreased'} month over month for ${card.consecutive_changes} consecutive changes. This does not describe the entire selected period.`;
    if(card.id.endsWith('.recent_turn'))return `The ${flow.toLowerCase()} moved from ${card.previous_direction==='增加'?'up':'down'} in ${card.months[1]} to ${card.direction==='增加'?'up':'down'} in ${card.months[2]}. This describes only the latest three observed months.`;
    return card.fact;
  }
  function englishYearPeak(card){
    const flow=card.flow==='export'?'exports':'imports';
    const peakMonths=(card.high_months||[]).join(', ');
    if(card.gap_usd===0)
      return `Among observed ${card.year} months, ${peakMonths} was the ${flow} high at ${fmt(card.high_usd)} USD; ${card.latest_month} was at the same level.`;
    return `Among observed ${card.year} months, ${peakMonths} was the ${flow} high at ${fmt(card.high_usd)} USD; ${card.latest_month} was ${fmt(card.latest_usd)} USD, ${fmt(card.gap_usd)} USD below that high.`;
  }
  function appendYearPeakCard(target,observations,flow){
    const card=observations.find(item=>item.id===flow+'.same_year_peak_gap'&&item.status==='available');
    if(!card)return;
    const section=make('section',undefined,'live-section trade-year-peak');
    section.append(make('h3',tr('按同年已观察月份比较','Compare observed months within the year')));
    const item=make('article',undefined,'trade-relation-card');
    item.append(make('h4',tr('同年峰值与最新已观察月','Year peak and latest observed month')));
    addParagraph(item,english()?englishYearPeak(card):card.fact);
    section.append(item);target.append(section);
  }
  function appendRelationCards(target, cards, flow){
    const eligible=cards.filter(card=>card.status==='available'&&card.eligible_for_ai&&card.flow===flow);
    if(!eligible.length)return;
    const section=make('section',undefined,'live-section trade-relations');
    section.append(make('h3',tr(flow==='both'?'进口和出口放在一起看':'最近几个月的变化',
      flow==='both'?'Imports and exports together':'Recent monthly movement')));
    for(const card of eligible){
      const item=make('article',undefined,'trade-relation-card');
      const title=card.id.endsWith('.recent_turn')?tr('最近出现转向','Recent direction change'):
        card.id.endsWith('.recent_run')?tr('连续几个月同向变化','Consecutive monthly changes'):
          tr('进出口方向对照','Import and export comparison');
      item.append(make('h4',title));
      addParagraph(item,english()?englishRelation(card):card.fact);
      section.append(item);
    }
    target.append(section);
  }
  function appendTradeDirection(target, result, observations=[]) {
    const {scope,summary,series}=result;
    const exportFlow=scope.flow==='export';
    const direction=exportFlow?'出口':'进口';
    const metric=exportFlow?'商品总出口额（FAS）':'消费进口额';
    target.append(make('h2',tr(`美国${direction} · ${scope.product_code} 商品组`,
      `U.S. ${exportFlow?'exports':'imports'} · product group ${scope.product_code}`)));
    const intro=make('section',undefined,'live-section');intro.append(make('h3',tr('先看数字','Key figures')));
    const latest=summary.latest_value_usd;
    const counterpart=scope.partner==='CHINA'?(exportFlow?'向中国':'从中国'):(exportFlow?'向全部目的地':'从全部来源');
    addParagraph(intro,latest===null?tr(`${summary.latest_month} 没有可用金额。`,
      `No published value is available for ${summary.latest_month}.`):
      tr(`${summary.latest_month}，美国${counterpart}的${metric}为 ${fmt(latest)} 美元。`,
        `In ${summary.latest_month}, U.S. ${exportFlow?'total exports (FAS)':'imports for consumption'} ${scope.partner==='CHINA'?(exportFlow?'to China':'from China'):(exportFlow?'to all destinations':'from all origins')} were ${fmt(latest)} USD.`));
    if(summary.month_change_usd!==null)addParagraph(intro,
      tr(`比 ${summary.previous_month} ${summary.month_change_usd>=0?'增加':'减少'} ${fmt(Math.abs(summary.month_change_usd))} 美元；仅凭金额不能判断原因。`,
        `That is ${fmt(Math.abs(summary.month_change_usd))} USD ${summary.month_change_usd>=0?'higher':'lower'} than ${summary.previous_month}. The value change alone does not tell us why.`));
    else if(series.length===1)addParagraph(intro,tr(`这份报告只含一个月，不能据此判断${direction}走势。`,
      'This report covers only one month, so it cannot establish a trend.'));
    if(summary.period_total_usd!==null && series.length>1)addParagraph(intro,
      tr(`${scope.start_month} 至 ${scope.end_month} 的合计为 ${fmt(summary.period_total_usd)} 美元。`,
        `The sum from ${scope.start_month} through ${scope.end_month} was ${fmt(summary.period_total_usd)} USD.`));
    if(exportFlow&&scope.coverage_note&&series.length>1)addParagraph(intro,tr(scope.coverage_note,
      `Only ${series.length} export months are available for this query; fewer than 12 months cannot establish a long-term trend.`));
    target.append(intro);
    const trendFact=observations.find(item=>item.id===scope.flow+'.trend');
    if(trendFact){
      const trend=make('section',undefined,'live-section trade-trend-fact');
      trend.append(make('h3',tr('这段时间的走势','Over this period')));
      addParagraph(trend,english()?englishTrend(series):trendFact.fact);
      target.append(trend);
    }
    appendYearPeakCard(target,observations,scope.flow);
    appendRelationCards(target,observations,scope.flow);
    const chart=make('section',undefined,'live-section');chart.append(make('h3',tr('逐月金额','Monthly values')));
    addParagraph(chart,tr(`每条横线表示该月的${metric}，不代表商品数量。`,
      `Each bar shows ${exportFlow?'total exports (FAS)':'imports for consumption'} in that month, not the quantity of goods.`));
    const max=Math.max(1,...series.map(row=>row.value_usd||0));
    const bars=make('div',undefined,'trade-bars');
    for(const row of series){const line=make('div',undefined,'trade-bar-row');
      line.append(make('span',row.month));const track=make('div',undefined,'trade-bar-track');
      const fill=make('div',undefined,'trade-bar-fill');
      fill.style.width=`${Math.max(0,(row.value_usd||0)/max*100)}%`;track.append(fill);line.append(track,
        make('span',row.status==='observed'?tr(`${fmt(row.value_usd)} 美元`,`${fmt(row.value_usd)} USD`):
          tr('无可用金额','No published value')));bars.append(line);}
    chart.append(bars);
    const numbers=make('details',undefined,'monthly-data');numbers.append(make('summary',tr('逐月金额表','Monthly values table')));
    const scroll=make('div',undefined,'table-scroll');const table=make('table');
    const head=make('thead');const headings=make('tr');
    [tr('月份','Month'),tr(`美国${metric} / 美元`,`${exportFlow?'U.S. total exports (FAS)':'U.S. imports for consumption'} / USD`),
      tr('记录状态','Record status')].forEach(label=>headings.append(make('th',label)));
    head.append(headings);table.append(head);const body=make('tbody');
    for(const row of series){const line=make('tr');
      [row.month,row.status==='observed'?fmt(row.value_usd):'—',
       row.status==='observed'?tr('有记录','Published'):row.status==='not_processed'?tr('月份未加工','Not processed'):tr('无可用金额','No published value')]
        .forEach(value=>line.append(make('td',value)));
      body.append(line);
    }table.append(body);scroll.append(table);numbers.append(scroll);chart.append(numbers);target.append(chart);
    const detail=make('details',undefined,'live-section');detail.append(make('summary',tr('商品范围、来源与计算说明','Product scope, sources and calculations')));
    addParagraph(detail,tr(`商品：${scope.product_label}，${exportFlow?'Schedule B':'HTS'} ${scope.product_code}。方向：美国${direction}；指标：${metric}；${exportFlow?'目的地':'来源地'}：${scope.partner==='CHINA'?'中国':'全部'}。`,
      `Product: ${scope.official_product_en||scope.product_code}, ${exportFlow?'Schedule B':'HTS'} ${scope.product_code}. Direction: U.S. ${exportFlow?'exports':'imports'}. Measure: ${exportFlow?'total exports (FAS)':'imports for consumption'}. ${exportFlow?'Destination':'Origin'}: ${scope.partner==='CHINA'?'China':'all'}.`));
    if(scope.official_product_en)addParagraph(detail,tr(`美国官方英文商品范围：${scope.official_product_en}。`,
      `Official U.S. product description: ${scope.official_product_en}.`));
    addParagraph(detail,tr(exportFlow?'金额来自美国人口普查局逐月商品出口明细；总出口是本国产品出口与再出口之和，采用 FAS 口径。':'金额来自美国人口普查局逐月商品进口明细，采用消费进口额口径。',
      exportFlow?'Values come from U.S. Census monthly export detail. Total exports include domestic exports and re-exports and use the FAS basis.':
        'Values come from U.S. Census monthly import detail and use imports-for-consumption values.'));
    for(const url of [...new Set([...(scope.classification_source_urls||[]),...(result.sources||[])])].filter(url=>
      typeof url==='string' && /^https:\/\/(www\.usitc\.gov|www\.census\.gov)\//.test(url) &&
      (!url.includes('/ex_m/')||exportFlow) && (!url.includes('/im_m/')||!exportFlow))){
      const link=make('a',url);link.href=url;link.target='_blank';link.rel='noopener';detail.append(link,make('br'));
    }
    for(const note of result.notes||[])if(!note.startsWith('目前未运行模型解释'))addParagraph(detail,english()?englishNote(note):note);
    target.append(detail);
  }
  function showTradeReport(result, {navigate=true}={}) {
    if(result?.kind==='announcement-statistics-report-v1')return showAnnouncementStatisticsReport(result,{navigate});
    if(result?.kind==='announcement-context-report-v1')return showAnnouncementContextReport(result,{navigate});
    if(!['trade-query-v1','trade-query-both-v1'].includes(result?.kind)||!result.scope)return;
    if(result.kind==='trade-query-v1'&&!Array.isArray(result.series))return;
    flow.tradeReport=result;flow.tradeProposal=null;flow.tradeChoices=null;flow.directionChoice=null;
    report.replaceChildren();report.append(reportStatus);
    const scope=result.scope;
    const title=scope.flow==='both'?'进出口':scope.flow==='export'?'出口':'进口';
    window.tradeintelLiveReportTitle=result.question||`美国${scope.product_code}${title}情况`;
    if(navigate||location.hash==='#report')document.title=`${window.tradeintelLiveReportTitle} · TradeIntel`;
    try {localStorage.setItem('tradeintel_live_trade_report',JSON.stringify(result));
      if(result.report_id)localStorage.setItem('tradeintel_live_trade_report_id',result.report_id);
      localStorage.setItem('tradeintel_last_report_type','trade');} catch (_) {}
    report.append(make('p',tr('美国贸易数据','U.S. trade data'),'eyebrow'),make('h1',window.tradeintelLiveReportTitle));
    addParagraph(report,tr(`${scope.start_month} 至 ${scope.end_month} · ${scope.product_code} 商品组。完整商品范围见报告末尾。`,
      `${scope.start_month} to ${scope.end_month} · product group ${scope.product_code}. The full product scope appears below.`));
    if(result.kind==='trade-query-both-v1'){
      addParagraph(report,tr('进口与出口来自不同统计口径，下面分别展示；两项金额不能直接相减称为贸易差额。',
        'Imports and exports use different statistical bases and are shown separately. Do not subtract these values and call the difference a trade balance.'));
      const observations=result.explanation?.observations||result.observations||[];
      appendTradeDirection(report,result.import_report,observations);
      appendTradeDirection(report,result.export_report,observations);
      appendRelationCards(report,observations,'both');
    }else appendTradeDirection(report,result,result.explanation?.observations||result.observations||[]);
    const ai=make('section',undefined,'live-section');ai.append(make('h2',tr('模型解读（试用）','Model explanation (trial)')));
    const explanation=result.explanation||{status:'not_requested'};
    const aiStatus=explanation.status||'not_requested';
    if(aiStatus!=='reviewed')ai.className+=' print-exclude';
    if(aiStatus==='not_requested'&&explanation.available===false){
      addParagraph(ai,tr(explanation.availability_reason||'目前没有额外的关系可解释；上面的数据报告仍可阅读。',
        'There is no additional relationship to explain. The data report above remains available.'));
    } else if(aiStatus==='not_requested'){
      addParagraph(ai,tr('模型可能重复报告内容或说错，请对照上方数据核对后再引用。调用会把本报告的事实发送给已设置的服务商，并可能产生费用。',
        'The model may repeat the report or make mistakes. Check its response against the data before reuse. The report facts are sent to your configured provider, and charges may apply.'));
      if(result.report_id&&result.report_sha256){
        const call=make('button',tr('试用模型解读','Try model explanation'),'button primary');
        call.addEventListener('click',async()=>{
          call.disabled=true;setStatus(tr('正在生成解释。本次请求不会自动重试。','Generating an explanation. This request will not retry automatically.'));
          try {const updated=await api('/api/trade/explanation/call',{
            report_id:result.report_id,report_sha256:result.report_sha256});
            showTradeReport(updated);setStatus(updated.explanation?.status==='needs_review'
              ?tr('模型草稿已保存，请逐项核对。','Model draft saved. Review each statement against the data.'):
                tr('本次模型解释未生成可采纳内容；数据报告仍可阅读。','No usable model explanation was produced; the data report remains available.'));
          }catch(error){
            try {const saved=await api(`/api/trade/report-state?report_id=${encodeURIComponent(result.report_id)}`);
              showTradeReport(saved);
            }catch(_){ /* The call may have begun; never enable an automatic retry. */ }
            setStatus(error.message);
          }
        });ai.append(call);
      } else addParagraph(ai,tr('这是旧版浏览器缓存的报告。重新提问后可生成模型解释。',
        'This is an older report saved in the browser. Ask the question again to generate a model explanation.'));
    } else if(aiStatus==='provider_call_started'){
      addParagraph(ai,tr('模型请求已经开始。若服务中断，结果可能无法确认；系统不会自动重新发送，以免重复计费。',
        'The model request has started. If the service is interrupted, its outcome may be unknown. The system will not automatically resend it.'));
    } else if(aiStatus==='failed'||aiStatus==='unknown_outcome'||aiStatus==='invalid_answer'){
      const lead=aiStatus==='unknown_outcome'?'模型请求结果未知，不能确认是否已计费。':
        aiStatus==='invalid_answer'?'模型回答没有通过本报告的格式或证据检查。':'模型请求失败。';
      addParagraph(ai,tr(`${lead} ${explanation.error||''} 本报告不会自动重试；数据和图表不受影响。`,
        `${aiStatus==='unknown_outcome'?'The request outcome is unknown; charges cannot be ruled out.':
          aiStatus==='invalid_answer'?'The response failed format or evidence checks.':'The model request failed.'} ${explanation.error||''} No automatic retry will occur. The data and charts remain available.`));
    } else if(['needs_review','rejected','reviewed'].includes(aiStatus) && explanation.parsed){
      const accepted=new Set((explanation.review?.decisions||[]).filter(item=>item.verdict==='accept').map(item=>item.index));
      const entries=explanation.parsed.interpretations||[];
      addParagraph(ai,aiStatus==='reviewed'?tr('以下是人工核对后采纳的解释。','The following explanations were accepted after human review.'):
        tr('以下是模型草稿，尚不能当作已核实结论。请逐条对照数据。','This is a model draft, not a verified conclusion. Check every statement against the data.'));
      for(const [index,entry] of entries.entries()){
        if(aiStatus==='reviewed'&&!accepted.has(index))continue;
        const box=make('div',undefined,aiStatus==='reviewed'?'reviewed-item':'review-draft');
        const observationIds=Array.isArray(entry.observation_ids)?entry.observation_ids:
          (typeof entry.observation_id==='string'?[entry.observation_id]:[]);
        const facts=observationIds.map(id=>(explanation.observations||[]).find(item=>item.id===id)).filter(Boolean);
        if(aiStatus!=='reviewed'&&facts.length)addParagraph(box,tr('对应数据：','Supporting data (original): ')+facts.map(item=>item.fact).join('；'));
        if(aiStatus==='reviewed')addParagraph(box,entry.text);
        else {const label=make('label',undefined,'review-item');
          const checkbox=make('input');checkbox.type='checkbox';checkbox.dataset.index=String(index);
          label.append(checkbox,document.createTextNode(entry.text));box.append(label);}
        ai.append(box);
      }
      if(aiStatus!=='reviewed'){
        const confirm=make('label',undefined,'review-item');
        const checked=make('input');checked.type='checkbox';checked.id='trade-facts-checked';
        confirm.append(checked,document.createTextNode(tr('我已对照上方数据与来源，逐条核对所选解释。',
          'I checked each selected statement against the data and sources above.')));
        const submit=make('button',tr('保存审阅结果','Save review'),'button primary');
        submit.addEventListener('click',async()=>{
          if(!checked.checked){setStatus(tr('请先对照报告核对事实。','Check the facts against the report first.'));return;}
          const choices=[...ai.querySelectorAll('.review-draft input[type=checkbox]')];
          if(!choices.some(input=>input.checked)){setStatus(tr('请至少选择一条已核实的解释。','Select at least one verified explanation.'));return;}
          submit.disabled=true;
          const decisions=choices.map((input,index)=>({index,verdict:input.checked?'accept':'reject',
            reason:input.checked?'已对照本报告数据核对':'暂不采纳'}));
          try {const updated=await api('/api/trade/explanation/review',{
            report_id:result.report_id,report_sha256:result.report_sha256,
            raw_sha256:explanation.raw_sha256,revision:explanation.revision,
            reviewer:'local-user',facts_checked:true,decisions});
            showTradeReport(updated);setStatus(tr('审阅结果已保存。','Review saved.'));
          }catch(error){setStatus(error.message);submit.disabled=false;}
        });ai.append(confirm,submit);
      }
    } else addParagraph(ai,tr('解释状态暂不可用；数据报告仍可阅读。','The explanation status is unavailable; the data report remains readable.'));
    report.append(ai);setReportMode(true);
    if(!navigate)reportStatus.textContent=tr('已恢复上次的数据报告；重新提问可查询当前发布版本。',
      'Restored the previous report. Ask a new question to query the current published version.');
    if(navigate)location.hash='report';
  }
  function showTradeProposal(proposal) {
    flow.tradeProposal=proposal;flow.tradeChoices=null;flow.directionChoice=null;
    const scope=$('scope-preview');scope.replaceChildren();scope.hidden=false;
    scope.append(make('h2',tr('请确认查询范围','Confirm the query scope')));
    addParagraph(scope,tr(`问题：${proposal.question}`,`Question: ${proposal.question}`));
    const direction=proposal.flow==='both'?'进口与出口':proposal.flow==='export'?'出口':'进口';
    const classification=proposal.flow==='export'?'Schedule B':proposal.flow==='both'?'共同 HS 商品组':'HTS';
    const partner=proposal.partner==='CHINA'?'中国':proposal.flow==='export'?'全部目的地':proposal.flow==='both'?'全部来源与目的地':'全部来源';
    addParagraph(scope,tr(`商品：${proposal.product_label}（${classification} ${proposal.product_code}）；方向：美国${direction}；伙伴：${partner}。`,
      `Product: ${proposal.official_product_en||proposal.product_code} (${classification} ${proposal.product_code}); `+
      `direction: U.S. ${proposal.flow==='both'?'imports and exports':proposal.flow==='export'?'exports':'imports'}; `+
      `${proposal.flow==='export'?'destination':'origin'}: ${proposal.partner==='CHINA'?'China':'all'}.`));
    if(proposal.official_product_en)addParagraph(scope,tr(`美国官方英文商品范围：${proposal.official_product_en}。`,
      `Official U.S. product description: ${proposal.official_product_en}.`));
    addParagraph(scope,tr(`本次查询月份：${proposal.start_month} 至 ${proposal.end_month}。数据目录最新到 ${proposal.latest_available_month}。`,
      `Query period: ${proposal.start_month} to ${proposal.end_month}. Latest published month in the catalog: ${proposal.latest_available_month}.`));
    if(proposal.coverage_note)addParagraph(scope,tr(proposal.coverage_note,
      'Fewer than 12 published export months are available for this query; this range does not establish a long-term trend.'));
    const confirm=make('button',tr('确认范围，生成数据报告','Confirm scope and generate data report'),'button primary');
    confirm.addEventListener('click',async()=>{
      confirm.disabled=true;setStatus(tr('正在核对数据并生成报告……','Checking the data and generating the report…'));
      try {const request={question:proposal.question,
        selected_flow:proposal.flow,dataset_version:proposal.dataset_version};
        if(proposal.selected_product_id){request.selected_product_id=proposal.selected_product_id;
          request.catalog_version=proposal.catalog_version;}
        const result=await api('/api/trade/report',request);
        showTradeReport(result);setStatus(tr('数据报告已生成；本次尚未调用模型。','Data report generated; no model call has been made.'));
      }catch(error){setStatus(error.message);confirm.disabled=false;}
    });scope.append(confirm);
  }
  function showProductChoices(result) {
    flow.tradeChoices=result;flow.tradeProposal=null;flow.directionChoice=null;
    const preview=$('scope-preview');preview.replaceChildren();preview.hidden=false;
    preview.append(make('h2',tr('先选你想看的商品范围','Choose the product scope')));
    addParagraph(preview,tr(result.message||'同一个日常名称可能对应几个官方商品组，请先核对范围。',
      'An everyday product name may cover more than one official category. Check the description before choosing.'));
    addParagraph(preview,tr(`本次可查询 ${result.start_month} 至 ${result.end_month} 的美国${result.flow==='both'?'进出口':result.flow==='export'?'出口':'进口'}数据。`,
      `Available U.S. ${result.flow==='both'?'import and export':result.flow==='export'?'export':'import'} data: ${result.start_month} to ${result.end_month}.`));
    const list=make('div',undefined,'commodity-choices');
    for(const candidate of result.candidates||[]){
      const card=make('article',undefined,'commodity-choice');
      card.append(make('h3',english()?candidate.official_en:(candidate.zh_label||candidate.official_en)),
        make('p',tr(`${candidate.level} ${candidate.code} · ${candidate.child_codes} 个十位细码`,
          `${candidate.level} ${candidate.code} · ${candidate.child_codes} ten-digit entries`),'muted'),
        make('p',candidate.official_en,'commodity-official'));
      if(candidate.description_kind==='derived_from_10_digit_entries')
        card.append(make('p',tr('八位码范围由当月十位细码归并；上面的英文示例不是独立的官方八位标题。',
          'The eight-digit scope is assembled from that month’s ten-digit entries; the examples above are not an independent official heading.'),'muted'));
      if(candidate.zh_review_status==='machine_extracted')
        card.append(make('p',tr('中文名称由税则 PDF 提取；请以美国官方英文范围为准。',
          'The Chinese label was extracted from a tariff PDF; rely on the official U.S. English description.'),'muted'));
      const source=make('a',tr('查看美国原包来源','View original U.S. source'),'commodity-source');source.href=candidate.source_url;
      source.target='_blank';source.rel='noopener noreferrer';card.append(source);
      const choose=make('button',tr('选这个范围','Choose this scope'),'button outline');
      choose.addEventListener('click',async()=>{
        choose.disabled=true;setStatus(tr('正在核对商品、月份和数据版本……','Checking the product, months and data version…'));
        try {const selected=await api('/api/trade/prepare',{
          question:result.question,selected_flow:result.flow,
          selected_product_id:candidate.id,catalog_version:result.catalog_version});
          if(selected.status!=='ready')throw Error(selected.message||'商品范围暂不可用');
          showTradeProposal(selected);setStatus(tr('请再次核对商品、方向和月份。','Check the product, direction and months once more.'));
        }catch(error){setStatus(error.message);choose.disabled=false;}
      });card.append(choose);list.append(card);
    }preview.append(list);preview.scrollIntoView({block:'center',behavior:'smooth'});
  }
  function showProgram(session, {navigate=true}={}) {
    const task = latest(session);
    const response = task?.response;
    if (!response || response.kind !== 'temporal-report-v1') return;
    window.tradeintelLiveReportTitle=task.request_snapshot?.original_question || '贸易情况';
    document.title=`${window.tradeintelLiveReportTitle} · TradeIntel`;
    try {localStorage.setItem('tradeintel_last_report_type','policy');} catch (_) {}
    flow.taskId = task.task_id;
    report.replaceChildren();
    report.append(reportStatus);
    const question = task.request_snapshot?.original_question || '贸易情况';
    report.append(make('p','根据你的问题生成','eyebrow'),make('h1',question),
                  make('p','以下金额由已发布的数据版本计算；模型解释单独列在后面。','muted'));
    const evidence = response.report?.evidence || response.evidence || {};
    const metrics = evidence.metrics || [];
    const values = new Map(metrics.filter(m=>m.status==='known' && m.unit==='usd' &&
      ['world','china'].includes(m.id?.split(':').at(-1))).map(m =>
      [`${m.product_scope}|${m.period}|${m.id.split(':').at(-1)}`,m.value]));
    const periods = [...new Set(metrics.map(m=>m.period))].sort();
    const products = task.request_snapshot?.products || [];
    const summary = make('section',undefined,'live-section');
    summary.append(make('h2','这次报告查了什么'));
    const window=task.request_snapshot?.window || {};
    addParagraph(summary,`商品税号：${products.join('、')}。主分析月份：${window.start || '未知'} 至 ${window.end || '未知'}。${periods.some(p=>p<window.start)?'表中另含用于同期对照的历史月份。':''}`);
    addParagraph(summary,`数据包含 ${evidence.observations?.length || 0} 条程序观察。税率、生效时间及限定条件请以本报告的政策资料和公告原文为准。`);
    report.append(summary);
    const policy=response.report?.policy_context || response.policy_context || {};
    if(Array.isArray(policy.product_rates) && policy.product_rates.length){
      const section=make('section',undefined,'live-section');section.append(make('h2','政策在这里涉及哪些商品'));
      addParagraph(section,`存档公告列出的生效日期为 ${policy.effective_date || '未登记'}。以下是公告附加税率，不是现行全部税费。`);
      const list=make('ul');
      for(const item of policy.product_rates.filter(p=>products.includes(p.hts8)))
        list.append(make('li',`${item.hts8}：公告附加税率 ${item.additional_duty_percent}%。`));
      section.append(list);
      for(const limit of (policy.limitations || []).slice(0,4))addParagraph(section,limit);
      report.append(section);
    }
    const latestCards=make('section',undefined,'live-section');
    latestCards.append(make('h2',`${window.end || '最新月'}，各商品分别是多少`));
    addParagraph(latestCards,'下列金额都是美国消费进口额。不同商品的金额不要直接解释成同一种市场变化。');
    const list=make('ul');
    for(const product of products){const world=values.get(`${product}|${window.end}|world`),
      china=values.get(`${product}|${window.end}|china`);
      list.append(make('li',world===undefined?`${product}：这个月没有可用金额。`:
        `${product}：全部来源 ${fmt(world)} 美元；中国来源 ${china===undefined?'缺失':fmt(china)+' 美元'}。`));}
    latestCards.append(list);report.append(latestCards);
    const chartSection=make('section',undefined,'live-section');
    chartSection.append(make('h2','按商品查看月度金额'));
    const select=make('select');select.setAttribute('aria-label','选择商品');
    for(const product of products){const option=make('option',product);option.value=product;select.append(option);}
    const bars=make('div',undefined,'live-bars');
    const chartNote=make('p',undefined,'muted');
    function drawChart(){
      bars.replaceChildren();const product=select.value;
      const chartPeriods=periods.filter(p=>p>=window.start&&p<=window.end);
      const maximum=Math.max(1,...chartPeriods.map(p=>values.get(`${product}|${p}|world`)||0));
      for(const period of chartPeriods){const value=values.get(`${product}|${period}|world`);
        const column=make('div',undefined,'live-bar-column');
        column.append(make('strong',value===undefined?'—':`${(value/1e6).toFixed(2)}m`));
        const bar=make('span',undefined,'live-bar');bar.style.height=`${Math.max(2,(value||0)/maximum*120)}px`;
        bar.title=value===undefined?'数据缺失':`${period}：${fmt(value)}美元`;
        column.append(bar,make('small',period.slice(5)));bars.append(column);
      }
      const latestPeriod=chartPeriods.at(-1),world=values.get(`${product}|${latestPeriod}|world`),
        china=values.get(`${product}|${latestPeriod}|china`);
      chartNote.textContent=world===undefined?'这个商品的最新月数据缺失。':
        `${product} 在 ${latestPeriod} 的全部来源进口额为 ${fmt(world)} 美元`+
        (china===undefined?'；中国来源金额缺失。':`，其中中国来源 ${fmt(china)} 美元，占 ${world?(china/world*100).toFixed(2):'不可计算'}%。`);
    }
    select.addEventListener('change',drawChart);chartSection.append(select,bars,chartNote);
    addParagraph(chartSection,'柱形高度对应当月全部来源的进口金额；金额变化可能来自数量或价格，目前不能只凭这张图判断政策效果。');
    drawChart();report.append(chartSection);
    const tableSection = make('section',undefined,'live-section');
    tableSection.append(make('h2','逐月进口金额'));
    addParagraph(tableSection,'下表按同一商品和月份列出美国消费进口额。中国来源已包含在全部来源里。');
    const scroll=make('div',undefined,'table-scroll');
    const table=make('table');
    const header=make('tr');
    ['商品税号','月份','全部来源 / 美元','中国来源 / 美元','中国份额'].forEach(t=>header.append(make('th',t)));
    const head=make('thead');head.append(header);table.append(head);
    const tbody=make('tbody');
    for(const product of products) for(const period of periods) {
      const world=values.get(`${product}|${period}|world`);
      const china=values.get(`${product}|${period}|china`);
      if(world===undefined && china===undefined)continue;
      const line=make('tr');
      [product,period,world===undefined?'缺失':fmt(world),china===undefined?'缺失':fmt(china),
       world>0 && china!==undefined?`${(china/world*100).toFixed(2)}%`:'不可计算']
        .forEach(t=>line.append(make('td',t)));
      tbody.append(line);
    }
    table.append(tbody);scroll.append(table);
    const valuesDetail=make('details');valuesDetail.append(make('summary','展开完整数值表'),scroll);
    tableSection.append(valuesDetail);report.append(tableSection);
    const explanation = task.explanation || {};
    const ai = make('section',undefined,'live-section');ai.id='live-ai';
    ai.append(make('h2','模型解读（试用）'));
    addParagraph(ai,'模型回答可能有误，请对照报告数据核实后再引用。调用会把报告事实发送给已设置的模型服务商，可能产生费用。','muted');
    if(explanation.status === 'provider_call_started' || explanation.status === 'unknown_outcome') {
      const knownRejection=/HTTP (401|403)/.test(explanation.error || '');
      addParagraph(ai,explanation.status==='unknown_outcome'
        ?knownRejection?'本机模型凭证或权限未通过验证。请到工作台的“模型设置”更新配置，再提出一个新问题。'
          :`模型请求结果未知：${explanation.error || '未收到可确认的回答'}。本任务不会自动重试。`
        :'模型正在处理；刷新后可查看任务状态。');
    } else if(explanation.parsed) {
      addParagraph(ai,explanation.review?.eligible_for_export?'以下解释已逐项核对。':'以下为模型原始解释，尚未逐项审阅。');
      const entries=[...(explanation.parsed.interpretations||[]).map((v,i)=>({kind:'interpretation',index:i,text:v.text})),
        ...(explanation.parsed.policy_explanations||[]).map((v,i)=>({kind:'policy_explanation',index:i,text:v.text})),
        ...(explanation.parsed.watchlist||[]).map((v,i)=>({kind:'watchlist',index:i,text:v.rationale}))];
      for(const entry of entries){const line=make('label',undefined,'review-item');
        const check=document.createElement('input');check.type='checkbox';check.dataset.kind=entry.kind;
        check.dataset.index=String(entry.index);line.append(check,document.createTextNode(entry.text || '（空解释）'));ai.append(line);}
      if(!explanation.review?.eligible_for_export && entries.length){const review=make('button','核对并采纳勾选的解释','button primary');
        review.addEventListener('click',async()=>{
          review.disabled=true;
          try {
            const decisions=[...ai.querySelectorAll('input[type=checkbox]')].map(c=>({kind:c.dataset.kind,
              index:Number(c.dataset.index),verdict:c.checked?'accept':'reject',
              reason:c.checked?'已对照上方程序数据核对':'暂不采纳'}));
            if(!decisions.some(d=>d.kind==='interpretation'&&d.verdict==='accept'))throw Error('至少勾选一条已核对的解释');
            const result=await api('/api/session/task/explanation/review',{
              session_id:flow.sessionId,task_id:flow.taskId,reviewer:'local-user',facts_checked:true,decisions});
            showProgram(result.session);setStatus('审阅记录已保存。');
          }catch(error){setStatus(error.message);review.disabled=false;}
        });ai.append(review);}
    } else if(explanation.status==='failed') {
      const code=explanation.error_details?.http_status;
      const hint=code===400||code===422?'模型请求参数被拒绝，请检查型号和推理设置。':
        code===401||code===403?'模型凭证或权限未通过验证。':
        code===404?'模型 ID 或接口不存在。':
        code===429?'请求受到限流或额度限制。':'模型回答未通过校验。';
      addParagraph(ai,`${hint} 本次未得到可用的模型解释。`);
    }
    else addParagraph(ai,'已生成数据报告；模型解释尚未运行。');
    if(explanation.status==='ready_for_provider') {
      const call=make('button','试用模型解读','button primary');
      call.addEventListener('click',async()=>{
        call.disabled=true;setStatus('模型正在解释报告，请等待当前请求完成。');
        try {const result=await api('/api/session/task/explanation/call',{
          session_id:flow.sessionId,task_id:flow.taskId});
          showProgram(result.session);setStatus(result.status==='failed'?`解释未通过校验：${result.message}`:'模型回答已保存，请逐项核对。');
        }catch(error){
          try {
            const saved=await api(`/api/session?session_id=${encodeURIComponent(flow.sessionId)}`);
            showProgram(saved);
          } catch (_) {
            // Keep the button disabled when the outcome cannot be checked.
          }
          setStatus(error.message);
        }
      });ai.append(call);
    }
    report.append(ai);
    const refs=make('details',undefined,'live-section');refs.append(make('summary','查看政策和数据来源'));
    const sources=evidence.sources || [];
    addParagraph(refs,`本次证据包记录 ${sources.length} 项来源。以下为已登记的来源地址。`);
    for(const source of sources.filter(s=>typeof s?.url==='string'&&s.url.startsWith('https://')).slice(0,20)) {
      const link=make('a',source.url);link.href=source.url;link.target='_blank';link.rel='noopener';refs.append(link,make('br'));
    }
    const full=make('details');full.append(make('summary','查看程序生成的完整报告'));
    full.append(make('pre',response.markdown||''));refs.append(full);
    report.append(refs);setReportMode(true);if(navigate)location.hash='report';
  }
  function showProposal(proposal) {
    flow.proposal=proposal;const scope=$('scope-preview');scope.replaceChildren();scope.hidden=false;
    scope.append(make('h2','请确认这次报告的范围'));
    addParagraph(scope,`问题：${proposal.question}`);
    addParagraph(scope,`商品：${(proposal.product_cards||[]).map(c=>`${c.name||c.hts8}（${c.hts8}）`).join('、')}`);
    const window=proposal.request?.window || {};
    addParagraph(scope,`本次使用 ${window.start || '未知'} 至 ${window.end || '未知'} 的已发布数据。`);
    addParagraph(scope,'确认后会查询已发布的数据。模型调用会在下一步单独开始。');
    const confirm=make('button','确认范围，生成数据报告','button primary');
    confirm.addEventListener('click',async()=>{
      confirm.disabled=true;setStatus('正在查询数据并生成报告……');
      try {
        const confirmed=await api('/api/session/confirm-proposal',{
          session_id:flow.sessionId,proposal_id:proposal.proposal_id});
        const started=await api('/api/session/task/start',{
          session_id:flow.sessionId,prompt_digest:proposal.request.original_question,request:proposal.request});
        flow.taskId=started.task_id;
        if(!['create','reuse'].includes(started.status))throw Error(started.reason||'这个问题已有进行中的任务');
        await api('/api/session/task/evidence',{session_id:flow.sessionId,task_id:flow.taskId});
        const generated=await api('/api/session/task/generate',{session_id:flow.sessionId,task_id:flow.taskId});
        showProgram(generated.session);
        const prepared=await api('/api/session/task/explanation/prepare',{
          session_id:flow.sessionId,task_id:flow.taskId,mode:'trade'});
        showProgram(prepared.session);
        setStatus('数据报告已生成。你可以先查看数字，再决定是否调用模型。');
      }catch(error){setStatus(error.message);confirm.disabled=false;}
    });scope.append(confirm);
  }
  function showDirectionChoice(question,trade){
    flow.directionChoice={question,trade};flow.tradeChoices=null;flow.tradeProposal=null;
    const preview=$('scope-preview');preview.replaceChildren();preview.hidden=false;
    preview.append(make('h2',tr('先确认贸易方向','Choose the trade direction')));
    addParagraph(preview,tr(trade.message,'Choose U.S. imports, exports, or view both separately.'));
    for(const [value,zh,en] of [['import','查看美国进口','View U.S. imports'],
      ['export','查看美国出口','View U.S. exports'],['both','两者分别看','View both separately']]){
      const choose=make('button',tr(zh,en),'button '+(value==='import'?'primary':'outline'));
      choose.addEventListener('click',async()=>{
        choose.disabled=true;
        try {const selected=await api('/api/trade/prepare',{question,selected_flow:value});
          if(selected.status==='needs_product_choice'){
            showProductChoices(selected);setStatus(tr('请先核对商品范围。','Check the product scope first.'));return;}
          if(selected.status!=='ready')throw Error(selected.message);
          showTradeProposal(selected);setStatus(tr('请核对商品、方向和月份。','Check the product, direction and months.'));
        }catch(error){setStatus(error.message);choose.disabled=false;}
      });preview.append(choose);
    }
    setStatus(tr('请先选进口、出口或两者。','Choose imports, exports, or both.'));
  }
  $('question-form').addEventListener('submit',async event=>{
    event.preventDefault();const question=$('question').value.trim();
    if(!question){setStatus(tr('先输入一个问题。','Enter a question first.'));return;}
    const button=$('question-form').querySelector('button[type=submit]');button.disabled=true;
    try {
      const trade=await api('/api/trade/prepare',{question});
      if(trade.status==='ready'){
        showTradeProposal(trade);setStatus(tr('请核对商品、方向和月份。','Check the product, direction and months.'));
        $('scope-preview').scrollIntoView({block:'center',behavior:'smooth'});return;
      }
      if(trade.status==='needs_product_choice'){
        showProductChoices(trade);setStatus(tr('请选择与问题相符的商品范围。','Choose the product scope that matches your question.'));return;
      }
      if(trade.status==='needs_direction'){
        showDirectionChoice(question,trade);return;
      }
      if(trade.status!=='needs_product'){
        $('scope-preview').replaceChildren();$('scope-preview').hidden=true;
        setStatus(english()?'This request is not available yet. Please check the product and date range.':trade.message||'当前问题尚未开放查询。');return;
      }
      // The policy-case flow may only be considered when the user actually
      // asks about a policy. A commodity lookup that the trade parser cannot
      // resolve must not fall through to the stored tungsten/solar example.
      if(!/(关税|政策|301|清单|税率|征税|公告|tariff|policy|list\s*\d)/i.test(question)){
        $('scope-preview').replaceChildren();$('scope-preview').hidden=true;
        setStatus(english()?'This product name could not be matched safely. Add a specific product code.':
          trade.message||'这个商品名称暂时无法识别，请补充具体商品编码。');return;
      }
      const scope=await api('/api/product/scope',{question});
      if(scope.status!=='supported_case'){
        $('scope-preview').replaceChildren();$('scope-preview').hidden=true;
        setStatus(scope.message||'当前问题尚未开放查询。');return;
      }
      const created=await api('/api/session/create',{});
      flow.sessionId=created.session.session_id;
      localStorage.setItem('tradeintel_live_session',flow.sessionId);
      const proposal=await api('/api/session/proposal',{
        session_id:flow.sessionId,original_question:question,
        policy_id:scope.policy_id,selected_products:scope.selected_products});
      showProposal(proposal);setStatus('请核对商品和月份，再生成数据报告。');
      $('scope-preview').scrollIntoView({block:'center',behavior:'smooth'});
    }catch(error){setStatus(error.message);}finally{button.disabled=false;}
  });
  addEventListener('tradeintel:language',()=>{
    localizeSettings();
    const reviewSelections=[...report.querySelectorAll('.review-draft input[type=checkbox]')]
      .map(input=>input.checked);
    const factsChecked=$('trade-facts-checked')?.checked||false;
    const restoreReviewSelections=()=>{
      [...report.querySelectorAll('.review-draft input[type=checkbox]')]
        .forEach((input,index)=>{input.checked=reviewSelections[index]||false;});
      const facts=$('trade-facts-checked');if(facts)facts.checked=factsChecked;
    };
    if(location.hash==='#report'&&flow.tradeReport){
      showTradeReport(flow.tradeReport,{navigate:false});
      restoreReviewSelections();
      setStatus(tr('报告已切换语言；数据与审阅状态没有改变。',
        'Report language changed; data and review status are unchanged.'));
    }else if(flow.tradeProposal){
      showTradeProposal(flow.tradeProposal);
      setStatus(tr('请核对商品、方向和月份。','Check the product, direction and months.'));
    }else if(flow.tradeChoices){
      showProductChoices(flow.tradeChoices);
      setStatus(tr('请选择与问题相符的商品范围。','Choose the product scope that matches your question.'));
    }else if(flow.directionChoice){
      showDirectionChoice(flow.directionChoice.question,flow.directionChoice.trade);
    }else if(flow.tradeReport){
      showTradeReport(flow.tradeReport,{navigate:false});
      restoreReviewSelections();
      setStatus(tr('可以继续查询新问题；上次报告保留在报告页。',
        'You can ask another question; the previous report remains under Report.'));
    }
  });
  api('/api/model/status').then(info=>{
    modelOptions=info.models||modelOptions;
    if(info.provider)provider.value=info.provider;
    modelName.value=info.model||'';optionsForProvider();
    if(info.model){modelName.value=info.model;
      preset.value=(modelOptions[provider.value]||[]).includes(info.model)?info.model:'custom';}
    if(info.reasoning&&provider.value==='deepseek')reasoning.value=info.reasoning;
    const modelStatus=info.configured?
      tr(`已保存 ${info.model}；${info.connection==='connected'?'短请求曾连通，完整报告尚需验收。':'连接尚未确认，请到“模型设置”测试。'}`,
        `Saved ${info.model}; ${info.connection==='connected'?'a short connection test succeeded, but a full report still needs validation.':'connection not confirmed. Use “Model settings” to test it.'}`):
      tr('本地服务尚未配置模型，仍可生成数据报告。',
        'No model is configured for this local service; data reports are still available.');
    status.textContent=modelStatus;
    if(report.hidden)reportStatus.textContent=modelStatus;
  })
    .catch(()=>{status.textContent=tr('无法读取本地模型状态。','Could not read local model status.');});
  let lastReportType='';
  try {lastReportType=localStorage.getItem('tradeintel_last_report_type')||'';} catch (_) {}
  const announcementIdMatch=(location.search||'').match(/[?&]announcement_report_id=([^&]+)/);
  const announcementReportId=announcementIdMatch?decodeURIComponent(announcementIdMatch[1].replace(/\+/g,' ')):null;
  if(announcementReportId){
    api(`/api/trade/report-state?report_id=${encodeURIComponent(announcementReportId)}`)
      .then(saved=>showTradeReport(saved,{navigate:false}))
      .catch(error=>setStatus(error.message||tr('报告无法读取。','The report could not be loaded.')));
  }else if(lastReportType==='trade'){
    const savedId=localStorage.getItem('tradeintel_live_trade_report_id');
    if(savedId)api(`/api/trade/report-state?report_id=${encodeURIComponent(savedId)}`)
      .then(saved=>showTradeReport(saved,{navigate:false}))
      .catch(()=>{status.textContent=tr('上次报告无法从本机记录恢复，请重新提问。',
        'The previous report could not be restored. Please ask the question again.');});
    else try {const saved=JSON.parse(localStorage.getItem('tradeintel_live_trade_report')||'null');
      if(['trade-query-v1','trade-query-both-v1'].includes(saved?.kind))showTradeReport(saved,{navigate:false});
    } catch (_) {}
  } else if(flow.sessionId) api(`/api/session?session_id=${encodeURIComponent(flow.sessionId)}`)
    .then(session=>{if(latest(session)?.response)showProgram(session,{navigate:false});})
    .catch(()=>{});
}
