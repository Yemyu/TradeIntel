// Offline reload coverage for new array citations and older single-ID answers.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../web/design-preview/report-view.js'), 'utf8') + '\n' +
  fs.readFileSync(path.join(__dirname, '../web/design-preview/live.js'), 'utf8');

function node(tag = 'div') {
  const value = {
    tag, children: [], attrs: {}, dataset: {}, style: {}, listeners: {},
    hidden: false, disabled: false, value: '', href: '', text: '',
    append(...items) { for (const item of items) item.parentNode = this; this.children.push(...items); },
    appendChild(item) { item.parentNode = this; this.children.push(item); },
    replaceChildren(...items) { for (const item of items) item.parentNode = this; this.children = items; },
    setAttribute(key, item) { this.attrs[key] = item; },
    addEventListener(name, handler) { this.listeners[name] = handler; },
    after() {}, before() {}, scrollIntoView() {},
    showModal() { this.open=true; }, close() { this.open=false; this.listeners.close?.(); },
    querySelector(selector) {
      if (this.id === 'report' && selector === '.report-layout') return this.layout;
      if (selector === 'button[type=submit]') return this.submitButton;
      return node();
    },
    querySelectorAll(selector) {
      const matches = [];
      const visit = (parent, insideDraft = false) => {
        for (const child of parent.children || []) {
          const inDraft = insideDraft || String(child.className || '').split(/\s+/).includes('review-draft');
          if (selector === 'details:not([open])' && child.tag === 'details' && !child.open) matches.push(child);
          if (child.tag === 'input' && child.type === 'checkbox' &&
              (selector === 'input[type=checkbox]' ||
               (selector === '.review-draft input[type=checkbox]' && inDraft))) matches.push(child);
          visit(child, inDraft);
        }
      };
      visit(this);
      return matches;
    },
    get textContent() {
      return this.text + this.children.map(item => item?.textContent ?? item?.text ?? '').join('');
    },
    set textContent(text) { this.text = String(text); this.children = []; },
    get options() { return this.children.filter(item => item.tag === 'option'); },
  };
  return value;
}

test('printing opens supporting tables and restores the screen view', async () => {
  const record = {
    kind: 'trade-query-v1', question: '最近美国小麦出口有什么变化',
    scope: {flow: 'export', product_label: '小麦', product_code: '1001', partner: 'ALL',
      start_month: '2026-06', end_month: '2026-07'},
    summary: {latest_month: '2026-07', latest_value_usd: 20, previous_month: '2026-06',
      month_change_usd: 10, period_total_usd: 30},
    series: [{month: '2026-06', status: 'observed', value_usd: 10},
      {month: '2026-07', status: 'observed', value_usd: 20}],
    observations: [], notes: [], sources: [], explanation: {status: 'needs_review'},
  };
  const env = makeEnv(record);
  vm.runInContext(script, env.context);
  await new Promise(resolve => setImmediate(resolve));
  const details = env.report().querySelectorAll('details:not([open])');
  assert.equal(details.length, 2);
  assert.ok(details.every(item => !item.open));
  env.events.beforeprint();
  assert.ok(details.every(item => item.open));
  env.events.afterprint();
  assert.ok(details.every(item => !item.open));
  assert.ok(env.created.some(item => String(item.className).includes('print-exclude')));
});

function makeEnv(reportState, agentState = null) {
  const ids = new Map();
  const created = [];
  const events = {};
  const homeNote = node('p');
  const questionForm = node('form');
  questionForm.submitButton = node('button');
  const question = node('textarea');
  const scope = node('section');
  const report = node('section');
  report.id = 'report';
  report.layout = node('div');
  ids.set('question-form', questionForm);
  ids.set('question', question);
  ids.set('scope-preview', scope);
  ids.set('report', report);
  for(const id of ['chat-messages','chat-empty','conversation-scroll','conversation-title',
    'workspace-mode','conversation-list','new-conversation','open-model-settings','model-status-button',
    'return-to-conversation']){const element=node();element.id=id;ids.set(id,element);}
  const storage = {
    tradeintel_last_report_type: 'trade',
    tradeintel_live_trade_report_id: 'report-1',
    tradeintel_query_mode: 'data',
    tradeintel_agent_session: agentState?.session_id || '',
    getItem(key) { return this[key] || ''; },
    setItem(key, value) { this[key] = value; },
    removeItem(key) { delete this[key]; },
  };
  const context = vm.createContext({
    location: {pathname: '/preview/', hash: ''},
    localStorage: storage,
    window: {location: {pathname: '/preview/', search: '', hash: ''}, localStorage: storage},
    document: {
      title: '', documentElement: {lang: 'zh-CN', dataset: {runtime: 'local'}},
      getElementById(id) { return ids.get(id); },
      querySelector() { return homeNote; },
      createElement: tag => { const createdNode = node(tag); created.push(createdNode); return createdNode; },
      createTextNode: text => Object.assign(node('#text'), {text: String(text)}),
    },
    addEventListener(name, handler) { events[name] = handler; },
    fetch: async url => ({
      ok: true,
      json: async () => url.startsWith('/api/model/status')
        ? {configured: false, models: {}}
        : url.startsWith('/api/trade/agent/state') ? agentState : reportState,
    }),
  });
  return {context, report: () => created.find(item => item.id === 'live-result'), ids, created, events};
}

test('first visit without a configured model starts in data-only mode', async () => {
  const env=makeEnv({});
  delete env.context.localStorage.tradeintel_query_mode;
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  const mode=env.created.find(item=>item.tag==='select'&&item.attrs['aria-label']==='查询方式');
  assert.equal(mode.value,'data');
  assert.equal(env.context.localStorage.getItem('tradeintel_query_mode'),'');
});

test('a configured model is offered on first visit but an explicit data choice stays', async () => {
  const first=makeEnv({});
  delete first.context.localStorage.tradeintel_query_mode;
  first.context.fetch=async url=>({ok:true,json:async()=>
    url==='/api/model/status'?{configured:true,model:'deepseek-flash',models:{}}:{}});
  vm.runInContext(script,first.context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(first.created.find(item=>item.tag==='select'&&item.attrs['aria-label']==='查询方式').value,'agent');

  const chosen=makeEnv({});
  chosen.context.localStorage.tradeintel_query_mode='data';
  chosen.context.fetch=first.context.fetch;
  vm.runInContext(script,chosen.context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(chosen.created.find(item=>item.tag==='select'&&item.attrs['aria-label']==='查询方式').value,'data');
});

test('agent report labels the safe program summary and not a model draft', async () => {
  const record = {kind: 'trade-query-v1', question: '美国大豆进口',
    scope: {flow: 'import', product_label: '大豆', product_code: '1201',
      partner: 'ALL_ORIGINS', start_month: '2026-06', end_month: '2026-07'},
    summary: {latest_month: '2026-07', latest_value_usd: 46041287,
      previous_month: '2026-06', month_change_usd: 13163460, period_total_usd: 78919114},
    series: [{month: '2026-06', status: 'observed', value_usd: 32877827},
      {month: '2026-07', status: 'observed', value_usd: 46041287}],
    observations: [], notes: [], sources: [], explanation: {status: 'not_requested'}};
  const state = {session_id: 'a'.repeat(32), scope: record.scope,
    turns: [{question: '最近美国大豆进口有什么变化？', status: 'completed',
      report_ids: ['b'.repeat(32)], message_kind: 'program_summary_v1',
      message: '2026-07进口消费额为 46,041,287 美元。仅凭金额变化不能判断政策效果。'}]};
  const env = makeEnv(record, state);
  vm.runInContext(script, env.context);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(env.report().textContent.includes('数据概览'));
  assert.ok(env.report().textContent.includes('46,041,287'));
  assert.ok(!env.report().textContent.includes('助手根据本次工具查询写的草稿'));
  assert.ok(!env.report().textContent.includes('模型解读（试用）'));
});

test('language switch rerenders a saved trade report without changing data or calling a model', async () => {
  const record = {
    kind: 'trade-query-v1', question: '最近美国大米进口有什么变化？',
    scope: {flow: 'import', product_label: '大米', official_product_en: 'RICE', product_code: '1006',
      partner: 'ALL_ORIGINS', start_month: '2026-06', end_month: '2026-07'},
    summary: {latest_month: '2026-07', latest_value_usd: 114725468,
      previous_month: '2026-06', month_change_usd: 3401390, period_total_usd: 226049546},
    series: [{month: '2026-06', status: 'observed', value_usd: 111324078},
      {month: '2026-07', status: 'observed', value_usd: 114725468}],
    observations: [{id: 'import.trend', fact: '中文走势说明'}], notes: [], sources: [],
    explanation: {status: 'not_requested'},
  };
  const env = makeEnv(record);
  const calls = [];
  env.context.fetch = async url => {
    calls.push(url);
    return {ok: true, json: async () => url.startsWith('/api/model/status')
      ? {configured: false, models: {}} : record};
  };
  vm.runInContext(script, env.context);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(env.report().textContent.includes('数据概览'));
  env.context.document.documentElement.lang = 'en';
  env.events['tradeintel:language']();
  assert.ok(env.report().textContent.includes('Overview'));
  assert.ok(env.report().textContent.includes('114,725,468 USD'));
  assert.ok(env.report().textContent.includes('Official U.S. product description: RICE'));
  assert.ok(!env.report().textContent.includes('数据概览'));
  assert.equal(env.context.window.tradeintelLiveReportTitle, 'U.S. imports · RICE');
  assert.ok(!env.report().textContent.includes(record.question));
  assert.deepEqual(calls, ['/api/model/status', '/api/trade/report-state?report_id=report-1']);
});

test('agent English summary and title switch without translating stored answers or making requests', async () => {
  const record = {kind:'trade-query-v1', question:'美国大豆出口',
    scope:{flow:'export',product_label:'大豆',official_product_en:'SOYBEANS',product_code:'1201',
      partner:'ALL_DESTINATIONS',start_month:'2026-06',end_month:'2026-07'},
    summary:{latest_month:'2026-07',latest_value_usd:889379312,previous_month:'2026-06',
      month_change_usd:-3500150,period_total_usd:1782258774},
    series:[{month:'2026-06',status:'observed',value_usd:892879462},
      {month:'2026-07',status:'observed',value_usd:889379312}],
    observations:[],sources:[],notes:[],explanation:{status:'not_requested'}};
  const turn={question:'出口呢？',status:'completed',message_kind:'program_summary_v1',
    message:'中文程序摘要，全部目的地889,379,312美元。',
    message_en:'Total exports (FAS) to all destinations were 889,379,312 USD.',report_ids:['r1']};
  const state={session_id:'a'.repeat(32),turns:[turn]};
  const before=JSON.stringify({record,state}),env=makeEnv(record,state),calls=[];
  env.context.localStorage.tradeintel_query_mode='agent';
  env.context.fetch=async url=>{calls.push(url);return {ok:true,json:async()=>
    url==='/api/model/status'?{configured:false,models:{}}:
      url.startsWith('/api/trade/agent/state')?state:record};};
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  const initialCalls=calls.length;
  env.context.location.hash='#report';
  env.context.document.documentElement.lang='en';env.events['tradeintel:language']();
  assert.equal(env.context.document.title,'U.S. exports · SOYBEANS · TradeIntel');
  assert.ok(env.report().textContent.includes('889,379,312'));
  assert.ok(!env.report().textContent.includes(turn.message_en),'turn-wide summary is not duplicated in a selected report');
  assert.ok(!env.report().textContent.includes(turn.message));
  assert.ok(env.ids.get('chat-messages').textContent.includes(turn.message_en));
  assert.ok(!env.ids.get('chat-messages').textContent.includes(turn.message));
  assert.ok(env.ids.get('chat-messages').textContent.includes(turn.question)); // user text is not translated
  env.context.document.documentElement.lang='zh-CN';env.events['tradeintel:language']();
  assert.ok(!env.report().textContent.includes(turn.message));
  assert.equal(env.context.document.title,'美国大豆出口情况 · TradeIntel');
  assert.equal(calls.length,initialCalls);
  assert.equal(JSON.stringify({record,state}),before);
});

test('English report without an official English label or projected summary uses a safe fallback', async () => {
  const record={kind:'trade-query-v1',question:'中文问题',
    scope:{flow:'import',product_label:'中文商品',product_code:'1201',partner:'ALL_ORIGINS',
      start_month:'2026-07',end_month:'2026-07'},
    summary:{latest_month:'2026-07',latest_value_usd:null,previous_month:null,
      month_change_usd:null,period_total_usd:null},
    series:[{month:'2026-07',status:'unavailable',value_usd:null}],
    observations:[],sources:[],notes:[],explanation:{status:'not_requested'}};
  const env=makeEnv(record,{session_id:'b'.repeat(32),turns:[{status:'completed',
    question:'中文问题',report_ids:['r1'],message_kind:'program_summary_v1',message:'中文摘要'}]});
  env.context.document.documentElement.lang='en';
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(env.context.window.tradeintelLiveReportTitle,'U.S. imports · product group 1201');
  assert.ok(env.report().textContent.includes('No published value'));
  assert.ok(!env.report().textContent.includes('中文摘要'));
  assert.ok(!env.report().textContent.includes('中文商品'));
});

test('v4 report without an additional relation keeps the data report and hides model call', async () => {
  const record = {
    kind: 'trade-query-v1', question: '最近美国大豆进口有什么变化',
    report_id: 'report-1', report_sha256: 'a'.repeat(64),
    scope: {flow: 'import', product_label: '大豆', product_code: '1201',
      partner: 'ALL_ORIGINS', start_month: '2026-06', end_month: '2026-07'},
    summary: {latest_month: '2026-07', latest_value_usd: 12,
      previous_month: '2026-06', month_change_usd: 0, period_total_usd: 24},
    series: [{month: '2026-06', status: 'observed', value_usd: 12},
      {month: '2026-07', status: 'observed', value_usd: 12}],
    sources: [], notes: [],
    explanation: {status: 'not_requested', protocol: 'trade-data-explanation-v4',
      available: false, observations: [], availability_reason: '目前没有额外的关系可解释；数据报告仍可阅读。'},
  };
  const env = makeEnv(record);
  vm.runInContext(script, env.context);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(env.report().textContent.includes('目前没有额外的关系可解释'));
  assert.ok(env.report().textContent.includes('美国大豆进口'));
  assert.ok(env.report().textContent.includes('模型解读（试用）'));
  assert.ok(!env.created.some(item => item.tag === 'button' && item.textContent === '试用模型解读'));
});

test('v4 relation card appears beside the monthly report in Chinese and English', async () => {
  const card = {id:'export.recent_turn', status:'available', eligible_for_ai:true, flow:'export',
    direction:'增加', previous_direction:'减少', months:['2026-05','2026-06','2026-07'],
    fact:'出口金额先在2026-06较上月减少，再在2026-07较上月增加；仅表示最近三个月的转向。'};
  const record = {kind:'trade-query-v1', question:'最近美国小麦出口有什么变化', report_id:'report-1',
    report_sha256:'a'.repeat(64), scope:{flow:'export', product_label:'小麦及混合麦', product_code:'1001',
      partner:'ALL_DESTINATIONS', start_month:'2026-05', end_month:'2026-07'},
    summary:{latest_month:'2026-07', latest_value_usd:25, previous_month:'2026-06',
      month_change_usd:5, period_total_usd:100, complete_window:true},
    series:[{month:'2026-05',status:'observed',value_usd:55},{month:'2026-06',status:'observed',value_usd:20},{month:'2026-07',status:'observed',value_usd:25}],
    sources:[],notes:[],explanation:{status:'not_requested', protocol:'trade-data-explanation-v4',
      available:true,observations:[card]}};
  const env = makeEnv(record);
  env.context.fetch = async url => ({ok:true,json:async()=>url.startsWith('/api/model/status')
    ? {configured:false,models:{}} : record});
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(env.report().textContent.includes('最近三个连续月份（2026-05、2026-06、2026-07）先降后升'));
  env.context.document.documentElement.lang='en';
  env.events['tradeintel:language']();
  assert.ok(env.report().textContent.includes('fell, then rose'));
});

test('same-year peak gap appears as a deterministic page fact without enabling a model call', async () => {
  const card = {id:'import.same_year_peak_gap', status:'available', eligible_for_ai:false, flow:'import',
    year:'2026', latest_month:'2026-07', latest_usd:75, high_usd:81, high_months:['2026-05'], gap_usd:6,
    fact:'2026年已观察月份中，最高为2026-05的81美元；2026-07为75美元，低于该峰值6美元。'};
  const record = {kind:'trade-query-v1', question:'最近美国自行车进口有什么变化', report_id:'report-1',
    report_sha256:'a'.repeat(64), scope:{flow:'import', product_label:'自行车', product_code:'8712',
      partner:'ALL_ORIGINS', start_month:'2026-06', end_month:'2026-07'},
    summary:{latest_month:'2026-07', latest_value_usd:75, previous_month:'2026-06', month_change_usd:-6,
      period_total_usd:156,complete_window:true}, series:[{month:'2026-06',status:'observed',value_usd:81},
      {month:'2026-07',status:'observed',value_usd:75}], sources:[], notes:[],
    explanation:{status:'not_requested', protocol:'trade-data-explanation-v4', available:false, observations:[card]}};
  const env=makeEnv(record);
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(env.report().textContent.includes('2026-07 比 2026 年已收录月份的峰值低 6 美元'));
  assert.ok(env.report().textContent.includes('该峰值出现在 2026-06'));
  env.context.document.documentElement.lang='en';
  env.events['tradeintel:language']();
  assert.ok(env.report().textContent.includes('6 USD below the highest observed value in 2026'));
});

test('v4 combined import-export relation appears after both direction sections', async () => {
  const importCard = {id:'import.recent_run', status:'available', eligible_for_ai:true, flow:'import',
    direction:'增加', consecutive_changes:2, months:['2026-05','2026-06','2026-07'],
    fact:'进口金额连续两个月逐月增加。'};
  const exportCard = {id:'export.recent_run', status:'available', eligible_for_ai:true, flow:'export',
    direction:'增加', consecutive_changes:2, months:['2026-05','2026-06','2026-07'],
    fact:'出口金额连续两个月逐月增加。'};
  const bothCard = {id:'both.latest_relation', status:'available', eligible_for_ai:true, flow:'both',
    relation:'同向', import_direction:'增加', export_direction:'增加', months:['2026-06','2026-07'],
    fact:'在2026-07，进口金额较上月增加，出口金额较上月增加；两方向同向。进口和出口使用不同口径，不相减。'};
  const reportPart = (flow, metric, amount) => ({kind:'trade-query-v1', question:'最近美国大豆进出口有什么变化',
    scope:{flow, product_label:'大豆', product_code:'1201', partner:flow==='import'?'ALL_ORIGINS':'ALL_DESTINATIONS',
      metric, start_month:'2026-05', end_month:'2026-07'},
    summary:{latest_month:'2026-07', latest_value_usd:amount, previous_month:'2026-06',
      month_change_usd:1, period_total_usd:30},
    series:[{month:'2026-06',status:'observed',value_usd:amount-1},{month:'2026-07',status:'observed',value_usd:amount}],
    sources:[],notes:[]});
  const record = {kind:'trade-query-both-v1', question:'最近美国大豆进出口有什么变化',
    scope:{flow:'both', product_label:'大豆', product_code:'1201', partner:'ALL', start_month:'2026-05', end_month:'2026-07'},
    import_report:reportPart('import','import_value_consumption_usd',10),
    export_report:reportPart('export','total_export_fas_usd',20),
    report_id:'report-1', report_sha256:'a'.repeat(64), summary:{}, series:[], sources:[], notes:[],
    explanation:{status:'not_requested', protocol:'trade-data-explanation-v4', available:true,
      observations:[importCard,exportCard,bothCard]}};
  const env=makeEnv(record);
  env.context.fetch=async url=>({ok:true,json:async()=>url.startsWith('/api/model/status')?{configured:false,models:{}}:record});
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  const content=env.report().textContent;
  assert.ok(content.includes('美国进口 · 1201 商品组'));
  assert.ok(content.includes('美国出口 · 1201 商品组'));
  assert.ok(content.includes('进口与出口采用不同口径'));
  assert.ok(content.includes('不相减'));
});

test('reload renders v3 multi-fact entries and their deterministic trend card', async () => {
  const facts = [
    {id: 'export.latest', fact: '2026-07 的出口总额（FAS）为 889,379,312 美元。'},
    {id: 'export.trend', fact: '大豆出口在完整区间连续六个月减少，七月最低。'},
  ];
  const {context, report} = makeEnv({
    kind: 'trade-query-v1', question: '美国大豆出口最近有什么变化',
    scope: {flow: 'export', product_label: '大豆', product_code: '1201', partner: 'ALL_DESTINATIONS',
      metric: 'total_export_fas_usd', start_month: '2025-08', end_month: '2026-07',
      latest_available_month: '2026-07'},
    summary: {latest_month: '2026-07', latest_value_usd: 889379312,
      previous_month: '2026-06', month_change_usd: -3500150, period_total_usd: 100,
      complete_window: true},
    series: [{month: '2026-06', status: 'observed', value_usd: 892879462},
      {month: '2026-07', status: 'observed', value_usd: 889379312}],
    sources: [], notes: [],
    explanation: {status: 'needs_review', observations: facts, parsed: {interpretations: [
      {observation_ids: ['export.latest', 'export.trend'],
        text: '近期出口金额持续减少，但仅凭金额无法确定数量和价格各自的作用。'},
    ]}},
  });
  vm.runInContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(report().textContent.includes('保存的摘要与月份数据未能核对一致'));
  assert.ok(report().textContent.includes(facts[1].fact));
  assert.ok(report().textContent.includes('对应数据：'));
  assert.ok(report().textContent.includes('近期出口金额持续减少'));
});

test('reload keeps rendering legacy single-observation answers', async () => {
  const fact = {id: 'export.latest', fact: '2026-07 的出口总额（FAS）为 889,379,312 美元。'};
  const {context, report} = makeEnv({
    kind: 'trade-query-v1', question: '最新一个月美国大豆出口是多少',
    scope: {flow: 'export', product_label: '大豆', product_code: '1201', partner: 'ALL_DESTINATIONS',
      metric: 'total_export_fas_usd', start_month: '2026-06', end_month: '2026-07',
      latest_available_month: '2026-07'},
    summary: {latest_month: '2026-07', latest_value_usd: 889379312,
      previous_month: '2026-06', month_change_usd: -3500150, period_total_usd: 100,
      complete_window: true},
    series: [{month: '2026-06', status: 'observed', value_usd: 892879462},
      {month: '2026-07', status: 'observed', value_usd: 889379312}],
    sources: [], notes: [],
    explanation: {status: 'needs_review', observations: [fact], parsed: {interpretations: [
      {observation_id: 'export.latest', text: '最新月金额反映所选期间的贸易规模，还需结合数量和价格资料理解。'},
    ]}},
  });
  vm.runInContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(report().textContent.includes(fact.fact));
  assert.ok(report().textContent.includes('最新月金额反映所选期间'));
});

test('unresolved commodity question does not fall through to the saved policy case', async () => {
  const env = makeEnv({});
  env.context.localStorage.tradeintel_last_report_type = '';
  env.context.localStorage.tradeintel_live_trade_report_id = '';
  const calls = [];
  env.context.fetch = async (url, options) => {
    calls.push({url, options});
    const response = url === '/api/model/status' ? {configured: false, models: {}} :
      url === '/api/trade/prepare' ? {
        status: 'needs_product', message: '请确认要查询的商品范围。',
      } :
      url === '/api/product/scope' ? {
        status: 'supported_case', policy_id: 'stored-demo', selected_products: ['demo'],
      } : {status: 'unexpected'};
    return {ok: true, json: async () => response};
  };
  vm.runInContext(script, env.context);
  await new Promise(resolve => setImmediate(resolve));
  env.ids.get('question').value = '最近美国大豆和小麦出口有什么变化？';
  await env.ids.get('question-form').listeners.submit({preventDefault() {}});
  assert.deepEqual(calls.map(item => item.url), ['/api/model/status', '/api/trade/prepare']);
  const status = env.created.find(item => item.className === 'live-status');
  assert.ok(status.textContent.includes('请确认要查询的商品范围'));
});

test('question to report, one model draft, review and readable final output stays offline', async () => {
  const observations = [
    {id: 'export.latest', fact: '2026-07 的出口总额（FAS）为 889,379,312 美元。'},
    {id: 'export.trend', fact: '美国向全部目的地出口大豆的FAS金额，在完整区间连续六个月减少，七月最低。'},
  ];
  const reportRecord = {
    kind: 'trade-query-v1', question: '美国大豆出口最近有什么变化',
    report_id: 'report-1', report_sha256: 'a'.repeat(64),
    scope: {flow: 'export', product_label: '大豆', product_code: '1201', partner: 'ALL_DESTINATIONS',
      metric: 'total_export_fas_usd', start_month: '2025-08', end_month: '2026-07',
      latest_available_month: '2026-07'},
    summary: {latest_month: '2026-07', latest_value_usd: 889379312,
      previous_month: '2026-06', month_change_usd: -3500150, period_total_usd: 100,
      complete_window: true},
    series: [{month: '2026-06', status: 'observed', value_usd: 892879462},
      {month: '2026-07', status: 'observed', value_usd: 889379312}],
    sources: [], notes: [],
    explanation: {status: 'not_requested', observations},
  };
  const drafted = {...reportRecord, explanation: {
    status: 'needs_review', revision: 0, raw_sha256: 'b'.repeat(64), observations,
    parsed: {interpretations: [{
      observation_ids: ['export.trend'],
      text: '近期出口金额持续减少，但仅凭金额无法确定数量和价格各自的作用。',
    }]},
  }};
  const reviewed = {...drafted, explanation: {
    ...drafted.explanation, status: 'reviewed',
    review: {decisions: [{index: 0, verdict: 'accept'}]},
  }};
  const calls = [];
  const env = makeEnv(reportRecord);
  env.context.localStorage.tradeintel_last_report_type = '';
  env.context.fetch = async (url, options) => {
    const body = options?.body ? JSON.parse(options.body) : {};
    calls.push({url, body});
    const response = url === '/api/model/status' ? {configured: false, models: {}} :
      url === '/api/trade/prepare' ? {
        status: 'ready', question: reportRecord.question, flow: 'export',
        product_label: '大豆', product_code: '1201', partner: 'ALL_DESTINATIONS',
        start_month: '2025-08', end_month: '2026-07', latest_available_month: '2026-07',
        dataset_version: 'dataset-1',
      } :
      url === '/api/trade/report' ? reportRecord :
      url === '/api/trade/explanation/call' ? drafted :
      url === '/api/trade/explanation/review' ? reviewed :
      {status: 'error', message: 'unexpected request'};
    return {ok: true, json: async () => response};
  };
  const {context, report, ids, created} = env;
  vm.runInContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  ids.get('question').value = reportRecord.question;
  await ids.get('question-form').listeners.submit({preventDefault() {}});
  const confirm = created.find(item => item.tag === 'button' &&
    item.textContent === '确认范围，生成数据报告');
  await confirm.listeners.click();
  assert.ok(!report().textContent.includes(observations[1].fact),'unrequested observation prose does not replace validated monthly facts');
  assert.ok(report().textContent.includes('模型解读（试用）'));
  assert.ok(report().textContent.includes('模型可能重复报告内容或说错'));
  const generate = created.find(item => item.tag === 'button' && item.textContent === '试用模型解读');
  await generate.listeners.click();
  assert.ok(report().textContent.includes('对应数据：'));
  const accepted = report().querySelectorAll('.review-draft input[type=checkbox]');
  assert.equal(accepted.length, 1, 'the explanation has one review decision');
  accepted[0].checked = true;
  created.find(item => item.id === 'trade-facts-checked').checked = true;
  const save = created.find(item => item.tag === 'button' && item.textContent === '保存审阅结果');
  await save.listeners.click();
  assert.ok(report().textContent.includes('人工核对后采纳'));
  assert.equal(report().textContent.split(observations[1].fact).length - 1, 0,
    'reviewed prose does not silently restore an unsupported six-month claim to the two-month base report');
  assert.deepEqual(calls.map(item => item.url), [
    '/api/model/status', '/api/trade/prepare', '/api/trade/report',
    '/api/trade/explanation/call', '/api/trade/explanation/review',
  ]);
});

test('commodity choice is visible and its identity stays bound through report generation', async () => {
  const question = '最近美国小麦出口有什么变化？';
  const candidate = {id: 'export:1001', code: '1001', level: 'HS4',
    zh_label: '小麦及混合麦', official_en: 'WHEAT AND MESLIN', child_codes: 8,
    source_url: 'https://www.census.gov/fixture/EXDB2607.ZIP'};
  const choice = {status: 'needs_product_choice', question, flow: 'export',
    start_month: '2025-08', end_month: '2026-07', catalog_version: 'c'.repeat(64),
    candidates: [candidate]};
  const ready = {status: 'ready', question, flow: 'export', product_label: candidate.zh_label,
    product_code: candidate.code, selected_product_id: candidate.id,
    catalog_version: choice.catalog_version, official_product_en: candidate.official_en,
    partner: 'ALL_DESTINATIONS', start_month: choice.start_month,
    end_month: choice.end_month, latest_available_month: '2026-07',
    dataset_version: 'd'.repeat(64)};
  const report = {kind: 'trade-query-v1', question, scope: ready,
    summary: {latest_month: '2026-07', latest_value_usd: 10, previous_month: null,
      month_change_usd: null, period_total_usd: 10, complete_window: true},
    series: [{month: '2026-07', status: 'observed', value_usd: 10}],
    sources: [], notes: [], explanation: {status: 'not_requested', observations: []}};
  const env = makeEnv(report);
  env.context.localStorage.tradeintel_last_report_type = '';
  const calls = [];
  env.context.fetch = async (url, options) => {
    const body = options?.body ? JSON.parse(options.body) : {};
    calls.push({url, body});
    return {ok: true, json: async () => url === '/api/model/status' ?
      {configured: false, models: {}} : url === '/api/trade/prepare' ?
      (body.selected_product_id ? ready : choice) : report};
  };
  vm.runInContext(script, env.context);
  await new Promise(resolve => setImmediate(resolve));
  env.ids.get('question').value = question;
  await env.ids.get('question-form').listeners.submit({preventDefault() {}});
  assert.ok(env.ids.get('scope-preview').textContent.includes('WHEAT AND MESLIN'));
  const choose = env.created.find(item => item.tag === 'button' && item.textContent === '选这个范围');
  await choose.listeners.click();
  const confirm = env.created.find(item => item.tag === 'button' &&
    item.textContent === '确认范围，生成数据报告');
  await confirm.listeners.click();
  assert.equal(calls[2].body.selected_product_id, candidate.id);
  assert.equal(calls[2].body.catalog_version, choice.catalog_version);
  assert.equal(calls[3].body.selected_product_id, candidate.id);
  assert.equal(calls[3].body.catalog_version, choice.catalog_version);
  assert.ok(env.report().textContent.includes('小麦及混合麦'));
});

test('announcement statistics report restores, shows coverage and sources, and switches language', async () => {
  const record = {
    kind: 'announcement-statistics-report-v1', question: '公告相关商品贸易情况',
    report_id: 'a'.repeat(32), report_sha256: 'b'.repeat(64),
    scope: {start_month: '2026-06', end_month: '2026-07', selected_codes: ['28046100'],
      excluded_partial_entries: [], unselected_whole_codes: [], latest_available_month: '2026-07'},
    policy: {title: 'Silicon Notice', source_provenance: 'user_supplied_unverified',
      source_url: 'https://official.example/notice', fields: [
        {field: 'effective_date', status: 'known', value: '2025-01-01'},
        {field: 'hts_codes', status: 'known', value: [{code: '28046100', precision: 'whole_hts8'}]},
        {field: 'rates', status: 'known', value: {'28046100': 10}},
        {field: 'conditions', status: 'known', value: ['The original notice stated 10 percent.']},
        {field: 'revisions', status: 'known', value: 'Later notices stated 15 percent and then 7.5 percent.'}],
      citations: [{field: 'effective_date', section_id: 'p1', quote: 'Effective January 1, 2025.'}]},
    monthly: [{month: '2026-06', status: 'queryable_aggregate', observed_value_usd: 100,
      complete_codes: 1, selected_codes: 1, rows: []},
      {month: '2026-07', status: 'queryable_aggregate', observed_value_usd: 125,
       complete_codes: 0, selected_codes: 1, rows: [{hts8: '28046100', observed_value_usd: 125,
         month_change_usd: null, month_change_status: 'not_comparable', expected_count: 2,
         matched_count: 2, observed_count: 1, complete: false, absent_codes: [],
         unobserved_codes: ['2804610020'], classification_available: true}]}],
    sources: [{months: ['2026-06', '2026-07'], url: 'https://www.census.gov/trade/monthly.zip'}],
    notes: ['图表金额为该月已观测的中国来源消费进口额；缺失细分行不补零。'],
    explanation: {status: 'not_requested', protocol: 'none', available: false},
  };
  const env = makeEnv(record);
  env.context.location.search = '?announcement_report_id=' + record.report_id;
  vm.runInContext(script, env.context);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(env.report().textContent.includes('公告所涉商品的美国进口情况'));
  assert.ok(env.report().textContent.includes('公告原题：Silicon Notice'));
  assert.ok(env.report().textContent.includes('125'));
  assert.ok(env.report().textContent.includes('2 / 2 / 1'));
  assert.ok(env.report().textContent.includes('2804610020'));
  assert.ok(env.report().textContent.includes('美国人口普查局月度贸易数据'));
  assert.ok(env.report().textContent.includes('查看 2 个月的贸易数据来源'));
  assert.ok(env.report().textContent.includes('公告原文记载的附加税率：10%（1 个税号）'));
  assert.ok(env.report().textContent.includes('不等于图表月份或今天实际适用的税率'));
  assert.ok(env.report().textContent.includes('后来的调整和排除，我们还没有核对'));
  assert.ok(!env.report().textContent.includes('现行税率：10%'));
  const warning = env.created.find(item => item.className === 'announcement-applicability-note');
  assert.ok(warning && !String(warning.className).includes('print-exclude'));
  assert.ok(env.report().textContent.includes('完整条款可展开查看'));
  assert.ok(env.report().textContent.includes('以下数据报告按已发布的贸易数据生成，不调用模型。'));
  assert.ok(!env.report().textContent.includes('试用模型解读'));
  record.scope.notice_time_relation = 'before_recorded_effective_month';
  env.context.document.documentElement.lang = 'en';
  env.events['tradeintel:language']();
  assert.ok(env.report().textContent.includes('U.S. imports of products in this notice'));
  assert.ok(env.report().textContent.includes('Official notice: Silicon Notice'));
  assert.ok(env.report().textContent.includes('Data sources'));
  assert.ok(env.report().textContent.includes('View trade-data sources for 2 months'));
  assert.ok(env.report().textContent.includes('Observed value (USD)'));
  assert.ok(env.report().textContent.includes('do not treat them as rates for the charted months or today'));
  assert.ok(env.report().textContent.includes('earlier trade context, not post-policy results'));
});

test('partial notice shows broader-product chart, while source-only notice never shows a trade bar', async () => {
  const base = {
    kind: 'announcement-context-report-v1', report_id: 'c'.repeat(32),
    policy: {policy_population: '仅部分泵类货品', source_url: 'https://official.example/notice',
      source_provenance: 'user_supplied_unverified', evidence: [{section_id: 'p1', quote: 'Except pumps'}],
      confirmed_fields: [{field: 'conditions', status: 'known', value: '特定用途', reason: '',
        evidence: [{section_id: 'p1', quote: 'Except pumps'}]}]},
    scope: {statistical_population: '整个 84139190 商品组', context_code: '84139190',
      unobserved_eligibility: [{description: '月表不能识别用途'}]},
    monthly: [{month: '2026-07', whole_parent_value_usd: 300}],
    sources: [{month: '2026-07', url: 'https://official.example/month.zip'}], notes: [],
  };
  const parent = makeEnv({...base, context_type: 'parent'});
  parent.context.location.search = '?announcement_report_id=' + base.report_id;
  vm.runInContext(script, parent.context);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(parent.report().textContent, /整个 84139190 商品组/);
  assert.match(parent.report().textContent, /300 美元/);
  assert.match(parent.report().textContent, /不是政策覆盖额/);
  assert.ok(parent.created.some(item => item.className === 'trade-bar-row'));
  parent.context.document.documentElement.lang = 'en';
  parent.events['tradeintel:language']();
  assert.match(parent.report().textContent, /broader product group/);

  const sourceOnly = makeEnv({...base, context_type: 'source_only', monthly: [],
    policy: {...base.policy, confirmed_fields: [
      ...base.policy.confirmed_fields,
      {field: 'rates', status: 'known', value: ['84% 第99章条目', '75美元 每件邮政货品'],
        evidence: [{section_id: 'p1', quote: '84%'}]},
    ]},
    scope: {statistical_population: null, unobserved_eligibility: [{description: '邮寄方式无法从月表识别'}]},
    sources: [{url: 'https://official.example/notice'}]});
  sourceOnly.context.location.search = '?announcement_report_id=' + base.report_id;
  vm.runInContext(script, sourceOnly.context);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(sourceOnly.report().textContent, /这里不画贸易图/);
  assert.ok(!sourceOnly.created.some(item => item.className === 'trade-bar-row'));
  assert.ok(!sourceOnly.report().textContent.includes('300 美元'));
  assert.ok(!sourceOnly.report().textContent.includes('贸易数据原包'));
  assert.ok(!sourceOnly.report().textContent.includes('上层商品按官方子码核对'));
  assert.match(sourceOnly.report().textContent, /没有查询贸易数据/);
  assert.equal(sourceOnly.created.filter(item => item.tag === 'a' && item.href === base.policy.source_url).length, 1);
  assert.ok(sourceOnly.created.some(item => item.tag === 'li' && item.textContent === '84% 第99章条目'));
  assert.ok(!sourceOnly.report().textContent.includes('["84%'));
  const details = sourceOnly.report().querySelectorAll('details:not([open])');
  sourceOnly.events.beforeprint();
  assert.ok(details.every(item => item.open));
});

test('assistant mode sends a natural question, renders its saved report, and keeps the session for follow-up', async () => {
  const importReport = {
    kind:'trade-query-v1', question:'美国大豆进口', report_id:'agent-report-1',
    scope:{flow:'import',product_label:'大豆',product_code:'1201',partner:'ALL_ORIGINS',
      start_month:'2026-06',end_month:'2026-07'},
    summary:{latest_month:'2026-07',latest_value_usd:46041287,previous_month:'2026-06',
      month_change_usd:1,period_total_usd:46041288},
    series:[{month:'2026-06',status:'observed',value_usd:1},
      {month:'2026-07',status:'observed',value_usd:46041287}],sources:[],notes:[],
    explanation:{status:'not_requested',available:false,observations:[]},
  };
  const exportReport = {...importReport, question:'美国大豆出口',report_id:'agent-report-2',
    scope:{...importReport.scope,flow:'export',partner:'ALL_DESTINATIONS'},
    summary:{...importReport.summary,latest_value_usd:889379312},
    series:[...importReport.series.slice(0,1),
      {month:'2026-07',status:'observed',value_usd:889379312}]};
  const env=makeEnv({});
  env.context.localStorage.tradeintel_query_mode='agent';
  env.context.localStorage.tradeintel_last_report_type='';
  env.context.localStorage.tradeintel_live_trade_report_id='';
  env.context.crypto={randomUUID:()=> '00000000-0000-4000-8000-000000000001'};
  const calls=[];
  env.context.fetch=async (url,options)=>{
    calls.push({url,body:options?.body?JSON.parse(options.body):null});
    const turns=calls.filter(call=>call.url==='/api/trade/agent/turn').length;
    const makeTurn=(question,rid)=>({question,status:'completed',message:'已根据本次查询整理。',
      message_kind:'program_summary_v1',
      report_ids:[rid],tool_calls:[{tool:'search_products',status:'ok'},
        {tool:'query_trade',status:'ok'}]});
    const state={session_id:'a'.repeat(32),turns:[makeTurn('最近美国大豆进口有什么变化？','agent-report-1'),
      ...(turns>1?[makeTurn('出口呢？','agent-report-2')]:[])]};
    const body=url==='/api/model/status'?{configured:true,models:{}}:
      url==='/api/trade/agent/turn'?state:
      url.includes('agent-report-2')?exportReport:importReport;
    return {ok:true,json:async()=>body};
  };
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  env.ids.get('question').value='最近美国大豆进口有什么变化？';
  await env.ids.get('question-form').listeners.submit({preventDefault(){}});
  assert.ok(env.report().textContent.includes('46,041,287'),
    JSON.stringify({calls,text:env.report().textContent}));
  assert.ok(env.report().textContent.includes('数据概览'));
  assert.ok(!env.report().textContent.includes('已根据本次查询整理'),'generic turn summary is not appended to the report');
  assert.ok(!calls.some(call=>call.url==='/api/trade/prepare'));
  env.ids.get('question').value='出口呢？';
  await env.ids.get('question-form').listeners.submit({preventDefault(){}});
  const turns=calls.filter(call=>call.url==='/api/trade/agent/turn');
  assert.equal(turns.length,2);
  assert.equal(turns[1].body.session_id,'a'.repeat(32));
  assert.ok(env.report().textContent.includes('889,379,312'));
  const restart=env.ids.get('new-conversation');
  assert.ok(restart);
  await restart.listeners.click();
  assert.equal(env.context.localStorage.getItem('tradeintel_agent_session'),'');
  assert.ok(env.report().textContent.includes('889,379,312'));
});

test('reader view survives saved-page loading and treats policy text as plain text', async () => {
  const sid='d'.repeat(32);
  const record={kind:'trade-query-v1',report_id:'reader-report',
    scope:{flow:'import',product_label:'大豆',product_code:'1201',partner:'ALL_ORIGINS',start_month:'2026-06',end_month:'2026-07'},
    summary:{latest_month:'2026-07',latest_value_usd:100,previous_month:'2026-06',month_change_usd:5},
    series:[{month:'2026-06',status:'observed',value_usd:95},{month:'2026-07',status:'observed',value_usd:100}],
    sources:[],notes:[],explanation:{status:'not_requested'}};
  const reader={schema:'trade-reader-view-v1',facts:[{report_id:'reader-report',text:'直接回答100美元。',text_en:'Direct answer: 100 USD.'}],
    policy:{status:'partial',evidence_bundles:[{hit:{citation_id:'v:s',text:'<script>not executable</script>'},
      required_context:[{status:'known',dependency:'exceptions',citation_id:'v:e',text:'独立例外全文。'}]}]},
    unanswered:[],method:{text:'已发布数据。',text_en:'Published data.'}};
  const state={session_id:sid,turns:[{question:'政策',status:'completed',message:'OLD REPETITIVE MESSAGE',
    message_kind:'program_summary_v1',reader_view:reader,report_ids:['reader-report']}]};
  const env=makeEnv({});env.context.location.search=`?agent_session_id=${sid}`;
  env.context.window.location.search=env.context.location.search;
  const calls=[];
  env.context.fetch=async(url,options)=>{calls.push(options?.method||'GET');return {ok:true,json:async()=>
    url==='/api/model/status'?{configured:true,models:{}}:url.startsWith('/api/trade/agent/state?')?state:record};};
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  assert.match(env.report().textContent,/为 100 美元/);
  assert.ok(!env.report().textContent.includes('直接回答100美元'),'the same latest value is not restated in a second summary');
  assert.match(env.report().textContent,/独立例外全文/);
  assert.match(env.report().textContent,/政策证据不完整/);
  assert.ok(!env.report().textContent.includes('OLD REPETITIVE MESSAGE'));
  assert.ok(!env.created.some(item=>item.tag==='script'));
  assert.ok(calls.every(method=>method==='GET'));
});

test('saved assistant link shows only the public summary without starting a new call', async () => {
  const sessionId='b'.repeat(32);
  const reportState={kind:'trade-query-v1',question:'最近美国大豆进口有什么变化',report_id:'saved-report',
    scope:{flow:'import',product_label:'大豆',product_code:'1201',partner:'ALL_ORIGINS',
      start_month:'2026-06',end_month:'2026-07'},
    summary:{latest_month:'2026-07',latest_value_usd:46041287,previous_month:'2026-06',
      month_change_usd:13163460,period_total_usd:78919114},
    series:[{month:'2026-06',status:'observed',value_usd:32877827},
      {month:'2026-07',status:'observed',value_usd:46041287}],
    sources:[],notes:['目前未运行模型解释；本页摘要和图表均由已发布数据计算。'],
    explanation:{status:'not_requested',available:true,observations:[]}};
  const state={session_id:sessionId,turns:[{question:reportState.question,status:'completed',
    message:'旧版模型文字未经本规则核验，已隐藏；数据报告仍可查看。',
    message_kind:'legacy_unreviewed_hidden',
    report_ids:['saved-report'],tool_calls:[{tool:'query_trade',status:'ok'}]}]};
  const env=makeEnv({});
  env.context.location.search=`?agent_session_id=${sessionId}`;
  env.context.window.location.search=env.context.location.search;
  const calls=[];
  env.context.fetch=async (url,options)=>{
    calls.push({url,method:options?.method||'GET'});
    return {ok:true,json:async()=>url==='/api/model/status'?{configured:true,models:{}}:
      url.startsWith('/api/trade/agent/state?')?state:reportState};
  };
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  const rendered=env.report().textContent;
  assert.match(rendered,/46,041,287/);
  assert.ok(!rendered.includes('旧版模型文字未经本规则核验'));
  assert.match(rendered,/旧记录的未审模型文字不作为报告正文/);
  assert.ok(!rendered.includes('目前未运行模型解释'));
  assert.ok(!env.created.some(item=>item.tag==='button'&&item.textContent==='试用模型解读'));
  assert.deepEqual(calls.map(call=>call.method),['GET','GET','GET']);
  assert.ok(calls.some(call=>call.url===`/api/trade/agent/state?session_id=${sessionId}`));
  assert.equal(env.context.localStorage.getItem('tradeintel_agent_session'),sessionId);
});

test('multi-report assistant restores the main all-destinations report and labels the China option', async () => {
  const sessionId='c'.repeat(32), allId='d'.repeat(32), chinaId='e'.repeat(32);
  const base={kind:'trade-query-v1',question:'美国大豆出口',
    scope:{flow:'export',product_label:'大豆',product_code:'1201',partner:'ALL_DESTINATIONS',
      start_month:'2025-08',end_month:'2026-07'},
    summary:{latest_month:'2026-07',latest_value_usd:889379312,previous_month:'2026-06',
      month_change_usd:-3500150,period_total_usd:18789570646},
    series:[{month:'2026-06',status:'observed',value_usd:892879462},
      {month:'2026-07',status:'observed',value_usd:889379312}],
    sources:[],notes:[],explanation:{status:'not_requested',available:false,observations:[]}};
  const allReport={...base,report_id:allId};
  const chinaReport={...base,report_id:chinaId,
    scope:{...base.scope,partner:'CHINA'},
    summary:{...base.summary,latest_value_usd:141197240},
    series:[{month:'2026-06',status:'observed',value_usd:203922101},
      {month:'2026-07',status:'observed',value_usd:141197240}]};
  const state={session_id:sessionId,scope:allReport.scope,turns:[
    {question:'出口呢？',status:'completed',message_kind:'program_summary_v1',
      message:'2026-07（全部目的地）出口 FAS 总额为 889,379,312 美元。2026-07（中国目的地）出口 FAS 总额为 141,197,240 美元。',
      report_ids:[allId,chinaId],primary_report_id:allId,
      report_options:[{report_id:allId,flow:'export',partner:'ALL_DESTINATIONS'},
        {report_id:chinaId,flow:'export',partner:'CHINA'}]}]};
  const env=makeEnv({},state);
  env.context.localStorage.tradeintel_last_report_type='';
  const calls=[];
  env.context.fetch=async url=>{calls.push(url);return {ok:true,json:async()=>
    url==='/api/model/status'?{configured:true,models:{}}:
      url.startsWith('/api/trade/agent/state?')?state:
        url.includes(chinaId)?chinaReport:allReport};};
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(calls.some(url=>url.includes(`report_id=${allId}`)));
  assert.ok(calls.some(url=>url.includes(`report_id=${chinaId}`)), 'saved card scope is loaded read-only');
  assert.ok(env.report().textContent.includes('889,379,312'));
  assert.ok(env.ids.get('chat-messages').textContent.includes('出口 · 全部目的地（主报告）'));
  const chinaButton=env.created.find(item=>item.tag==='button'&&item.textContent.startsWith('出口 · 中国'));
  assert.ok(chinaButton);
  await chinaButton.listeners.click();
  assert.ok(calls.some(url=>url.includes(`report_id=${chinaId}`)));
  assert.ok(env.report().textContent.includes('141,197,240'));
  assert.ok(env.report().textContent.includes('数据概览'));
  assert.ok(!env.report().textContent.includes('模型解读（试用）'));
});

test('showcase runtime never initializes the local API, even under /preview/', async()=>{
  const env=makeEnv({});env.context.document.documentElement.dataset.runtime='showcase';
  let requests=0;env.context.fetch=async()=>{requests++;throw Error('must stay static');};
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests,0);assert.equal(env.created.length,0);
});

test('local marker alone does not enable the API on a repository subpath', async()=>{
  const env=makeEnv({});env.context.location.pathname='/TradeIntel/preview/';
  let requests=0;env.context.fetch=async()=>{requests++;throw Error('not the local route');};
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests,0);
});

test('settings are a labelled dialog, hide duplicate model input and never probe on opening', async()=>{
  const env=makeEnv({});const calls=[];
  env.context.localStorage.tradeintel_last_report_type='';
  env.context.fetch=async(url,options)=>{calls.push({url,method:options?.method||'GET'});
    return {ok:true,json:async()=>({configured:true,provider:'deepseek',model:'deepseek-flash',models:{deepseek:['deepseek-flash']}})};};
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  const dialog=env.created.find(item=>item.tag==='dialog');
  assert.equal(dialog.attrs['aria-labelledby'],'model-settings-title');
  env.ids.get('open-model-settings').listeners.click();assert.equal(dialog.open,true);
  const input=env.created.find(item=>item.tag==='input'&&item.attrs['aria-label']==='Model ID');
  assert.equal(input.parentNode.hidden,true);
  const preset=env.created.find(item=>item.tag==='select'&&item.attrs['aria-label']==='常用型号');
  preset.value='custom';preset.listeners.change();assert.equal(input.parentNode.hidden,false);
  const secret=env.created.find(item=>item.type==='password');secret.value='temporary-test-value';
  const close=env.created.find(item=>item.className==='dialog-close');close.listeners.click();
  assert.equal(dialog.open,false);assert.equal(secret.value,'');
  assert.ok(calls.every(call=>call.method==='GET'));
});

test('Enter sends, Shift+Enter and IME composition never submit', async()=>{
  const env=makeEnv({});let submitted=0;
  env.ids.get('question-form').requestSubmit=()=>submitted++;
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  const handler=env.ids.get('question').listeners.keydown;
  handler({key:'Enter',shiftKey:true,preventDefault(){throw Error('newline prevented');}});
  handler({key:'Enter',isComposing:true,preventDefault(){throw Error('IME prevented');}});
  handler({key:'Enter',keyCode:229,preventDefault(){throw Error('IME prevented');}});
  handler({key:'Enter',preventDefault(){}});assert.equal(submitted,1);
  env.ids.get('question-form').submitButton.disabled=true;
  handler({key:'Enter',preventDefault(){}});assert.equal(submitted,1);
});

test('data-mode language change does not overwrite range cards with an old chat', async()=>{
  const env=makeEnv({}, {session_id:'a'.repeat(32),turns:[{question:'old chat',status:'needs_clarification',message:'clarify'}]});
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  const scope=env.ids.get('scope-preview');scope.textContent='kept data range';scope.hidden=false;
  env.context.document.documentElement.lang='en';env.events['tradeintel:language']();
  assert.equal(scope.textContent,'kept data range');assert.equal(scope.hidden,false);
  assert.equal(env.ids.get('chat-messages').hidden,true);
});

test('new conversation retains an unconfirmed pending request and creates no POST', async()=>{
  const env=makeEnv({});const sid='a'.repeat(32),pending=JSON.stringify({session_id:sid,request_id:'b'.repeat(32),question:'still running'});
  env.context.localStorage.tradeintel_agent_pending=pending;
  env.context.localStorage.tradeintel_agent_session=sid;
  const calls=[];env.context.fetch=async(url,options)=>{calls.push(options?.method||'GET');return {ok:true,json:async()=>
    url==='/api/model/status'?{configured:false,models:{}}:{session_id:sid,turns:[{question:'still running',status:'in_progress'}]}};};
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  await env.ids.get('new-conversation').listeners.click();
  assert.equal(env.context.localStorage.getItem('tradeintel_agent_pending'),pending);
  assert.equal(env.context.localStorage.getItem('tradeintel_agent_session'),sid);
  assert.ok(calls.every(method=>method==='GET'));
});

test('a selected older report survives refresh rather than being replaced by the last turn', async()=>{
  const report=(id,flow,value)=>({kind:'trade-query-v1',report_id:id,question:flow,
    scope:{product_code:'1201',product_label:'大豆',flow,partner:'ALL',start_month:'2026-06',end_month:'2026-07'},
    summary:{latest_month:'2026-07',latest_value_usd:value,month_change_usd:1},
    series:[{month:'2026-06',status:'observed',value_usd:value-1},{month:'2026-07',status:'observed',value_usd:value}],
    sources:[],notes:[],observations:[],explanation:{status:'not_requested'}});
  const first=report('first-report','import',100),last=report('last-report','export',200);
  const state={session_id:'a'.repeat(32),turns:[
    {question:'进口',status:'completed',report_ids:['first-report'],message_kind:'program_summary_v1',message:'进口100'},
    {question:'出口呢',status:'completed',report_ids:['last-report'],message_kind:'program_summary_v1',message:'出口200'}]};
  const env=makeEnv(first,state);env.context.location.hash='#report';
  env.context.localStorage.tradeintel_query_mode='agent';
  env.context.localStorage.tradeintel_active_report=JSON.stringify({origin:'local',id:'first-report'});
  const methods=[];env.context.fetch=async(url,options)=>{methods.push(options?.method||'GET');return {ok:true,json:async()=>
    url==='/api/model/status'?{configured:true,models:{}}:url.startsWith('/api/trade/agent/state')?state:
      url.includes('last-report')?last:first};};
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  assert.match(env.report().textContent,/100/);assert.equal(env.context.localStorage.tradeintel_live_trade_report_id,'first-report');
  assert.match(env.ids.get('chat-messages').textContent,/出口呢/);assert.ok(methods.every(method=>method==='GET'));
});

test('concurrent duplicate submits send one POST and completion stays in the conversation', async()=>{
  const env=makeEnv({});env.context.location.hash='#workspace';env.context.localStorage.tradeintel_last_report_type='';
  env.context.localStorage.tradeintel_query_mode='agent';env.context.crypto={randomUUID:()=> 'a'.repeat(32)};
  let complete;const pending=new Promise(resolve=>complete=resolve),posts=[];
  env.context.fetch=async(url,options)=>{
    if(options?.method==='POST'){posts.push(url);return pending;}
    return {ok:true,json:async()=>({configured:true,models:{}})};
  };
  vm.runInContext(script,env.context);await new Promise(resolve=>setImmediate(resolve));
  env.ids.get('question').value='请选择商品';
  const first=env.ids.get('question-form').listeners.submit({preventDefault(){}});
  const duplicate=env.ids.get('question-form').listeners.submit({preventDefault(){}});
  assert.deepEqual(posts,['/api/trade/agent/turn']);
  complete({ok:true,json:async()=>({session_id:'a'.repeat(32),turns:[{question:'请选择商品',status:'needs_clarification',message:'哪个商品？'}]})});
  await Promise.all([first,duplicate]);
  assert.equal(env.context.location.hash,'#workspace');assert.match(env.ids.get('chat-messages').textContent,/哪个商品/);
});
