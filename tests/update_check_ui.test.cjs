// F9 fixture: runs the real update-check page script against a DOM double.
// Verifies the page shows the persisted check time (never the version creation
// time) and that clicking check re-loads an updated status.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/update-check.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

test('update check page records checks and refreshes the displayed time', async () => {
  const nodes = new Map();
  const requested = [];
  let status = {status: 'ok', active_version: 'a'.repeat(64),
                last_checked: null, last_check_status: null,
                data_cutoff_month: '2026-07', month_count: 19, check_history: []};
  function element() {
    return {children: [], value: '', setAttribute() {},
            appendChild(child) { this.children.push(child); },
            replaceChildren(...items) { this.children = items; },
            addEventListener(event, handler) { this['on' + event] = handler; },
            click() { return this.onclick && this.onclick(); }};
  }
  for (const id of ['last-checked', 'last-check-status', 'cutoff', 'active-version',
                    'month-count', 'check-note', 'check']) nodes.set(id, element());
  const table = element();
  table.querySelector = () => ({replaceChildren(...items) { table.children = items; },
                                appendChild(child) { table.children.push(child); }});
  nodes.set('check-history', table);
  const context = vm.createContext({
    document: {getElementById: id => nodes.get(id),
               querySelector: sel => (sel.includes('tbody') ? table.querySelector() : element()),
               createElement: element},
    fetch: async (url, options) => {
      requested.push(url);
      if (url === '/api/update-status') return {ok: true, json: async () => status};
      if (url === '/api/update/check') {
        status = {...status, last_checked: '2026-09-16T00:30:00+00:00',
                  last_check_status: 'no_fetch_source',
                  check_history: [{checked_at: '2026-09-16T00:30:00+00:00',
                                   status: 'no_fetch_source'}]};
        return {ok: true, json: async () => ({status: 'no_fetch_source',
                                              message: '未配置真实抓取源；本轮仅记录检查时间，不做任何数据变更。'})};
      }
      return {ok: false, json: async () => ({})};
    }});
  vm.runInContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requested, ['/api/update-status']);
  assert.equal(nodes.get('last-checked').textContent, '从未检查');
  assert.equal(nodes.get('cutoff').textContent, '2026-07');
  await nodes.get('check').onclick();
  assert.ok(requested.includes('/api/update/check'));
  assert.equal(nodes.get('last-checked').textContent, '2026-09-16T00:30:00+00:00');
  assert.equal(nodes.get('last-check-status').textContent, 'no_fetch_source');
  assert.equal(table.children.length, 1, 'one persisted check entry rendered');
});
