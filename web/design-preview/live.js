// The real product flow is available only when this page is served by web_app.
if (document.documentElement?.dataset?.runtime === 'local' &&
    ['/preview/', '/preview/index.html'].includes(location.pathname)) {
  const english=()=>document.documentElement?.lang==='en';
  const tr=(zh,en)=>english()?en:zh;
  const setCopy=(selector,zh,en)=>{const element=document.querySelector(selector);
    if(element){element.textContent=tr(zh,en);element.dataset.en=en;}};
  setCopy('#home .section-heading > p','用商品名称或编码提问，助手查找数据并返回报告；范围不明确时会先询问。',
    'Ask about a product by name or code. The assistant finds available data and returns a report, asking for clarification when needed.');
  setCopy('#home .flow article:nth-of-type(2) h3','核对查询范围','Check the scope');
  setCopy('#home .flow article:nth-of-type(2) p',
    '助手核对商品与月份；有歧义时再请你确认。',
    'The assistant checks products and dates, asking you only when the scope is ambiguous.');
  setCopy('.hero-note','已收录数据截至2026年7月。查看案例不调用模型；使用助手提问可能产生服务商费用。',
    'Data is available through July 2026. Browsing examples makes no model request; assistant questions may incur provider charges.');
  setCopy('#workspace .composer .eyebrow','本地工作台','Local workspace');
  setCopy('#chat-empty > p:not(.eyebrow)',
    '用商品名称或编码提问，例如“最近美国大豆出口怎么样？”。配置模型后可以在同一对话里追问。',
    'Ask about a product by name or code. Configure a model to use the assistant and continue with follow-up questions.');
  setCopy('#question-form .compose-bottom > span','数据查询不调用模型；使用助手会请求你配置的服务商，可能收费。',
    'Data-only queries make no model request. Assistant questions use your configured provider and may incur charges.');
  setCopy('#question-form button[type=submit]','发送','Send');
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
  const linkedAgentSession=(location.search||'').match(/(?:[?&])agent_session_id=([0-9a-f]{32})(?:&|$)/)?.[1]||'';
  const flow = {sessionId: localStorage.getItem('tradeintel_live_session') || '', proposal: null,
    tradeProposal: null, tradeChoices: null, tradeReport: null, directionChoice: null, taskId: null,
    agentSessionId: linkedAgentSession || localStorage.getItem('tradeintel_agent_session') || '', agentTurn: null,
    agentState: null};
  let restoredReportSelection=null;
  try{const selected=JSON.parse(localStorage.getItem('tradeintel_active_report')||'null');
    if(['local','legacy_sample'].includes(selected?.origin)&&
      (selected.id===null||typeof selected.id==='string'))restoredReportSelection=selected;
  }catch(_){}
  let activeReport=restoredReportSelection||{origin:'local',id:null};
  function selectReport(origin,id){if(window.tradeintelCaseActive)return;activeReport={origin,id};
    localStorage.setItem('tradeintel_active_report',JSON.stringify(activeReport));}
  const chat=$('chat-messages');
  const scroll=$('conversation-scroll');
  const drafts=new Map();
  const draftKey=()=>`${mode.value}:${flow.agentSessionId||'new'}`;
  const modeButtons=[];
  const savedReports=new Map();
  $('scope-preview').replaceChildren();$('scope-preview').hidden=true;
  const status = make('p', '', 'live-status');
  status.setAttribute('role', 'status');
  $('question-form').after(status);
  const modeLabel=make('label',tr('查询方式：','Query mode: '),'agent-mode');
  const mode=make('select');mode.setAttribute('aria-label',tr('查询方式','Query mode'));
  for(const [value,zh,en] of [['agent','研究助手（使用模型）','Research assistant (uses model)'],
    ['data','仅查询数据（不使用模型）','Data only (no model)']]){
    const option=make('option',tr(zh,en));option.value=value;option.dataset.zh=zh;option.dataset.en=en;
    mode.append(option);
  }
  // A new local installation has no model key. Start safely with data-only
  // search; honour an explicit choice saved by the user.
  mode.value=localStorage.getItem('tradeintel_query_mode')==='agent'?'agent':'data';
  const updateModeHelp=()=>setCopy('#question-form .compose-bottom > span',
    mode.value==='agent'?'数据查询不调用模型；使用助手会请求你配置的服务商，可能收费。':'此模式不调用模型；核对商品和月份后生成数据报告。',
    mode.value==='agent'?'Data-only queries make no model request. Assistant questions use your configured provider and may incur charges.':'This mode does not call a model. Check the product and dates before generating the data report.');
  updateModeHelp();
  function selectMode(){
    localStorage.setItem('tradeintel_query_mode',mode.value);
    updateModeHelp();
    syncMode();
    setStatus(mode.value==='agent'?tr('提问后助手会调用已配置模型。','Asking will call the configured model.'):
      tr('仅查询数据，不调用模型。','Data-only mode does not call the model.'));
  }
  mode.addEventListener('change',selectMode);
  mode.hidden=true;
  modeLabel.textContent='';modeLabel.append(mode);
  for(const [value,zh,en] of [['agent','研究助手','Assistant'],['data','数据查询','Data']]){
    const button=make('button',tr(zh,en),'mode-tab');button.type='button';
    button.dataset.mode=value;button.dataset.zh=zh;button.dataset.en=en;
    button.addEventListener('click',()=>{
      drafts.set(draftKey(),$('question').value);mode.value=value;
      $('question').value=drafts.get(draftKey())||'';selectMode();
    });modeButtons.push(button);modeLabel.append(button);
  }
  ($('workspace-mode')||status).append(modeLabel);
  function syncMode(){
    for(const button of modeButtons){button.textContent=tr(button.dataset.zh,button.dataset.en);
      button.setAttribute('aria-pressed',String(button.dataset.mode===mode.value));}
    chat.hidden=mode.value!=='agent';
    $('scope-preview').hidden=mode.value==='agent'||!$('scope-preview').textContent.trim();
    const submit=$('question-form').querySelector('button[type=submit]');
    submit.textContent=mode.value==='agent'?tr('发送','Send'):tr('查询','Query');
    if($('chat-empty'))$('chat-empty').hidden=mode.value==='agent'&&Boolean(flow.agentState?.turns?.length);
  }
  const newConversation=$('new-conversation')||make('button',tr('新对话','New conversation'),'button outline');
  newConversation.type='button';
  newConversation.addEventListener('click',async()=>{
    const pending=localStorage.getItem('tradeintel_agent_pending');
    if(pending){
      try{const saved=JSON.parse(pending);const previous=await api(`/api/trade/agent/state?session_id=${encodeURIComponent(saved.session_id||saved.request_id)}`);
        if(!previous?.turns?.length||previous.turns.at(-1).status==='in_progress'){
          setStatus(tr('上一轮结果尚未确认，请先等待；新对话不会取消它。','The previous result is unconfirmed. Starting a new conversation would not cancel it.'));return;
        }
        localStorage.removeItem('tradeintel_agent_pending');
      }catch(_){setStatus(tr('无法确认上一轮状态，暂不开始新对话。','Cannot confirm the previous request; a new conversation has not been started.'));return;}
    }
    drafts.set(draftKey(),$('question').value);
    localStorage.removeItem('tradeintel_agent_session');
    flow.agentSessionId='';flow.agentTurn=null;flow.agentState=null;
    chat.replaceChildren();$('question').value=drafts.get(draftKey())||'';
    if($('conversation-title'))$('conversation-title').textContent=tr('新对话','New conversation');
    syncMode();
    setStatus(tr('已开始新对话。已有报告仍可查看；新问题会建立独立会话。',
      'New conversation started. Saved reports remain available; the next question starts a separate session.'));
  });
  if(!$('new-conversation'))modeLabel.after(newConversation);
  const settings=make('dialog',undefined,'model-settings');settings.id='model-settings-dialog';
  const settingsTitle=make('h2',tr('模型设置','Model settings'));settingsTitle.id='model-settings-title';
  settings.setAttribute('aria-labelledby',settingsTitle.id);
  const closeSettings=make('button',tr('关闭','Close'),'dialog-close');closeSettings.type='button';
  const openSettings=()=>{if(!settings.open)settings.showModal();};
  const closeModelSettings=()=>{secret.value='';settings.close();};
  closeSettings.addEventListener('click',closeModelSettings);
  for(const id of ['open-model-settings','model-status-button'])$(id)?.addEventListener('click',openSettings);
  settings.addEventListener('close',()=>{secret.value='';});
  settings.append(settingsTitle,closeSettings);
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
  saveButton.type='submit';
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
    modelField.hidden=preset.value!=='custom';
    reasoning.disabled=provider.value!=='deepseek';if(reasoning.disabled)reasoning.value='default';
  }
  provider.addEventListener('change',()=>{modelName.value='';optionsForProvider();});
  preset.addEventListener('change',()=>{if(preset.value!=='custom')modelName.value=preset.value;
    modelField.hidden=preset.value!=='custom';});
  modelName.addEventListener('input',()=>{preset.value=(modelOptions[provider.value]||[]).includes(modelName.value)?modelName.value:'custom';});
  const fieldLabels=[];
  function field(control,zh,en){const label=make('label',undefined,'model-field');
    const title=make('span',tr(zh,en));fieldLabels.push({title,zh,en});label.append(title,control);return label;}
  const modelField=field(modelName,'型号 ID','Model ID');
  settingsForm.append(field(provider,'服务商','Provider'),field(preset,'型号','Model'),modelField,
    field(reasoning,'推理配置','Reasoning'),field(secret,'API Key','API key'));
  const settingsActions=make('div',undefined,'settings-actions');settingsActions.append(saveButton,testButton);
  settingsForm.append(settingsActions);
  const settingsHint=make('p',tr('密钥由本地服务保存，不发布到展示网站。更换服务商需要新密钥；测试连接会发送一个短请求，也可能收费。',
    'The local server stores your key; it is not published with the showcase. Changing providers requires a new key. A connection test sends a short request and may incur provider charges.'),'muted');
  settings.append(settingsForm,settingsHint);
  function localizeSettings(){
    settingsTitle.textContent=tr('模型设置','Model settings');closeSettings.textContent=tr('关闭','Close');
    for(const label of fieldLabels)label.title.textContent=tr(label.zh,label.en);
    provider.setAttribute('aria-label',tr('模型服务','Model provider'));
    for(const option of provider.options)option.textContent=english()?option.dataset.en:option.dataset.zh;
    preset.setAttribute('aria-label',tr('常用型号','Model preset'));
    reasoning.setAttribute('aria-label',tr('推理档位','Reasoning level'));
    for(const option of reasoning.options)option.textContent=english()?option.dataset.en:option.dataset.zh;
    const custom=[...preset.options].find(option=>option.value==='custom');
    if(custom)custom.textContent=tr('手动填写型号','Enter a model ID');
    secret.placeholder=tr('新的 API Key','New API key');secret.setAttribute('aria-label',secret.placeholder);
    saveButton.textContent=tr('保存设置','Save settings');testButton.textContent=tr('测试连接','Test connection');
    settingsHint.textContent=tr('密钥由本地服务保存，不发布到展示网站。更换服务商需要新密钥；测试连接会发送一个短请求，也可能收费。',
      'The local server stores your key; it is not published with the showcase. Changing providers requires a new key. A connection test sends a short request and may incur provider charges.');
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
  const setReportMode = show => {if(window.tradeintelCaseActive){report.hidden=true;return;}
    liveVisible = show; report.hidden = !show; staticReport.hidden = show;
    const caseReport=$('case-result');if(caseReport)caseReport.hidden=true;};
  addEventListener('tradeintel:case-report',()=>{report.hidden=true;});
  addEventListener('tradeintel:return-local',()=>{
    if(flow.agentSessionId)api(`/api/trade/agent/state?session_id=${encodeURIComponent(flow.agentSessionId)}`)
      .then(state=>showAgentState(state,{navigate:false})).catch(()=>setStatus(tr('会话暂时无法读取。','The conversation is unavailable.')));
    else if(flow.tradeReport)showTradeReport(flow.tradeReport,{navigate:false,agentTurn:flow.agentTurn});
  });
  addEventListener('hashchange', () => setReportMode(liveVisible));
  document.querySelectorAll?.('[data-example-report]').forEach(link=>link.addEventListener('click',()=>{
    selectReport('legacy_sample','policy-materials');
    window.tradeintelLiveReportTitle='';setReportMode(false);
  }));
  $('return-to-conversation')?.addEventListener('click',()=>{
    if(flow.agentState&&mode.value==='agent')showAgentConversation(flow.agentState);
  });
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
      await refreshModelStatus();
      setStatus(tr(`已保存 ${result.model}；请点“测试连接”确认能否调用。`,
        `Saved ${result.model}. Use “Test connection” to check access.`));
    }catch(error){setStatus(error.message);}finally{saveButton.disabled=false;}
  });
  testButton.addEventListener('click',async()=>{
    testButton.disabled=true;setStatus(tr('正在测试模型连接……','Testing the model connection…'));
    try {const result=await api('/api/model/test',{});
      await refreshModelStatus();
      setStatus(`${english()?(result.status==='connected'?'Connection successful. You can now ask the assistant.':`Provider response: ${result.message}`):result.message}${result.provider_code?tr(` 错误码：${result.provider_code}。`,` Code: ${result.provider_code}.`):''}${result.provider_param?tr(` 参数：${result.provider_param}。`,` Parameter: ${result.provider_param}.`):''}`);
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
  function loadSavedReport(id){
    if(!savedReports.has(id))savedReports.set(id,api(`/api/trade/report-state?report_id=${encodeURIComponent(id)}`).catch(error=>{
      savedReports.delete(id);throw error;
    }));
    return savedReports.get(id);
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
      `${latest.month}: observed values sum to ${fmt(latest.observed_value_usd)} USD; detailed codes are complete for ${latest.complete_codes} of ${latest.selected_codes} products. This does not measure imports covered by the policy.`));
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
          'This broader product group includes goods outside the notice. Values are not shown for months with incomplete detailed codes.'):
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
      tr('本卡保存已确认的公告字段及原文引文。',
        'This card preserves confirmed notice fields and source quotations.'):
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
  function showTradeReport(result, {navigate=true,agentTurn=null}={}) {
    if(window.tradeintelCaseActive)return;
    selectReport('local',result?.report_id||null);
    if(result?.kind==='announcement-statistics-report-v1')return showAnnouncementStatisticsReport(result,{navigate});
    if(result?.kind==='announcement-context-report-v1')return showAnnouncementContextReport(result,{navigate});
    if(!['trade-query-v1','trade-query-both-v1'].includes(result?.kind)||!result.scope)return;
    if(result.kind==='trade-query-v1'&&!Array.isArray(result.series))return;
    flow.tradeReport=result;flow.tradeProposal=null;flow.tradeChoices=null;flow.directionChoice=null;
    report.replaceChildren();report.append(reportStatus);
    const scope=result.scope;
    const title=scope.flow==='both'?'进出口':scope.flow==='export'?'出口':'进口';
    const englishDirection=scope.flow==='both'?'imports and exports':scope.flow==='export'?'exports':'imports';
    window.tradeintelLiveReportTitle=tr(result.question||`美国${scope.product_code}${title}情况`,
      `U.S. ${englishDirection} · ${scope.official_product_en||`product group ${scope.product_code}`}`);
    if(navigate||location.hash==='#report')document.title=`${window.tradeintelLiveReportTitle} · TradeIntel`;
    try {localStorage.setItem('tradeintel_live_trade_report',JSON.stringify(result));
      if(result.report_id)localStorage.setItem('tradeintel_live_trade_report_id',result.report_id);
      localStorage.setItem('tradeintel_last_report_type','trade');} catch (_) {}
    const reader=agentTurn?.reader_view?.schema==='trade-reader-view-v1'?agentTurn.reader_view:null;
    window.tradeintelLiveReportTitle=globalThis.TradeIntelReportView.renderTradeReport(report,result,{language:english()?'en':'zh',readerView:reader});
    if(navigate||location.hash==='#report')document.title=`${window.tradeintelLiveReportTitle} · TradeIntel`;
    const agentProgramSummary=agentTurn?.message_kind==='program_summary_v1';
    const ai=make('section',undefined,'live-section');ai.append(make('h2',
      agentTurn?tr('运行记录','Execution record'):
        tr('模型解读（试用）','Model explanation (trial)')));
    const explanation=result.explanation||{status:'not_requested'};
    const aiStatus=explanation.status||'not_requested';
    if(aiStatus!=='reviewed'&&!agentTurn)ai.className+=' print-exclude';
    if(agentTurn){
      ai.className+=' print-exclude';
      if(agentTurn.execution_metrics){
        const metrics=agentTurn.execution_metrics;
        const detail=make('details');detail.append(make('summary',tr('调用详情','Execution details')));
        addParagraph(detail,tr(`模型调用尝试 ${metrics.complete_attempts??'未知'} 次，收到 ${metrics.responses_received??'未知'} 次响应；费用未知。`,
          `Model attempts: ${metrics.complete_attempts??'unknown'}; responses received: ${metrics.responses_received??'unknown'}. Cost is unknown.`));
        const total=metrics.token_totals?.total_tokens;
        addParagraph(detail,total?.reported_sum==null?tr('供应商未返回总 token 用量。','The provider did not report total token usage.'):
          tr(`供应商已报告的总 token 合计 ${total.reported_sum}，覆盖 ${total.reporting_responses} 次响应。`,
            `Provider-reported total tokens: ${total.reported_sum}, covering ${total.reporting_responses} responses.`));
        ai.append(detail);
      }
      if(!agentProgramSummary){const legacy=make('details');legacy.append(
        make('summary',tr('历史回答状态','Legacy response status')),
        make('p',tr('此记录的模型文字尚未审阅，报告展示已保存的查询数据。',
          'The model text in this record has not been reviewed. The report shows the saved query data.')));ai.append(legacy);}
      if(!reader&&agentTurn.policy_sources?.length){const refs=make('details');refs.append(make('summary',
        tr('查看政策原文','View policy sources')));
        for(const item of agentTurn.policy_sources){
          addParagraph(refs,`${item.citation_id}：${item.text||''}`);
          if(typeof item.url==='string'&&item.url.startsWith('https://')){
            const link=make('a',item.url);link.href=item.url;link.target='_blank';link.rel='noopener';
            refs.append(link);
          }
        }ai.append(refs);
      }
    } else if(aiStatus==='not_requested'&&explanation.available===false){
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
    const confirm=make('button',tr('确认范围，生成数据报告','Check the scope and generate data report'),'button primary');
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
    addParagraph(summary,tr(`报告包含 ${evidence.observations?.length || 0} 项数据观察。税率、生效时间及限定条件见政策资料与公告原文。`, `The report contains ${evidence.observations?.length || 0} data observations. See the policy documents and notice text for tariffs, effective dates, and conditions.`));
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
  function conversationIndex(){
    try{const rows=JSON.parse(localStorage.getItem('tradeintel_conversation_index')||'[]');
      return Array.isArray(rows)?rows.filter(row=>/^[0-9a-f]{32}$/.test(row?.id)&&typeof row.title==='string').slice(0,20):[];
    }catch(_){return [];}
  }
  function renderHistory(){
    const list=$('conversation-list');if(!list)return;list.replaceChildren();
    for(const entry of conversationIndex()){
      const button=make('button',entry.title,'history-item');button.type='button';
      button.setAttribute('aria-current',String(entry.id===flow.agentSessionId));
      button.addEventListener('click',async()=>{
        try{const state=await api(`/api/trade/agent/state?session_id=${encodeURIComponent(entry.id)}`);
          drafts.set(draftKey(),$('question').value);flow.agentSessionId=entry.id;mode.value='agent';
          $('question').value=drafts.get(draftKey())||'';selectMode();
          await showAgentState(state,{navigate:false});location.hash='workspace';
          $('workspace-sidebar')?.classList?.remove('is-open');
        }catch(_){setStatus(tr('这段对话暂时无法读取，记录没有删除。','This conversation cannot be loaded; its record has not been deleted.'));}
      });list.append(button);
    }
  }
  function rememberConversation(state){
    if(!/^[0-9a-f]{32}$/.test(state.session_id))return;
    const title=(state.turns?.[0]?.question||tr('新对话','New conversation')).slice(0,64);
    const index=[{id:state.session_id,title,updated_at:new Date().toISOString()},
      ...conversationIndex().filter(row=>row.id!==state.session_id)].slice(0,20);
    localStorage.setItem('tradeintel_conversation_index',JSON.stringify(index));
    if($('conversation-title'))$('conversation-title').textContent=title;
    renderHistory();
  }
  renderHistory();
  $('sidebar-toggle')?.addEventListener('click',()=>{
    const sidebar=$('workspace-sidebar');const expanded=sidebar.classList.toggle('is-open');
    $('sidebar-toggle').setAttribute('aria-expanded',String(expanded));
  });
  $('question').addEventListener('input',()=>drafts.set(draftKey(),$('question').value));
  $('question').addEventListener('keydown',event=>{
    if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){
      event.preventDefault();if(!$('question-form').querySelector('button[type=submit]').disabled)$('question-form').requestSubmit();
    }
  });
  function showAgentConversation(state){
    flow.agentSessionId=state.session_id;
    flow.agentState=state;
    localStorage.setItem('tradeintel_agent_session',state.session_id);
    rememberConversation(state);
    const preview=chat;const nearBottom=!scroll||scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<100;
    preview.replaceChildren();preview.hidden=mode.value!=='agent';
    if($('chat-empty'))$('chat-empty').hidden=Boolean(state.turns?.length);
    for(const turn of state.turns||[]){
      const item=make('div',undefined,'agent-turn');
      const user=make('div',undefined,'chat-message user-message');user.append(make('small',tr('你','You')));
      addParagraph(user,turn.question);preview.append(user);
      item.className='agent-turn chat-message assistant-message';
      item.append(make('small',tr('研究助手','Assistant')));
      if(turn.reader_view?.schema==='trade-reader-view-v1'){
        for(const fact of turn.reader_view.facts||[])addParagraph(item,tr(fact.text,fact.text_en));
        for(const missing of turn.reader_view.unanswered||[])addParagraph(item,tr(missing.text,missing.text_en));
      }else if(turn.message)addParagraph(item,english()&&turn.status==='completed'?
        turn.message_en||(turn.message_kind==='program_summary_v1'?
          'The queried data are available in the report. These values alone cannot establish a policy effect.':
          'The saved query data are available in the report.'):turn.message);
      if(turn.report_ids?.length){
        const options=make('div',undefined,'report-cards');
        const records=turn.report_options?.length?turn.report_options:turn.report_ids.map(report_id=>
          ({...state.scope,report_id}));
        for(const option of records){
          const direction=option.flow==='both'?tr('进出口','Imports and exports'):
            option.flow==='export'?tr('出口','Exports'):tr('进口','Imports');
          const partner=option.partner==='CHINA'?tr('中国','China'):
            option.flow==='export'?tr('全部目的地','All destinations'):
              option.flow==='both'?tr('全部来源与目的地','All origins and destinations'):
                tr('全部来源地','All origins');
          const label=`${direction} · ${partner}${option.report_id===(turn.primary_report_id||turn.report_ids[0])?
            tr('（主报告）',' (main report)'):''}`;
          const button=make('button',label,'report-card');button.type='button';
          const subtitle=make('span',`${option.product_label||option.product_code||tr('数据报告','Data report')} · ${option.start_month||''}—${option.end_month||''}`);
          button.append(subtitle);
          loadSavedReport(option.report_id).then(saved=>{
            const scope=saved.scope||{};
            subtitle.textContent=`${english()?(scope.official_product_en||scope.product_code||''):scope.product_label||scope.product_code||''} · ${scope.start_month||''}—${scope.end_month||''}`;
          }).catch(()=>{subtitle.textContent=tr('报告范围暂时无法读取','Report scope could not be loaded');});
          button.addEventListener('click',async()=>{
            try{const saved=await loadSavedReport(option.report_id);
              flow.agentTurn=turn;showTradeReport(saved,{agentTurn:turn});}
            catch(error){setStatus(error.message);}
          });options.append(button);
        }
        item.append(options);
      }
      if(turn.status==='in_progress')addParagraph(item,tr('请求已发出，结果尚未确认；请勿重复提交同一问题。',
        'The request was sent but its outcome is not confirmed. Do not resubmit the same question.'));
      const calls=(turn.tool_calls||[]).filter(call=>call.status==='ok');
      if(calls.length){const details=make('details');details.append(make('summary',
        tr('本次查询步骤','Tools used')));
        addParagraph(details,calls.map(call=>call.tool).join(' → '));item.append(details);}
      preview.append(item);
    }
    if(nearBottom&&scroll)scroll.scrollTop=scroll.scrollHeight;
  }
  async function showAgentState(state,{navigate=false}={}){
    showAgentConversation(state);
    const turn=(state.turns||[]).at(-1);
    if(turn?.status==='completed'&&turn.report_ids?.length){
      const saved=await loadSavedReport(turn.primary_report_id||turn.report_ids.at(-1));
      flow.agentTurn=turn;
      showTradeReport(saved,{navigate,agentTurn:turn});
      setStatus(tr('报告已生成；上方数据摘要由程序根据已发布数据整理。',
        'Report ready. The data summary is generated from published data.'));
    }else if(turn?.status==='needs_clarification'){
      setStatus(turn.message);$('question').focus?.();
    }else if(turn?.status==='failed'||turn?.status==='unknown_outcome'){
      const earlier=[...state.turns].reverse().find(item=>item.status==='completed'&&item.report_ids?.length);
      if(earlier){const saved=await loadSavedReport(earlier.primary_report_id||earlier.report_ids.at(-1));flow.agentTurn=earlier;showTradeReport(saved,{navigate:false,agentTurn:earlier});}
      setStatus(turn.message||tr('本轮未生成报告。','This turn did not produce a report.'));
    }else setStatus(tr('请求结果尚未确认；系统不会自动重试。可先等待或查看已保存的报告。',
      'The request outcome is not confirmed. The system will not retry automatically. You may wait or view saved reports.'));
  }
  async function askAgent(question){
    let pending;
    try{pending=JSON.parse(localStorage.getItem('tradeintel_agent_pending')||'null');}catch(_){pending=null;}
    if(pending&&pending.question!==question){
      try{const previous=await api(`/api/trade/agent/state?session_id=${encodeURIComponent(
        pending.session_id||pending.request_id)}`);
        if(previous.turns?.at(-1)?.status==='in_progress'){
          await showAgentState(previous,{navigate:false});return;
        }
        localStorage.removeItem('tradeintel_agent_pending');
      }catch(_){setStatus(tr('上次请求状态无法确认；请恢复本地服务后再提问，避免重复调用模型。',
        'The previous request status is unknown. Restore the local service before asking again.'));return;}
      pending=null;
    }
    if(!pending){
      pending={question,request_id:crypto.randomUUID().replaceAll('-',''),
        session_id:flow.agentSessionId||null};
      localStorage.setItem('tradeintel_agent_pending',JSON.stringify(pending));
    }
    setStatus(tr('助手正在查商品和数据，模型调用可能产生费用。',
      'The assistant is checking products and data. The model call may incur charges.'));
    try{
      const body={question,request_id:pending.request_id};
      if(pending.session_id)body.session_id=pending.session_id;
      const state=await api('/api/trade/agent/turn',body);
      localStorage.removeItem('tradeintel_agent_pending');
      await showAgentState(state);
    }catch(error){
      try{const state=await api(`/api/trade/agent/state?session_id=${encodeURIComponent(
        pending.session_id||pending.request_id)}`);
        if(state.turns?.at(-1)?.status!=='in_progress')localStorage.removeItem('tradeintel_agent_pending');
        await showAgentState(state,{navigate:false});
      }catch(_){
        if(/模型设置|模型密钥|model/i.test(error.message)){openSettings();
        }
        setStatus(error.message);
      }
    }
  }
  $('question-form').addEventListener('submit',async event=>{
    event.preventDefault();const question=$('question').value.trim();
    if(!question){setStatus(tr('先输入一个问题。','Enter a question first.'));return;}
    const button=$('question-form').querySelector('button[type=submit]');if(button.disabled)return;button.disabled=true;
    try {
      if(mode.value==='agent'){
        const followBottom=!scroll||scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<100;
        const pendingUser=make('div',undefined,'chat-message user-message pending-message');addParagraph(pendingUser,question);
        const waiting=make('p',tr('正在处理…','Working…'),'chat-message assistant-message pending-message');waiting.setAttribute('role','status');
        chat.hidden=false;chat.append(pendingUser,waiting);if($('chat-empty'))$('chat-empty').hidden=true;
        if(followBottom&&scroll)scroll.scrollTop=scroll.scrollHeight;
        await askAgent(question);
        if(waiting.parentNode===chat){waiting.textContent=status.textContent;}
        if(flow.agentState?.turns?.at(-1)?.question===question&&flow.agentState.turns.at(-1).status!=='in_progress'){
          $('question').value='';drafts.set(draftKey(),'');
        }
        return;
      }
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
    setCopy('#home .flow article:nth-of-type(2) h3','核对查询范围','Check the scope');
    setCopy('#home .flow article:nth-of-type(2) p',
      '助手核对商品与月份；有歧义时再请你确认。',
      'The assistant checks products and dates, asking you only when the scope is ambiguous.');
    setCopy('#workspace .composer .eyebrow','本地工作台','Local workspace');
    setCopy('#chat-empty > p:not(.eyebrow)',
      '用商品名称或编码提问，例如“最近美国大豆出口怎么样？”。配置模型后可以在同一对话里追问。',
      'Ask about a product by name or code. Configure a model to use the assistant and continue with follow-up questions.');
    updateModeHelp();
    syncMode();
    if(questionInput)questionInput.placeholder=tr('例如：最近美国大豆出口有什么变化？',
      'For example: How have recent U.S. soybean exports changed?');
    modeLabel.firstChild?.nodeType===3 && (modeLabel.firstChild.textContent=tr('查询方式：','Query mode: '));
    mode.setAttribute('aria-label',tr('查询方式','Query mode'));
    for(const option of mode.options)option.textContent=english()?option.dataset.en:option.dataset.zh;
    newConversation.textContent=tr('新对话','New conversation');
    const reviewSelections=[...report.querySelectorAll('.review-draft input[type=checkbox]')]
      .map(input=>input.checked);
    const factsChecked=$('trade-facts-checked')?.checked||false;
    const restoreReviewSelections=()=>{
      [...report.querySelectorAll('.review-draft input[type=checkbox]')]
        .forEach((input,index)=>{input.checked=reviewSelections[index]||false;});
      const facts=$('trade-facts-checked');if(facts)facts.checked=factsChecked;
    };
    if(location.hash==='#report'&&flow.tradeReport&&activeReport.origin==='local'){
      showTradeReport(flow.tradeReport,{navigate:false,agentTurn:flow.agentTurn});
      restoreReviewSelections();
      setStatus(tr('报告已切换语言；数据与审阅状态没有改变。',
        'Report language changed; data and review status are unchanged.'));
    }else if(mode.value==='data'&&flow.tradeProposal){
      showTradeProposal(flow.tradeProposal);
      setStatus(tr('请核对商品、方向和月份。','Check the product, direction and months.'));
    }else if(mode.value==='data'&&flow.tradeChoices){
      showProductChoices(flow.tradeChoices);
      setStatus(tr('请选择与问题相符的商品范围。','Choose the product scope that matches your question.'));
    }else if(mode.value==='data'&&flow.directionChoice){
      showDirectionChoice(flow.directionChoice.question,flow.directionChoice.trade);
    }else if(flow.tradeReport&&activeReport.origin==='local'){
      showTradeReport(flow.tradeReport,{navigate:false,agentTurn:flow.agentTurn});
      restoreReviewSelections();
      setStatus(tr('可以继续查询新问题；上次报告保留在报告页。',
        'You can ask another question; the previous report remains under Report.'));
    }
    if(flow.agentState&&mode.value==='agent')showAgentConversation(flow.agentState);
    if(modelInfo)renderModelBadge(modelInfo);
  });
  let modelInfo=null;
  function renderModelBadge(info){
    const badge=$('model-status-button');if(!badge)return;
    const connection=info.connection==='connected'?tr('已连通','Connected'):
      ['rejected','unavailable'].includes(info.connection)?tr('连接失败','Connection failed'):tr('未测试','Untested');
    badge.textContent=info.configured?`${info.model} · ${connection}`:tr('配置模型','Set up model');
  }
  async function refreshModelStatus(){const info=await api('/api/model/status');modelInfo=info;renderModelBadge(info);return info;}
  refreshModelStatus().then(info=>{
    if(!['agent','data'].includes(localStorage.getItem('tradeintel_query_mode'))){
      mode.value=info.configured?'agent':'data';
      updateModeHelp();
    }
    modelOptions=info.models||modelOptions;
    if(info.provider)provider.value=info.provider;
    modelName.value=info.model||'';optionsForProvider();
    if(info.model){modelName.value=info.model;
      preset.value=(modelOptions[provider.value]||[]).includes(info.model)?info.model:'custom';}
    modelField.hidden=preset.value!=='custom';
    syncMode();
    if(info.reasoning&&provider.value==='deepseek')reasoning.value=info.reasoning;
    const modelStatus=info.configured?
      tr(`已保存 ${info.model}；${info.connection==='connected'?'连接测试成功（短请求）。':'连接尚未确认，请到“模型设置”测试。'}`,
        `Saved ${info.model}; ${info.connection==='connected'?'connection test succeeded with a short request.':'connection not confirmed. Use “Model settings” to test it.'}`):
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
  if(/(?:[?&])case=/.test(location.search||'')){
    // A case deep link must not restore or rewrite the live report selection.
  }else if(announcementReportId){
    api(`/api/trade/report-state?report_id=${encodeURIComponent(announcementReportId)}`)
      .then(saved=>showTradeReport(saved,{navigate:false}))
      .catch(error=>setStatus(error.message||tr('报告无法读取。','The report could not be loaded.')));
  }else if(location.hash==='#report'&&restoredReportSelection?.origin==='legacy_sample'){
    setReportMode(false);
  }else if(flow.agentSessionId){
    api(`/api/trade/agent/state?session_id=${encodeURIComponent(flow.agentSessionId)}`)
      .then(async state=>{
        if(location.hash==='#report'&&restoredReportSelection?.origin==='legacy_sample'){
          showAgentConversation(state);setReportMode(false);return;
        }
        const selected=location.hash==='#report'&&restoredReportSelection?.origin==='local'?
          state.turns?.find(turn=>turn.report_ids?.includes(restoredReportSelection.id)):null;
        if(selected){showAgentConversation(state);
          flow.agentTurn=selected;showTradeReport(await loadSavedReport(restoredReportSelection.id),{navigate:false,agentTurn:selected});
        }else await showAgentState(state,{navigate:false});
      })
      .catch(()=>{status.textContent=tr('上次助手会话无法恢复，可重新提问。',
        'The previous assistant session could not be restored. You can ask again.');});
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
