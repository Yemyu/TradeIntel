// K3 page fixture: offline DOM/fetch double for the new-announcement path.
// This is mechanism coverage, not a real R2 migration or model evaluation.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto, createHash} = require('node:crypto');

const html = fs.readFileSync(path.join(__dirname, '../web/announcement-import.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const fieldNames = ['title', 'publication_date', 'effective_date', 'clock_24h', 'timezone',
  'entry_events', 'origin', 'hts_codes', 'rates', 'rate_meaning', 'conditions', 'exceptions', 'revisions'];

function makeEnv() {
  const nodes = new Map();
  const requested = [];
  const state = {docVersion: 'docver-synthetic-k3', submitted: false, enabled: false};
  const dynamicIds = new Map();
  function element(tag = 'div') {
    const node = {tagName: tag.toUpperCase(), children: [], value: '', textContent: '', disabled: false,
      style: {}, hidden: false, open: false,
      className: '', selected: false, appendChild(child) { this.children.push(child); },
      replaceChildren(...items) { this.children = items; },
      addEventListener(event, handler) { this['on' + event] = handler; },
      click() { return this.onclick && this.onclick(); }};
    let nodeId = '';
    Object.defineProperty(node, 'id', {get: () => nodeId,
      set: value => { nodeId = value; dynamicIds.set(value, node); }});
    return node;
  }
  ['policy-id', 'source-id', 'source-url', 'source-text'].forEach(id => nodes.set(id, element('input')));
  nodes.get('policy-id').value = 'policy-k3';
  nodes.get('source-id').value = 'notice:new:p1';
  nodes.get('source-url').value = 'https://official.example/notice';
  nodes.get('source-text').value = 'Synthetic Notice\nPublished 2024.\nEffective January 1, 2025.';
  nodes.set('doc-version', element('code'));
  nodes.set('fields', element('table'));
  const tbody = element('tbody');
  nodes.set('fields-tbody', tbody);
  ['import-note', 'candidate-note', 'coverage', 'rebind', 'saved-sections', 'source-provenance']
    .forEach(id => nodes.set(id, element()));
  ['reading-preview', 'reading-preview-note', 'reading-preview-items', 'document-details']
    .forEach(id => nodes.set(id, element()));
  nodes.set('reading-preview-file', element('input'));
  ['import', 'template', 'submit', 'enable', 'check-coverage', 'load-coverage'].forEach(id => nodes.set(id, element('button')));
  nodes.set('coverage-month', element('input')); nodes.get('coverage-month').value = '2025-01';
  nodes.set('coverage-codes', element('input')); nodes.get('coverage-codes').value = '28046100';
  nodes.set('research-link', element('a'));
  nodes.get('template').disabled = true; nodes.get('submit').disabled = true;
  nodes.get('enable').disabled = true; nodes.get('load-coverage').disabled = true;
  function findById(node, id) {
    if (!node) return null;
    if (node.id === id) return node;
    for (const child of node.children || []) {
      const found = findById(child, id); if (found) return found;
    }
    return null;
  }
  const responses = {
    '/api/announcements/import': () => ({status: 'registered_candidate', doc_version: state.docVersion,
      source_provenance: 'user_supplied_unverified'}),
    '/api/announcements/template': () => ({schema_version: 'announcement-candidate-template-v1', doc_version: state.docVersion,
      source_provenance: 'user_supplied_unverified', source_url: 'https://official.example/notice',
      sections: [
        {section_id: 'notice:new:p1:para1', text: 'Synthetic Notice\n'},
        {section_id: 'notice:new:p1:para2', text: 'Published 2024.\n'},
        {section_id: 'notice:new:p1:para3', text: 'Effective January 1, 2025.'},
      ],
      fields: fieldNames.map(field => ({field, status: 'unknown', value: null, reason: 'synthetic reason'}))}),
    '/api/announcements/submit': () => { state.submitted = true; return {status: 'candidate_ready', candidate_digest: 'digest-synthetic'}; },
    '/api/announcements/enable': () => { state.enabled = true; return {status: 'enabled', rebind_required: true,
      coverage: {trade_coverage: 'not_checked'}}; },
    '/api/announcements/coverage': () => ({coverage: {trade_coverage: 'not_checked'}}),
    '/api/announcements/coverage/check': () => ({coverage: {trade_coverage: 'exact'}}),
  };
  const context = vm.createContext({
    URLSearchParams,
    crypto: webcrypto,
    TextEncoder,
    document: {
      getElementById: id => nodes.get(id) || dynamicIds.get(id) || findById(tbody, id),
      querySelector: selector => selector === '#fields tbody' ? tbody : element(),
      createElement: tag => element(tag),
    },
    fetch: async (url, options) => {
      requested.push({url, body: options ? JSON.parse(options.body || '{}') : null});
      const route = url.split('?')[0];
      const handler = responses[route];
      if (!handler) return {ok: false, json: async () => ({message: 'not found'})};
      return {ok: true, json: async () => handler()};
    },
  });
  return {context, nodes, tbody, requested, state};
}

test('announcement page enforces import -> template -> submit -> enable -> coverage', async () => {
  const {context, nodes, tbody, requested, state} = makeEnv();
  vm.runInContext(script, context);
  await nodes.get('import').onclick();
  assert.equal(nodes.get('doc-version').textContent, state.docVersion);
  assert.equal(nodes.get('template').disabled, false);
  await nodes.get('template').onclick();
  const templateRequest = requested.find(item => item.url === '/api/announcements/template');
  assert.equal(Object.prototype.hasOwnProperty.call(templateRequest.body, 'fields'), false);
  assert.equal(tbody.children.length, fieldNames.length);
  assert.equal(nodes.get('saved-sections').children.length, 6);
  assert.match(nodes.get('source-provenance').textContent, /网址未核验/);
  assert.equal(nodes.get('submit').disabled, false);
  // dynamic controls are registered by the DOM double's id setter
  assert.ok(context.document.getElementById('status-0'), JSON.stringify(tbody.children));
  // Fill two known fields with exact locations and leave the rest explicitly unknown.
  context.document.getElementById('status-0').value = 'known';
  context.document.getElementById('value-0').value = 'Synthetic Notice';
  context.document.getElementById('section-0').value = 'notice:new:p1:para1';
  context.document.getElementById('quote-0').value = 'Synthetic Notice';
  context.document.getElementById('status-2').value = 'known';
  context.document.getElementById('value-2').value = '2025-01-01';
  context.document.getElementById('section-2').value = 'notice:new:p1:para3';
  context.document.getElementById('quote-2').value = 'Effective January 1, 2025.';
  // Enable is guarded by candidateReady; clicking before submit must not call its endpoint.
  await nodes.get('enable').onclick();
  assert.equal(requested.filter(item => item.url === '/api/announcements/enable').length, 0);
  await nodes.get('submit').onclick();
  assert.equal(state.submitted, true);
  assert.equal(nodes.get('enable').disabled, false);
  await nodes.get('enable').onclick();
  assert.equal(state.enabled, true);
  assert.equal(nodes.get('check-coverage').disabled, false);
  assert.match(nodes.get('coverage').textContent, /not_checked/);
  assert.match(nodes.get('rebind').textContent, /rebind_required/);
  await nodes.get('check-coverage').onclick();
  assert.match(nodes.get('coverage').textContent, /exact/);
  const coverageRequest = requested.find(item => item.url === '/api/announcements/coverage/check');
  assert.deepEqual(coverageRequest.body.requested_codes, ['28046100']);
  assert.equal(nodes.get('research-link').style.display, '');
  assert.match(nodes.get('research-link').href, /products=28046100/);
  await nodes.get('load-coverage').onclick();
  assert.equal(requested.filter(item => item.url.startsWith('/api/announcements/coverage')).length, 2);
});

test('conflicting field submits two exact section citations, not one', async () => {
  const {context, nodes, requested} = makeEnv();
  vm.runInContext(script, context);
  await nodes.get('import').onclick();
  await nodes.get('template').onclick();
  context.document.getElementById('status-0').value = 'conflict';
  context.document.getElementById('section-0').value = 'notice:new:p1:para1';
  context.document.getElementById('quote-0').value = 'Synthetic Notice';
  await nodes.get('submit').onclick();
  assert.equal(requested.filter(item => item.url === '/api/announcements/submit').length, 0);
  assert.match(nodes.get('candidate-note').textContent, /两条引文/);
  context.document.getElementById('add-evidence-0').click();
  context.document.getElementById('section-0-1').value = 'notice:new:p1:para2';
  context.document.getElementById('quote-0-1').value = 'Published 2024.';
  await nodes.get('submit').onclick();
  const request = requested.find(item => item.url === '/api/announcements/submit');
  assert.equal(request.body.fields[0].evidence.length, 2);
  assert.equal(request.body.fields[0].evidence[1].section_id, 'notice:new:p1:para2');
});

test('a selected paragraph can fill an exact quote but never confirms its meaning', async () => {
  const {context, nodes, requested} = makeEnv();
  vm.runInContext(script, context);
  await nodes.get('import').onclick();
  await nodes.get('template').onclick();
  assert.equal(context.document.getElementById('fields-tbody').children[0].children[0].textContent,
    '公告标题');
  const section = context.document.getElementById('section-0');
  assert.match(section.children[1].textContent, /Synthetic Notice/);
  context.document.getElementById('status-0').value = 'known';
  context.document.getElementById('value-0').value = 'Synthetic Notice';
  section.value = 'notice:new:p1:para1';
  context.document.getElementById('fill-quote-0').click();
  assert.equal(context.document.getElementById('quote-0').value, 'Synthetic Notice\n');
  assert.equal(nodes.get('enable').disabled, true);
  await nodes.get('submit').onclick();
  const submitted = requested.find(item => item.url === '/api/announcements/submit');
  assert.equal(submitted.body.fields[0].evidence[0].quote, 'Synthetic Notice\n');
  assert.equal(nodes.get('enable').disabled, false);
  section.value = 'notice:new:p1:para2';
  context.document.getElementById('fill-quote-0').click();
  assert.equal(context.document.getElementById('quote-0').value, 'Published 2024.\n');
  assert.equal(nodes.get('enable').disabled, true, 'a changed quote requires re-submission');
});

test('import sends the pasted notice text byte-for-byte without trimming whitespace', async () => {
  const {context, nodes, requested} = makeEnv();
  const original = '\n Official Notice\n\n';
  nodes.get('source-text').value = original;
  vm.runInContext(script, context);
  await nodes.get('import').onclick();
  assert.equal(requested.find(item => item.url === '/api/announcements/import').body.text, original);
});

test('offline reading notes show sourced claims but never fill or submit the form', async () => {
  const {context, nodes, requested} = makeEnv();
  vm.runInContext(script, context);
  await nodes.get('import').onclick();
  await nodes.get('template').onclick();
  assert.equal(nodes.get('reading-preview-file').disabled, false);
  const original = nodes.get('source-text').value;
  const digest = text => createHash('sha256').update(text).digest('hex');
  const notes = {schema_version: 'announcement-reading-suggestions-v2', status: 'review_only',
    doc_version: 'docver-synthetic-k3', source_sha256: digest(original),
    items: [
      {field: 'rate_meaning', status: 'known', reason: '', claims: [{
        text: '合成公告的税率需核对原文。', source_passages: [{passage_id: 'P1',
          start: 0, end: original.length, text: original, text_sha256: digest(original)}]}]},
      {field: 'conditions', status: 'unknown', reason: '合成原文没有完整条件', claims: []},
      {field: 'exceptions', status: 'unknown', reason: '合成原文没有例外', claims: []},
    ]};
  await context.renderReadingPreview(notes);
  assert.equal(nodes.get('reading-preview').hidden, false);
  assert.equal(nodes.get('reading-preview-items').children.length, 3);
  assert.equal(context.document.getElementById('value-9').value, '');
  assert.equal(nodes.get('enable').disabled, true);
  assert.equal(requested.filter(item => item.url === '/api/announcements/submit').length, 0);
  const detail = nodes.get('reading-preview-items').children[0].children[1];
  detail.children[1].click();
  assert.equal(nodes.get('document-details').open, true);
  notes.source_sha256 = '0'.repeat(64);
  await assert.rejects(context.renderReadingPreview(notes), /不一致/);
  assert.equal(nodes.get('reading-preview').hidden, true);
});
