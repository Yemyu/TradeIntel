const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/design-preview/report-view.js'),'utf8');
function environment(){
  const created=[];
  const document={createElement(tag){const el={tag,children:[],style:{},append(...nodes){this.children.push(...nodes);},
    get textContent(){return (this.text||'')+this.children.map(c=>c.textContent).join('');},set textContent(text){this.text=String(text);this.children=[];}};created.push(el);return el;}};
  const context=vm.createContext({document,fetch(){throw Error('No network allowed');},
    localStorage:{setItem(){throw Error('No storage writes allowed');}},location:Object.freeze({hash:'#cases'})});
  vm.runInContext(source,context);const target=document.createElement('article');
  return {render:context.TradeIntelReportView.renderTradeReport,target,created};
}
const saved=JSON.parse(fs.readFileSync(path.join(__dirname,'../web/design-preview/cases/soybean-trade.json'),'utf8'));
test('real shared renderer reads the saved export and has no navigation/storage/network side effects',()=>{
  const e=environment(),report=saved.reports[1],before=JSON.stringify(report);
  const view={...saved.reader_view,facts:saved.reader_view.facts.filter(f=>f.report_id===report.report_id)};
  const title=e.render(e.target,report,{language:'en',readerView:view});
  assert.match(title,/exports/);assert.match(e.target.textContent,/889,379,312 USD/);
  assert.match(e.target.textContent,/18,789,570,646 USD/);assert.match(e.target.textContent,/Monthly values table/);
  assert.equal(e.created.filter(n=>n.tag==='tr').length,13);assert.equal(JSON.stringify(report),before);
  assert.ok(!e.created.some(n=>['script','input','button'].includes(n.tag)));
});
test('language changes presentation but preserve all saved bar amounts',()=>{
  for(const language of ['zh','en']){const e=environment();e.render(e.target,saved.reports[0],{language});
    for(const row of saved.reports[0].series)assert.ok(e.target.textContent.includes(row.value_usd.toLocaleString('en-US')));
    assert.match(e.target.textContent,/354,295,547/);
  }
});
test('combined report retains both directions and the non-subtraction boundary',()=>{
  const e=environment();const combined={...saved.reports[0],kind:'trade-query-both-v1',
    scope:{...saved.reports[0].scope,flow:'both'},import_report:saved.reports[0],export_report:saved.reports[1]};
  e.render(e.target,combined,{language:'en'});
  assert.match(e.target.textContent,/Do not subtract/);assert.match(e.target.textContent,/46,041,287/);assert.match(e.target.textContent,/889,379,312/);
});
test('strings are rendered as plain text, and unknown report kinds are refused',()=>{
  const e=environment();const report=structuredClone(saved.reports[0]);report.question='<img src=x onerror=alert(1)>';
  e.render(e.target,report);assert.ok(e.target.textContent.includes(report.question));assert.ok(!e.created.some(n=>n.tag==='img'));
  assert.throws(()=>e.render(e.target,{kind:'fixture'}),/Unsupported saved report/);
});
test('heading scope notes show in single-month imports and short exports in both languages',()=>{
  for(const flow of ['import','export'])for(const language of ['zh','en']){
    const e=environment(),report=structuredClone(saved.reports[flow==='import'?0:1]);
    report.scope.coverage_note='4001包括其他天然胶。出口短期间提示保留。';
    report.scope.coverage_note_en='Heading 4001 includes other natural gums. Short export coverage retained.';
    if(flow==='import')report.series=report.series.slice(-1);
    e.render(e.target,report,{language});
    assert.match(e.target.textContent,language==='en'?/includes other natural gums/:/包括其他天然胶/);
  }
});
