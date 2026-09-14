// Runs the actual page script with a small DOM double; no browser or network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../web/interpretation-review.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

test('an approved record becoming stale loses its link and cannot label new notes', async () => {
  const nodes = new Map();
  function element() {
    return {children: [], disabled: false, value: '', checked: false, textContent: '',
      set id(value) { nodes.set(value, this); },
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      setAttribute() {}, addEventListener(event,handler) {this[event]=handler;}};
  }
  for (const id of ['export','record','save','notes','status','boundary','reviewer','facts','source-link','run-label','revise','cancel-revision','change-box','change-reason','history']) nodes.set(id, element());
  let response = {status:'recorded', revision:1,review_digest:'base-digest',notes:[{text:'old note',fact_ids:['a']}],
    decision:{reviewer:'fixture',facts_checked:true,eligible_for_reviewed_draft:true,
      decisions:[{verdict:'accept',reason:'old evidence'}]}};
  nodes.set('data-report', element());
  response.data_report={status:'bound',url:'/api/version-report?version='+'a'.repeat(64),message:'同版本背景'};
  const run='exposure-20260914T120000-abcdef12';
  const requested=[];let submitted;
  const context = vm.createContext({URLSearchParams,window:{location:{search:'?run_id='+run}},
    document:{getElementById:id=>nodes.get(id),createElement:element},
    confirm:()=>true,
    fetch:async (url,options)=>{requested.push(url);if(options)submitted=JSON.parse(options.body);return {ok:true,json:async()=>response};}});
  vm.runInContext(script, context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(nodes.get('export').children.length, 1);
  assert.equal(nodes.get('data-report').children[0].href,response.data_report.url);
  assert.equal(requested[0],'/api/saved-interpretation-review?run_id='+run);
  assert.equal(nodes.get('export').children[0].href,'/api/saved-interpretation-draft?run_id='+run);
  assert.equal(nodes.get('source-link').href,'/api/research-artifact/'+run+'/source-packet.zh-CN.md');
  await vm.runInContext('load()', context);
  assert.equal(nodes.get('export').children.length, 1, 'refresh must not duplicate download links');
  nodes.get('revise').click();
  assert.equal(nodes.get('facts').checked,false,'revision requires fresh fact confirmation');
  assert.equal(nodes.get('reason-0').disabled,false);
  nodes.get('change-reason').value='核查后调整';
  nodes.get('facts').checked=true;
  await nodes.get('save').click();
  assert.equal(submitted.base_review_digest,'base-digest');
  assert.equal(submitted.change_reason,'核查后调整');
  response = {...response,status:'stale',notes:[{text:'changed note',fact_ids:['b']}]};
  await vm.runInContext('load()', context);
  assert.equal(nodes.get('export').children.length, 0);
  assert.equal(nodes.get('notes').children.length, 0, 'old acceptance must not be paired with changed text');
  assert.equal(nodes.get('save').disabled, true);
  assert.equal(nodes.get('facts').checked, false);
  assert.match(nodes.get('record').textContent, /旧版本记录/);
});
