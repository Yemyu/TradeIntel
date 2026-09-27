import createGlobe from './vendor/cobe.mjs';

const $ = id => document.getElementById(id);
if (location.pathname.startsWith('/preview')) {
  const updates = [
    ['.hero-note','可查询已发布的美国进出口数据，出口数据目前连续到2026年7月。政策案例另附公告背景。','Published US imports and exports are queryable. Export data currently runs through July 2026. The policy case also includes notice context.'],
    ['#home .section-heading > p','本地服务可查询已接入的商品数据；下方案例仍是示例。','The local service can query supported trade data; the case below remains a sample.'],
    ['#workspace .eyebrow','本地研究工作台','LOCAL WORKSPACE'],
    ['#workspace .composer>p:not(.eyebrow)','输入商品名称或编码；确认范围后，查看已发布的数据与图表。部分日常名称可能需要补充编码。','Enter a product name or code, confirm its scope, then view published data and charts. Some everyday names may need a product code.'],
    ['.compose-bottom>span','数据报告不用模型；模型解读是试用功能，回答请核对，调用可能产生费用。','The data report works without a model. Model explanations are experimental; check them before use. Calls may incur charges.'],
    ['#question-form button[type=submit]','查询可用范围 ↗','Check the available scope ↗'],
    ['.suggestions button[data-question]','最近美国大豆出口有什么变化？','How have recent U.S. soybean exports changed?'],
    ['.nav nav a[href="#report"]','报告','Report'],
    ['.footer small','本地运行 · 2026','Local service · 2026']
  ];
  for (const [selector,zh,en] of updates) {
    const element=document.querySelector(selector);
    if(element){element.textContent=zh;element.dataset.en=en;}
  }
}
// Keep the case direction legible even when globe markers rotate out of view.
const lead = document.querySelector('.hero .lead');
lead.textContent = '查询美国商品贸易数据；涉及已登记政策时，再查看公告背景。';
lead.dataset.en = 'Explore US merchandise trade data and, where available, related policy notices.';
const direction = document.querySelector('.tag-one');
direction.innerHTML = '<span class="route-point"></span>中国 <span aria-hidden="true">⟶</span> 美国<span class="route-point"></span>';
direction.dataset.en = '<span class="route-point"></span>China <span aria-hidden="true">⟶</span> United States<span class="route-point"></span>';
const caption = document.querySelector('.globe-caption');
caption.textContent = '案例方向示意：中国出口，美国进口。非实时货运。';
caption.dataset.en = 'Case direction: exports from China to the US. Not live shipping.';
let language = 'zh';
try { language = localStorage.getItem('tradeintel-preview-language') === 'en' ? 'en' : 'zh'; } catch {}
let rows = [];
const tr = (zh,en) => language === 'en' ? en : zh;
const translations = [...document.querySelectorAll('[data-en]')].map(el=>({el,zh:el.innerHTML,en:el.dataset.en}));
function applyLanguage() {
  translations.forEach(({el,zh,en})=>{el.innerHTML=language==='en'?en:zh;});
  document.documentElement.lang=language==='en'?'en':'zh-CN';
  $('language-toggle').textContent=tr('English','中文');
  $('language-toggle').setAttribute('aria-label',tr('Switch to English','切换到中文'));
  $('question').placeholder=tr('例如：最近美国大豆出口有什么变化？','For example: How have recent U.S. soybean exports changed?');
  $('question-feedback').textContent='';
  motionLabel(); route(); if(rows.length)render(rows);
  window.dispatchEvent(new Event('tradeintel:language'));
}
$('language-toggle').addEventListener('click',()=>{language=language==='zh'?'en':'zh';try{localStorage.setItem('tradeintel-preview-language',language);}catch{} applyLanguage();});
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let paused = reduced.matches;
let page = 'home';
function route() {
  page = ['home', 'workspace', 'report'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'home';
  document.querySelectorAll('.page').forEach(node => { node.hidden = node.id !== page; });
  document.querySelectorAll('.nav nav a').forEach(a => {
    if(a.hash === '#' + page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  document.title = `${page==='report' && window.tradeintelLiveReportTitle
    ? window.tradeintelLiveReportTitle
    : {home:tr('贸易政策与数据','Trade policy and data'),workspace:tr('工作台','Workspace'),report:tr('美国钨与光伏材料进口情况','US imports of tungsten and solar materials')}[page]} · TradeIntel`;
  window.scrollTo({top:0,left:0,behavior:'instant'});
}
addEventListener('hashchange', route); route();
document.querySelectorAll('[data-scroll]').forEach(a => a.addEventListener('click', e => {
  e.preventDefault(); $(a.dataset.scroll).scrollIntoView({behavior:reduced.matches?'instant':'smooth'});
}));
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => {
  $('question').value = tr(button.dataset.question,'How are US imports of tungsten and solar materials doing?'); $('question').focus();
}));
$('question-form').addEventListener('submit', event => {
  event.preventDefault();
  if (location.pathname.startsWith('/preview')) return;
  if (!$('question').value.trim()) { $('question-feedback').textContent = tr('请先输入问题，或选择示例。','Enter a question or choose the example.'); return; }
  $('question-feedback').textContent = tr('下面显示已有示例，不是对这个问题的新回答。','The saved example below is not a new answer to your question.');
  $('scope-preview').hidden = false; $('scope-preview').scrollIntoView({behavior:reduced.matches?'instant':'smooth',block:'center'});
});
$('print-report').addEventListener('click', () => window.print());

let phi = 0.8;
let globeInstance = null;
function initGlobe() {
  if (globeInstance || page !== 'home') return;
  try {
  const size = () => Math.round(($('globe').getBoundingClientRect().width || 500) * Math.min(devicePixelRatio,2));
  globeInstance = createGlobe($('globe'), {
    devicePixelRatio:Math.min(devicePixelRatio,2),width:size(),height:size(),phi,theta:0.25,
    dark:0,diffuse:1.3,mapSamples:18000,mapBrightness:2.8,baseColor:[0.23,0.40,0.33],
    markerColor:[0.58,0.74,0.25],glowColor:[0.965,0.965,0.94],scale:1.02,
    markers:[{location:[38,-97],size:0.07},{location:[35,104],size:0.065}],
    onRender:state=> {if(!paused&&page==='home'&&!document.hidden) phi+=0.002;state.phi=phi;if(page==='home'){state.width=size();state.height=size();}}
  });
  addEventListener('pagehide', () => globeInstance?.destroy(), {once:true});
  } catch (error) {
  $('globe').hidden = true; document.querySelector('.globe-fallback').hidden = false;
  $('motion-toggle').hidden = true;
  }
}
addEventListener('hashchange',()=>{if(page==='home')initGlobe();});
if(page==='home')initGlobe();
function motionLabel() {$('motion-toggle').textContent=paused?tr('播放动效','Play animation'):tr('暂停动效','Pause animation');$('motion-toggle').setAttribute('aria-pressed',String(paused));}
$('motion-toggle').addEventListener('click',()=>{paused=!paused;motionLabel();});
reduced.addEventListener('change',()=>{paused=reduced.matches;motionLabel();});motionLabel();

function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
const fmt = value => Number(value).toLocaleString(language==='en'?'en-US':'zh-CN');
const svgNS='http://www.w3.org/2000/svg';
function svgEl(tag,attrs,text){const el=document.createElementNS(svgNS,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));if(text!==undefined)el.textContent=text;return el;}
function render(rows) {
  const filtered = rows.filter(row=>row.product===$('product').value);
  const latest=filtered.at(-1); const share=latest.world ? latest.china/latest.world*100 : null;
  $('metrics').replaceChildren();
  [[tr('全部来源进口额','All sources'),(latest.world/1e6).toFixed(2),tr('百万美元','USD million')],[tr('中国来源进口额','From China'),(latest.china/1e6).toFixed(2),tr('百万美元','USD million')],[tr('中国来源份额','China share'),share===null?tr('未知','Unknown'):share.toFixed(2)+'%',tr('同商品 · 同月份','Same product and month')]].forEach(([label,value,unit])=>{
    const card=node('div');card.append(node('small',label),node('strong',value),node('span',unit));$('metrics').append(card);
  });
  const name=$('product').selectedOptions[0].textContent;
  $('product-explanation').textContent=tr(`2026年7月，美国进口的${name}金额为${fmt(latest.world)}美元，其中来自中国的金额为${fmt(latest.china)}美元。这两项金额采用相同商品和月份范围：中国来源已经包含在全部来源中，不能再把两者相加。下图列出这类商品各月的金额，便于查看规模。`,`In July 2026, US imports of ${name.toLowerCase()} totalled $${fmt(latest.world)}, including $${fmt(latest.china)} from China. The China figure is part of the total, not an additional amount. The chart below shows the stored value for each month.`);
  $('share-explanation').textContent=share===null?tr('该月总额为零，不能计算份额。','The total is zero, so a share cannot be calculated.'):tr(`每100美元的这类商品进口中，约${share.toFixed(2)}美元来自中国，其余约${(100-share).toFixed(2)}美元来自其他来源。这按金额计算，不代表进口数量占比。`,`Of every $100 imported in this category, about $${share.toFixed(2)} came from China and $${(100-share).toFixed(2)} from other sources. This is a value share, not a quantity share.`);
  const svg=svgEl('svg',{viewBox:'0 0 700 260','aria-hidden':'true'});
  const maximum=Math.max(...filtered.map(row=>row.world))*1.18;
  for(let i=0;i<=3;i++){const y=210-i*57;svg.append(svgEl('line',{x1:45,y1:y,x2:685,y2:y,stroke:'#e6e9e2','stroke-dasharray':i?'3 5':'none'}),svgEl('text',{x:35,y:y+4,'text-anchor':'end',fill:'#879087','font-size':10},(maximum*i/3/1e6).toFixed(1)));}
  filtered.forEach((row,i)=>{const x=77+i*103;const height=row.world/maximum*171;const bar=svgEl('rect',{x,y:210-height,width:47,height,rx:3,fill:i===5?'#b7d779':'#315f51',tabindex:0});bar.append(svgEl('title',{},`${row.period}: ${fmt(row.world)} USD`));svg.append(bar,svgEl('text',{x:x+23.5,y:201-height,'text-anchor':'middle',fill:'#315f51','font-size':11},(row.world/1e6).toFixed(2)),svgEl('text',{x:x+23.5,y:237,'text-anchor':'middle',fill:'#879087','font-size':11},tr(row.period.slice(5)+'月',['Feb','Mar','Apr','May','Jun','Jul'][i])));});
  $('monthly-chart').replaceChildren(svg);$('monthly-chart').setAttribute('aria-label',tr(`${name}2026年2月至7月全部来源进口金额。完整数值见下方表格。`,`${name}: imports from all sources, February–July 2026. Exact values are in the table below.`));
  const donut=node('div',undefined,'donut');donut.style.background=`conic-gradient(#315f51 0 ${share??0}%,#e9eddf ${share??0}% 100%)`;
  const inside=node('div');inside.append(node('strong',share===null?tr('未知','Unknown'):share.toFixed(2)+'%'),node('small',tr('中国来源','China')));donut.append(inside);
  const legend=node('div',undefined,'donut-legend');[tr('中国来源','China'),tr('其他来源','Other sources')].forEach(t=>{const s=node('span');s.append(node('i'),document.createTextNode(t));legend.append(s);});
  $('share-chart').replaceChildren(donut,legend);$('share-chart').setAttribute('aria-label',tr(`${name}2026年7月中国来源份额${share?.toFixed(2)??'未知'}%`,`${name}: July 2026 share from China ${share?.toFixed(2)??'unknown'} percent`));
  $('data-table').replaceChildren();filtered.forEach(row=>{const rowNode=node('tr');[row.period,fmt(row.world),fmt(row.china),row.world?(row.china/row.world*100).toFixed(2)+'%':tr('未知','Unknown')].forEach(value=>rowNode.append(node('td',value)));$('data-table').append(rowNode);});
}
applyLanguage();
try {const response=await fetch('data.json');if(!response.ok)throw Error('Data unavailable');const data=await response.json();rows=data.rows;render(rows);$('product').addEventListener('change',()=>render(rows));}
catch(error){$('metrics').textContent=tr('示例数据暂时无法载入，请通过本地预览服务器打开。','Example data could not be loaded. Open this page through the local preview server.');}
