const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../web/design-preview/index.html'),'utf8');
const home=html.slice(html.indexOf('<section id="home"'),html.indexOf('<section id="workspace"'));
test('homepage explains capabilities, responsibility, data, implementation, tests and installation',()=>{
  for(const id of ['project-capabilities','project-workflow','project-data','project-stack','project-tests','project-start']){
    assert.ok(home.includes('id="'+id+'"'),id);
  }
  for(const phrase of ['贸易研究 Agent','Python','CSV + JSON','MySQL','BM25','48个','连续12个月','不是另一个中国海关数据源']){
    assert.ok(home.includes(phrase),phrase);
  }
  assert.equal((home.match(/<dt/g)||[]).length,6);
  assert.equal((home.match(/<span class="step-number"/g)||[]).length,4);
});
test('international project identity separates current US coverage from future expansion',()=>{
  assert.match(home,/<h1 data-en="International trade<br><em>research assistant<\/em>">国际贸易/);
  assert.match(home,/class="data-scope-label" data-en="Current data: U.S. imports and exports · through July 2026"/);
  assert.match(home,/当前数据：美国进出口 · 截至2026年7月/);
  assert.match(home,/后续考虑加入中国及其他国家的数据/);
  assert.match(home,/Future work may add datasets from China and other countries/);
  assert.doesNotMatch(home,/美国贸易研究助手|U.S. trade<br>/);
  const app=fs.readFileSync(path.join(__dirname,'../web/design-preview/app.js'),'utf8');
  assert.match(app,/home:tr\('国际贸易研究助手','International trade research assistant'\)/);
  assert.match(app,/report:tr\('美国钨与光伏材料进口情况'/);
});
test('workflow explains model feedback decisions separately from program calculation',()=>{
  const workflow=home.slice(home.indexOf('id="project-workflow"'),home.indexOf('id="project-data"'));
  for(const phrase of ['读取工具返回的结果','根据结果继续','本轮报告与引用','第3步会回到第2步','不是模型自由撰写的经济分析','Read the results and decide whether','step 3 returns to step 2']){
    assert.ok(workflow.includes(phrase),phrase);
  }
  assert.match(workflow,/<small data-en="Model">模型<\/small><h3 data-en="Decide the next step">/);
  for(const [file,title,coverage] of [
    ['README.md','International trade research assistant','The current release includes U.S. import and export data'],
    ['README.zh-CN.md','国际贸易研究助手','当前版本收录美国进出口数据']
  ]){
    const content=fs.readFileSync(path.join(__dirname,'..',file),'utf8');
    assert.ok(content.includes(title));assert.ok(content.includes(coverage));
  }
});
test('homepage routes readers to cases without duplicating case cards or report entry points',()=>{
  assert.equal((home.match(/href="#cases"/g)||[]).length,1);
  assert.doesNotMatch(home,/href="[^"]*#report"|class="featured"|case-gallery|case-tile/);
  assert.match(home,/href="#workspace" data-local-only hidden/);
  assert.match(home,/data-href-en="[^"]*README.md#quickstart"/);
  assert.match(home,/data-href-en="[^"]*MODEL_SELECTION.md"/);
});
test('homepage preserves the five published model configurations and their report counts',()=>{
  const results=home.slice(home.indexOf('class="project-table model-results"'),home.indexOf('</table>',home.indexOf('class="project-table model-results"')));
  assert.equal((results.match(/scope="row"/g)||[]).length,5);
  for(const name of ['GPT-6.1 Sol · Low','GPT-6.1 Sol · Medium','GPT-6 Luna · Max','DeepSeek-V4.1 Flash · high','GLM-5.3-Flash · High'])assert.ok(results.includes(name));
  for(const count of ['9/9','10/10','8/8','14/14'])assert.ok(results.includes(count));
});
test('case categories share the same default style; only selection changes the background',()=>{
  const css=fs.readFileSync(path.join(__dirname,'../web/design-preview/style.css'),'utf8');
  assert.doesNotMatch(css,/\.case-picker-group:nth-child\([^)]*\) \.case-tab/);
  assert.match(css,/\.case-tab\[aria-current\]\{[^}]*background:#e9eddf/);
  assert.doesNotMatch(home,/全部伙伴汇总及中国|汇总，以及中国|All-partner totals and China|combined, and China/);
});
