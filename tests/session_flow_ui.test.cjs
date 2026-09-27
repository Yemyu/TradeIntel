// F9 fixture: runs the real session-research page script against a DOM double
// with a scripted fetch stub. No browser and no network; verifies the offline
// session flow wiring: create -> start -> confirm -> evidence -> generate ->
// review -> export, refresh recovery and duplicate-click protection.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/session-research.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makeEnv(search = '') {
  const nodes = new Map();
  const requested = [];
  const requestBodies = [];
  let session = {session_id: 'session-0123456789abcdef', revision: 0, messages: [],
                 current_request: null, request_digest: 'digest-1', tasks: {}};
  const task = {task_id: 'task-1', state: 'received', request_digest: 'digest-1',
                request_snapshot: null, evidence: null, response: null, created_at: 't1'};
  const responses = {
    '/api/session/create': () => ({session: session = {...session, session_id: session.session_id}}),
    '/api/session/message': () => ({status: 'appended'}),
    '/api/session/proposal': (body) => ({
      proposal_id: 'proposal-0123456789abcdef',
      question: body.original_question,
      request: {schema_version: 'analysis-request-v1', original_question: body.original_question,
                policy_id: 'us_301_review2025_tungsten_solar', products: ['all'],
                window: {start: '2026-02', end: '2026-07', mode: 'latest'},
                data_version: 'version-1', comparisons: []},
      product_cards: [], data_version: 'version-1', query_executed: false,
      message: '范围提案已生成'}),
    '/api/session/confirm-proposal': () => {
      session.current_request = {schema_version: 'analysis-request-v1',
        original_question: '分析2026-07', policy_id: 'us_301_review2025_tungsten_solar',
        products: ['all'], window: {start: '2026-02', end: '2026-07', mode: 'latest'},
        data_version: 'version-1', comparisons: []};
      return {status: 'confirmed', session};
    },
    '/api/session/task/start': () => {
      const existing = Object.values(session.tasks)[0];
      if (existing) {
        if (existing.state === 'generation_started' && !existing.response) {
          return {status: 'blocked_unknown_outcome', task_id: existing.task_id,
                  reason: '同名任务已开始生成但没有保存的响应'};
        }
        if (['received', 'awaiting_confirmation', 'evidence_ready'].includes(existing.state)) {
          return {status: 'in_progress', task_id: existing.task_id,
                  reason: '同名任务尚未完成，继续等待；不创建第二个任务。'};
        }
        if (['response_saved', 'needs_review', 'reviewed', 'exportable'].includes(existing.state)) {
          return {status: 'reuse', task_id: existing.task_id, reason: '已有结果，直接复用'};
        }
        return {status: 'blocked_unknown_outcome', task_id: existing.task_id,
                reason: '同名任务处于失败/未知结果状态；需要人工决定后才能重试。'};
      }
      session.tasks = {key1: {...task, request_snapshot: session.current_request}};
      return {status: 'create', task_id: 'task-1'};
    },
    '/api/session/request': () => {
      session.current_request = {policy_id: 'us_301_review2025_tungsten_solar',
                                 month: '2026-07', product: 'all', focus: 'contrast'};
      return {status: 'confirmed', session};
    },
    '/api/session/task/transition': (body) => {
      const key = Object.keys(session.tasks)[0];
      session.tasks = {[key]: {...session.tasks[key], state: body.state}};
      return {status: body.state};
    },
    '/api/session/task/evidence': () => {
      session.tasks = {key1: {...session.tasks.key1, state: 'evidence_ready',
        evidence: {rows: [{hts8: '81019910', world_import_usd: 100, china_import_usd: 10,
                           china_share_percent: 10, share_status: 'known'}], month: '2026-07'}}};
      return {status: 'evidence_ready', evidence: session.tasks.key1.evidence};
    },
    '/api/session/task/generate': () => {
      session.tasks = {key1: {...session.tasks.key1, state: 'needs_review',
        response: {kind: 'program-report-a3', a3_markdown: '# A3'}}};
      return {status: 'needs_review'};
    },
  };
  function element() {
    return {children: [], disabled: false, value: '', style: {}, href: '#',
      setAttribute() {}, appendChild(child) { this.children.push(child); },
      replaceChildren(...items) { this.children = items; },
      addEventListener(event, handler) { this['on' + event] = handler; },
      click() { return this.onclick && this.onclick(); }};
  }
  for (const id of ['session-label', 'start-note', 'confirm-note', 'generate-note',
                    'task-state', 'followup-result', 'check-note', 'proposal-result', 'state']) {
    nodes.set(id, element());
  }
  for (const id of ['create', 'start', 'confirm', 'generate', 'review-pass',
                    'followup', 'followup-confirm']) {
    nodes.set(id, element());
  }
  nodes.set('question', Object.assign(element(), {value: '分析2026-07'}));
  nodes.set('month', Object.assign(element(), {value: '2026-07'}));
  nodes.set('product', Object.assign(element(), {value: 'all'}));
  const focus = element(); focus.value = 'contrast';
  nodes.set('focus', focus);
  nodes.set('followup-text', Object.assign(element(), {value: '那上月呢？'}));
  const table = element();
  table.querySelector = () => ({replaceChildren(...items) { table.children = items; },
                                appendChild(child) { table.children.push(child); }});
  nodes.set('evidence-table', table);
  const exportLink = element();
  nodes.set('export-link', exportLink);
  const context = vm.createContext({
    URLSearchParams,
    window: {location: {search}, localStorage: {store: {}, getItem(k) { return this.store[k] || ''; },
                            setItem(k, v) { this.store[k] = v; }}},
    document: {getElementById: id => nodes.get(id),
               querySelector: sel => (sel.includes('tbody') ? table.querySelector() : element()),
               createElement: element},
    fetch: async (url, options) => {
      requested.push(url);
      requestBodies.push({url, body: options ? JSON.parse(options.body) : {}});
      const route = url.split('?')[0];
      if (route === '/api/session') {
        return {ok: true, json: async () => session};
      }
      const handler = responses[route];
      const body = options ? JSON.parse(options.body) : {};
      if (handler) {
        if (body.session_id && route !== '/api/session/create') {
          session = {...session, session_id: body.session_id};
        }
        const result = handler(body);
        return {ok: true, json: async () => ({...result, session: result.session || session})};
      }
      return {ok: false, json: async () => ({message: 'not found'})};
    },
    localStorage: null,
  });
  context.localStorage = context.window.localStorage;
  return {context, nodes, requested, requestBodies};
}

test('session flow: confirm gate, duplicate click, refresh recovery, export link', async () => {
  const {context, nodes, requested} = makeEnv();
  vm.runInContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  // Initial load without a session must not call session APIs.
  assert.deepEqual(requested, []);

  await nodes.get('create').onclick();
  assert.equal(requested[0], '/api/session/create');
  assert.equal(nodes.get('session-label').textContent, 'session-0123456789abcdef');

  // Starting a question stores a message and creates a server-side proposal;
  // no task or evidence query is allowed before confirmation.
  await nodes.get('start').onclick();
  assert.ok(requested.some(url => url === '/api/session/message'));
  assert.ok(requested.some(url => url === '/api/session/proposal'));
  assert.equal(requested.some(url => url === '/api/session/task/start'), false);

  // The evidence query is refused until the scope is confirmed: the stub
  // handler for task/evidence is only reached after the request call.
  const evidenceCalls = () => requested.filter(url => url === '/api/session/task/evidence').length;
  await nodes.get('confirm').onclick();
  assert.equal(evidenceCalls(), 1, 'evidence runs exactly once after confirmation');
  assert.ok(nodes.get('confirm-note').textContent.includes('证据已生成'));

  // Duplicate clicks never create a second task.
  await nodes.get('start').onclick();
  assert.ok(nodes.get('start-note').textContent.includes('不重复创建'));

  // Generate -> review -> exportable, then the export link appears.
  await nodes.get('generate').onclick();
  assert.equal(nodes.get('task-state').textContent, '待审阅');
  await nodes.get('review-pass').onclick();
  await nodes.get('review-pass').onclick();
  assert.equal(nodes.get('task-state').textContent, '已可导出');
  assert.equal(nodes.get('export-link').style.display, '');
  assert.ok(nodes.get('export-link').href.includes('/api/session/export?session_id='));

  // Refresh recovery: load() re-reads the session without duplicating links.
  await vm.runInContext('load()', context);
  assert.equal(nodes.get('export-link').style.display, '');
});

test('announcement session page sends server binding and selected products', async () => {
  const {context, nodes, requestBodies} = makeEnv(
    '?policy_id=notice-2025&doc_version=docver-1&candidate_digest=digest-1&month=2026-07&products=28046100,38180000');
  // Match actual HTML, which no longer contains these legacy controls.
  nodes.delete('month');
  nodes.delete('product');
  vm.runInContext(script, context);
  await nodes.get('create').onclick();
  await nodes.get('start').onclick();
  await nodes.get('confirm').onclick();
  const request = requestBodies.find(item => item.url === '/api/session/request');
  assert.equal(request.body.request.month, '2026-07');
  assert.deepEqual(request.body.request.products, ['28046100', '38180000']);
  assert.deepEqual(request.body.policy_binding, {
    policy_id: 'notice-2025', doc_version: 'docver-1', candidate_digest: 'digest-1'});
});
