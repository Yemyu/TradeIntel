// Offline reload coverage for new array citations and older single-ID answers.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../web/design-preview/live.js'), 'utf8');

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

function makeEnv(reportState) {
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
  const storage = {
    tradeintel_last_report_type: 'trade',
    tradeintel_live_trade_report_id: 'report-1',
    getItem(key) { return this[key] || ''; },
    setItem(key, value) { this[key] = value; },
  };
  const context = vm.createContext({
    location: {pathname: '/preview/', hash: ''},
    localStorage: storage,
    window: {location: {pathname: '/preview/', search: '', hash: ''}, localStorage: storage},
    document: {
      title: '', documentElement: {lang: 'zh-CN'},
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
        : reportState,
    }),
  });
  return {context, report: () => created.find(item => item.id === 'live-result'), ids, created, events};
}

test('language switch rerenders a saved trade report without changing data or calling a model', async () => {
  const record = {
    kind: 'trade-query-v1', question: 'How have U.S. rice imports changed recently?',
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
  assert.ok(env.report().textContent.includes('先看数字'));
  env.context.document.documentElement.lang = 'en';
  env.events['tradeintel:language']();
  assert.ok(env.report().textContent.includes('Key figures'));
  assert.ok(env.report().textContent.includes('114,725,468 USD'));
  assert.ok(env.report().textContent.includes('Official U.S. product description: RICE'));
  assert.ok(!env.report().textContent.includes('先看数字'));
  assert.deepEqual(calls, ['/api/model/status', '/api/trade/report-state?report_id=report-1']);
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
      partner:'ALL_DESTINATIONS', start_month:'2025-08', end_month:'2026-07'},
    summary:{latest_month:'2026-07', latest_value_usd:25, previous_month:'2026-06',
      month_change_usd:5, period_total_usd:100},
    series:[{month:'2026-06',status:'observed',value_usd:20},{month:'2026-07',status:'observed',value_usd:25}],
    sources:[],notes:[],explanation:{status:'not_requested', protocol:'trade-data-explanation-v4',
      available:true,observations:[card]}};
  const env = makeEnv(record);
  env.context.fetch = async url => ({ok:true,json:async()=>url.startsWith('/api/model/status')
    ? {configured:false,models:{}} : record});
  vm.runInContext(script,env.context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(env.report().textContent.includes('出口金额先在2026-06'));
  assert.ok(env.report().textContent.includes('最近出现转向'));
  env.context.document.documentElement.lang='en';
  env.events['tradeintel:language']();
  assert.ok(env.report().textContent.includes('Recent direction change'));
  assert.ok(env.report().textContent.includes('moved from down in 2026-06 to up in 2026-07'));
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
  assert.ok(content.includes('进口和出口放在一起看'));
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
  assert.ok(report().textContent.includes('这段时间的走势'));
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
  assert.ok(report().textContent.includes(observations[1].fact));
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
  assert.equal(report().textContent.split(observations[1].fact).length - 1, 1,
    'the final reader view shows the trend fact once, not repeated under the prose');
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
        {field: 'rates', status: 'known', value: {'28046100': 0}},
        {field: 'conditions', status: 'known', value: ['Initial tariff level of 0 percent.']},
        {field: 'revisions', status: 'known', value: 'The rate will be announced later.'}],
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
  assert.ok(env.report().textContent.includes('附加税率：0%（1 个税号）'));
  assert.ok(env.report().textContent.includes('完整条款可展开查看'));
  assert.ok(env.report().textContent.includes('以下数据报告按已发布的贸易数据生成，不调用模型。'));
  assert.ok(!env.report().textContent.includes('试用模型解读'));
  env.context.document.documentElement.lang = 'en';
  env.events['tradeintel:language']();
  assert.ok(env.report().textContent.includes('U.S. imports of products in this notice'));
  assert.ok(env.report().textContent.includes('Official notice: Silicon Notice'));
  assert.ok(env.report().textContent.includes('Data sources'));
  assert.ok(env.report().textContent.includes('View trade-data sources for 2 months'));
  assert.ok(env.report().textContent.includes('Observed value (USD)'));
});
