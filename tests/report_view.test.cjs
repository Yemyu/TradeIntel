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
  return {render:context.TradeIntelReportView.renderTradeReport,build:context.TradeIntelReportView.buildTradeReportDocument,target,created};
}
const saved=JSON.parse(fs.readFileSync(path.join(__dirname,'../web/design-preview/cases/soybean-trade.json'),'utf8'));
test('real shared renderer reads the saved export and has no navigation/storage/network side effects',()=>{
  const e=environment(),report=saved.reports[1],before=JSON.stringify(report);
  const view={...saved.reader_view,facts:saved.reader_view.facts.filter(f=>f.report_id===report.report_id)};
  const title=e.render(e.target,report,{language:'en',readerView:view});
  assert.match(title,/exports/);assert.match(e.target.textContent,/889,379,312 USD/);
  assert.match(e.target.textContent,/18,789,570,646/);assert.match(e.target.textContent,/Monthly values table/);
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

function fixture(values,months=values.map((_,i)=>`2026-${String(i+1).padStart(2,'0')}`)){
  const series=values.map((value,i)=>({month:months[i],status:value===null?'unavailable':'observed',value_usd:value}));
  const complete=values.every(v=>v!==null),last=series.at(-1),prior=series.at(-2);
  return {kind:'trade-query-v1',report_id:'selected',question:'最近有什么变化？',
    scope:{flow:'import',product_code:'1201',product_label:'大豆',partner:'ALL_ORIGINS',start_month:months[0],end_month:months.at(-1)},series,
    summary:{latest_month:last.month,latest_value_usd:last.value_usd,previous_month:prior?.month??null,
      month_change_usd:prior?.value_usd!=null&&last.value_usd!=null?last.value_usd-prior.value_usd:null,
      complete_window:complete,period_total_usd:complete?values.reduce((a,b)=>a+b,0):null},sources:[],notes:[]};
}
test('saved real reports derive the same facts with or without optional explanation cards',()=>{
  const oil=JSON.parse(fs.readFileSync(path.join(__dirname,'../web/design-preview/cases/soybean-oil.json'),'utf8'));
  const all=[...saved.reports,...oil.reports],expected=[[46041287,354295547,49961609,16665347],
    [889379312,18789570646,2547423202,889379312],[152115,2120520,474347,37080],[27503913,204669591,30844293,8388794]];
  all.forEach((report,i)=>{const e=environment(),before=JSON.stringify(report),a=e.build(report).directions[0];
    assert.equal(a.issues.length,0);assert.deepEqual([a.latest,a.total,a.high,a.low],expected[i]);
    const withCards=structuredClone(report);withCards.explanation={observations:[{id:'import.trend',fact:'UNSUPPORTED STORY'}]};
    assert.equal(JSON.stringify(e.build(report)),JSON.stringify(e.build(withCards)));assert.equal(JSON.stringify(report),before);
    e.render(e.target,report,{language:'en'});assert.match(e.target.textContent,/Among observed months/);
    assert.ok(!e.target.textContent.includes('UNSUPPORTED STORY'));});
});
test('zero is observed, missing stays missing and latest missing never falls back',()=>{
  const e=environment(),r=fixture([12,0,null]),d=e.build(r).directions[0];
  assert.equal(d.issues.length,0);assert.equal(d.latest,null);assert.equal(d.total,null);assert.equal(d.delta,null);
  e.render(e.target,r,{language:'en'});assert.match(e.target.textContent,/No published value is available for 2026-03/);
  assert.match(e.target.textContent,/0 USD/);assert.equal(e.created.filter(n=>n.className==='trade-bar-fill').length,2);
  assert.ok(e.created.filter(n=>n.className==='trade-bar-fill').every(n=>!n.style.width.includes('NaN')));
});
test('single month and flat series do not invent movement',()=>{
  const e=environment(),one=e.build(fixture([0])).directions[0],flat=e.build(fixture([7,7,7])).directions[0];
  assert.equal(one.latest,0);assert.equal(one.delta,null);assert.equal(one.run,null);assert.equal(one.yearPeak,null);
  assert.equal(flat.delta,0);assert.equal(flat.run,null);assert.equal(flat.turn,null);
});
test('ties preserve every month and recent runs count changes, not months',()=>{
  const e=environment(),r=fixture([3,1,3]),d=e.build(r).directions[0];
  assert.equal(d.highMonths.join(','),'2026-01,2026-03');assert.equal(d.turn.sign,1);
  const run=e.build(fixture([1,2,3,4])).directions[0].run;assert.equal(run.changes,3);
});
test('missing months and year boundaries cannot be bridged into recent movement',()=>{
  const e=environment();
  for(const r of [fixture([1,null,3]),fixture([1,2,3],['2025-11','2025-12','2026-01']),fixture([1,2],['2026-01','2026-03'])]){
    const d=e.build(r).directions[0];assert.equal(d.run,null);assert.equal(d.turn,null);assert.equal(d.delta,null);}
});
test('invalid amount, order and summary conflicts withhold derived comparisons without changing input',()=>{
  const changes=[r=>r.series[0].value_usd='1',r=>r.series[0].value_usd=-1,r=>r.series[0].value_usd=Number.MAX_SAFE_INTEGER+1,
    r=>r.series[0].month=r.series[1].month,r=>r.summary.period_total_usd=999,r=>r.summary.latest_value_usd=999,
    r=>r.summary.month_change_usd=999,r=>r.series.reverse(),r=>r.series[0].status='invented'];
  for(const change of changes){const e=environment(),r=fixture([1,2,3]);change(r);const before=JSON.stringify(r),d=e.build(r).directions[0];
    assert.ok(d.issues.length);assert.equal(d.high,null);assert.equal(d.total,null);assert.equal(d.delta,null);
    e.render(e.target,r,{language:'en'});assert.match(e.target.textContent,/Comparisons are withheld/);assert.equal(JSON.stringify(r),before);}
});
test('a selected report cannot inherit other reports facts or unbound policy context',()=>{
  const e=environment(),r=fixture([1,2]),view={facts:[{report_id:'other',text:'LEAK 987,654',text_en:'LEAK 987,654'}],
    policy:{status:'candidate_evidence',evidence_bundles:[]},unanswered:[{text:'OTHER QUERY',text_en:'OTHER QUERY'}]};
  const d=e.build(r,{readerView:view});assert.equal(d.selectedFacts.length,0);assert.equal(d.policy,null);
  e.render(e.target,r,{language:'en',readerView:view});assert.ok(!e.target.textContent.includes('LEAK'));assert.ok(!e.target.textContent.includes('OTHER QUERY'));
});
test('matching policy retains candidate or incomplete status and never becomes applicability',()=>{
  for(const status of ['candidate_evidence','partial','no_evidence','incomplete_required_context']){
    const e=environment(),r=fixture([1,2]),view={facts:[{report_id:r.report_id,text:'repeated',text_en:'repeated'}],
      policy:{status,evidence_bundles:[{hit:{text:'<script>TEXT ONLY</script>',url:'https://evil.test/'},required_context:[]}]},unanswered:[]};
    e.render(e.target,r,{language:'en',readerView:view});assert.match(e.target.textContent,/Policy evidence from this search/);
    assert.ok(!e.created.some(n=>n.tag==='script'||n.href==='https://evil.test/'));assert.ok(!e.target.textContent.includes('repeated'));}
});
