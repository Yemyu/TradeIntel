/* Pure reading view of saved facts. No model calls or storage writes. */
(() => {
  const amount=v=>Number.isSafeInteger(v)&&v>=0;
  const month=v=>typeof v==='string'&&/^\d{4}-(0[1-9]|1[0-2])$/.test(v);
  const index=v=>Number(v.slice(0,4))*12+Number(v.slice(5));
  const adjacent=(a,b)=>month(a)&&month(b)&&index(b)-index(a)===1;
  const pair=(a,b)=>adjacent(a.month,b.month)&&a.month.slice(0,4)===b.month.slice(0,4)
    &&a.status==='observed'&&b.status==='observed'&&amount(a.value_usd)&&amount(b.value_usd);
  function projectDirection(report){
    const {scope,summary={},series=[]}=report,issues=[];
    const valid=Array.isArray(series)&&series.every((r,i)=>month(r.month)&&(i===0||index(r.month)>index(series[i-1].month))
      &&(r.status==='observed'?amount(r.value_usd):['missing','unavailable','not_processed'].includes(r.status)&&r.value_usd===null));
    if(!valid)issues.push('rows');
    const rows=valid?series.map(r=>({...r})):[],observed=rows.filter(r=>r.status==='observed'),last=rows.at(-1),previous=rows.at(-2);
    const scopeValid=month(scope.start_month)&&month(scope.end_month)&&index(scope.start_month)<=index(scope.end_month)
      &&rows.every(r=>index(r.month)>=index(scope.start_month)&&index(r.month)<=index(scope.end_month));
    if(!scopeValid)issues.push('scope');
    const latestValid=scopeValid&&last?.month===scope.end_month&&summary.latest_month===last.month
      &&summary.latest_value_usd===(last.status==='observed'?last.value_usd:null);
    if(!latestValid)issues.push('latest');
    const delta=latestValid&&previous&&pair(previous,last)?last.value_usd-previous.value_usd:null;
    if(delta!==null&&(summary.month_change_usd!==delta||summary.previous_month!==previous.month))issues.push('change');
    const complete=scopeValid&&rows.length>0&&rows[0].month===scope.start_month&&last.month===scope.end_month
      &&rows.every((r,i)=>r.status==='observed'&&(i===0||adjacent(rows[i-1].month,r.month)));
    const sum=complete?rows.reduce((v,r)=>v+r.value_usd,0):null;
    const total=complete&&Number.isSafeInteger(sum)&&summary.complete_window===true&&summary.period_total_usd===sum?sum:null;
    if(summary.period_total_usd!=null&&total===null)issues.push('total');
    const safe=issues.length===0,high=safe&&observed.length?Math.max(...observed.map(r=>r.value_usd)):null,
      low=safe&&observed.length?Math.min(...observed.map(r=>r.value_usd)):null;
    let run=null,turn=null,yearPeak=null;
    if(safe&&delta!==null&&delta!==0){const sign=Math.sign(delta);let changes=0;
      for(let i=rows.length-1;i>0;i--){if(!pair(rows[i-1],rows[i])||Math.sign(rows[i].value_usd-rows[i-1].value_usd)!==sign)break;changes++;}
      if(changes>=2)run={changes,sign,start:rows[rows.length-1-changes].month,end:last.month};
      const earlier=rows.at(-3);
      if(earlier&&pair(earlier,previous)){const old=Math.sign(previous.value_usd-earlier.value_usd);
        if(old!==0&&old!==sign)turn={months:[earlier.month,previous.month,last.month],sign};}
    }
    if(safe&&last?.status==='observed'){const year=last.month.slice(0,4),sameYear=observed.filter(r=>r.month.startsWith(year+'-'));
      if(sameYear.length>=2){const peak=Math.max(...sameYear.map(r=>r.value_usd));
        yearPeak={year,months:sameYear.filter(r=>r.value_usd===peak).map(r=>r.month),gap:peak-last.value_usd};}}
    return {scope:{...scope},rows,issues,latestMonth:summary.latest_month,latest:safe&&latestValid?summary.latest_value_usd:null,
      delta:safe?delta:null,previousMonth:previous?.month,total:safe?total:null,high,low,
      highMonths:observed.filter(r=>r.value_usd===high).map(r=>r.month),lowMonths:observed.filter(r=>r.value_usd===low).map(r=>r.month),run,turn,yearPeak};
  }
  function buildTradeReportDocument(result,{readerView=null}={}){
    if(!['trade-query-v1','trade-query-both-v1'].includes(result?.kind)||!result.scope)throw Error('Unsupported saved report');
    const parts=result.kind==='trade-query-both-v1'?[result.import_report,result.export_report]:[result];
    if(parts.some(p=>!p?.scope))throw Error('Unsupported saved report');
    const selectedFacts=(readerView?.facts||[]).filter(f=>result.report_id&&f.report_id===result.report_id);
    return {directions:parts.map(projectDirection),selectedFacts,policy:selectedFacts.length?readerView?.policy:null,
      unanswered:selectedFacts.length?(readerView?.unanswered||[]):[]};
  }
  function renderTradeReport(target,result,{language='zh',readerView=null}={}){
    const doc=buildTradeReportDocument(result,{readerView}),english=language==='en',tr=(zh,en)=>english?en:zh,
      fmt=v=>v.toLocaleString(english?'en-US':'zh-CN');
    const make=(tag,text,className)=>{const el=(target.ownerDocument||document).createElement(tag);
      if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
    const p=(parent,text)=>parent.append(make('p',text)),scope=result.scope;
    const direction=scope.flow==='both'?tr('进出口','imports and exports'):scope.flow==='export'?tr('出口','exports'):tr('进口','imports');
    const product=english?(scope.official_product_en||`product group ${scope.product_code}`):(scope.product_label||scope.product_code);
    const title=tr(`美国${product}${direction}情况`,`U.S. ${direction} · ${product}`);
    target.append(make('p',tr('美国贸易数据','U.S. trade data'),'eyebrow'),make('h1',title));
    if(result.question&&!english)p(target,`提问：${result.question}`);
    p(target,tr(`${scope.start_month} 至 ${scope.end_month} · ${scope.product_code} 商品组`,`${scope.start_month} to ${scope.end_month} · product group ${scope.product_code}`));
    if(result.kind==='trade-query-both-v1')p(target,tr('进口与出口采用不同口径，分别展示，不相减计算贸易差额。',
      'Imports and exports use different statistical bases and are shown separately. Do not subtract these values and call the difference a trade balance.'));
    doc.directions.forEach((d,i)=>{
      const part=result.kind==='trade-query-both-v1'?[result.import_report,result.export_report][i]:result,s=d.scope,ex=s.flow==='export';
      const metric=tr(ex?'商品总出口额（FAS）':'消费进口额',ex?'total exports (FAS)':'imports for consumption');
      const partner=tr(s.partner==='CHINA'?(ex?'向中国':'从中国'):(ex?'向全部目的地':'从全部来源'),
        s.partner==='CHINA'?(ex?'to China':'from China'):(ex?'to all destinations':'from all origins'));
      const block=make('section',undefined,'trade-report-direction');
      block.append(make('h2',tr(`美国${ex?'出口':'进口'} · ${s.product_code} 商品组`,`U.S. ${ex?'exports':'imports'} · product group ${s.product_code}`)));
      const intro=make('section',undefined,'live-section trade-overview');intro.append(make('h3',tr('数据概览','Overview')));
      if(d.issues.length)p(intro,tr('保存的摘要与月份数据未能核对一致，暂不生成比较结论。请核对下方记录。',
        'The saved summary could not be reconciled with the monthly records. Comparisons are withheld; check the records below.'));
      else p(intro,d.latest===null?tr(`${d.latestMonth} 没有可用金额。`,`No available value for ${d.latestMonth}.`):
        tr(`${d.latestMonth}，美国${partner}的${metric}为 ${fmt(d.latest)} 美元。`,`In ${d.latestMonth}, U.S. ${metric} ${partner} were ${fmt(d.latest)} USD.`));
      if(d.rows.length===1)p(intro,tr('这份报告只有一个月的数据，不能据此判断走势。','This report covers one month only; it does not establish a trend.'));
      if(s.coverage_note)p(intro,tr(s.coverage_note,s.coverage_note_en||s.coverage_note));block.append(intro);
      const metrics=make('div',undefined,'metric-grid trade-key-figures');
      const card=(label,value,detail)=>{const el=make('div');el.append(make('small',label),make('strong',value),make('span',detail));metrics.append(el);};
      if(d.latest!==null)card(tr('最新月金额 / 美元','Latest month / USD'),fmt(d.latest),d.latestMonth);
      if(d.delta!==null)card(tr('比前月变化 / 美元','Change from previous month / USD'),`${d.delta>0?'+':d.delta<0?'−':''}${fmt(Math.abs(d.delta))}`,`${d.previousMonth} → ${d.latestMonth}`);
      if(d.total!==null&&d.rows.length>1)card(tr('期间合计 / 美元','Period total / USD'),fmt(d.total),`${s.start_month} – ${s.end_month}`);
      if(metrics.children.length)block.append(metrics);
      const chart=make('section',undefined,'live-section chart-panel trade-monthly');chart.append(make('h3',tr('逐月金额','Monthly values')));
      p(chart,tr(`图中展示${metric}，不是商品数量。`,`The chart shows ${metric}, not the quantity of goods.`));
      const max=Math.max(1,...d.rows.filter(r=>r.status==='observed').map(r=>r.value_usd)),bars=make('div',undefined,'trade-bars');
      for(const row of d.rows){const line=make('div',undefined,'trade-bar-row');line.append(make('span',row.month));const track=make('div',undefined,'trade-bar-track');
        if(row.status==='observed'){const fill=make('div',undefined,'trade-bar-fill');fill.style.width=`${row.value_usd/max*100}%`;track.append(fill);}
        line.append(track,make('span',row.status==='observed'?tr(`${fmt(row.value_usd)} 美元`,`${fmt(row.value_usd)} USD`):tr('无可用金额','No available value')));bars.append(line);}chart.append(bars);
      if(d.high!==null&&d.rows.length>1){const observations=make('div',undefined,'trade-observations');
        p(observations,d.high===d.low?tr(`已收录月份的金额相同，均为 ${fmt(d.high)} 美元。`,`All observed months have the same value: ${fmt(d.high)} USD.`):
          tr(`已收录月份中，最高为 ${d.highMonths.join('、')} 的 ${fmt(d.high)} 美元；最低为 ${d.lowMonths.join('、')} 的 ${fmt(d.low)} 美元。`,
            `Among observed months, the highest value was ${fmt(d.high)} USD (${d.highMonths.join(', ')}); the lowest was ${fmt(d.low)} USD (${d.lowMonths.join(', ')}).`));
        if(d.yearPeak?.gap>0)p(observations,tr(`${d.latestMonth} 比 ${d.yearPeak.year} 年已收录月份的峰值低 ${fmt(d.yearPeak.gap)} 美元。该峰值出现在 ${d.yearPeak.months.join('、')}。`,
          `${d.latestMonth} was ${fmt(d.yearPeak.gap)} USD below the highest observed value in ${d.yearPeak.year}, recorded in ${d.yearPeak.months.join(', ')}.`));
        if(d.run)p(observations,tr(`${d.run.start} 至 ${d.run.end}，相邻月份金额连续${d.run.changes}次${d.run.sign>0?'增加':'减少'}。这只描述最近一段，不代表整个查询期间。`,
          `From ${d.run.start} through ${d.run.end}, value ${d.run.sign>0?'increased':'decreased'} for ${d.run.changes} consecutive monthly changes. This describes the recent sequence, not the whole period.`));
        else if(d.turn)p(observations,tr(`最近三个连续月份（${d.turn.months.join('、')}）先${d.turn.sign>0?'降后升':'升后降'}。`,
          `Across the latest three consecutive months (${d.turn.months.join(', ')}), value ${d.turn.sign>0?'fell, then rose':'rose, then fell'}.`));chart.append(observations);}
      const numbers=make('details',undefined,'monthly-data');numbers.append(make('summary',tr('逐月金额表','Monthly values table')));
      const scroll=make('div',undefined,'table-scroll'),table=make('table'),head=make('thead'),heading=make('tr');
      [tr('月份','Month'),`${metric} / ${tr('美元','USD')}`,tr('数据状态','Record status')].forEach(label=>heading.append(make('th',label)));head.append(heading);table.append(head);const body=make('tbody');
      for(const row of Array.isArray(part.series)?part.series:[]){const line=make('tr');
        [row.month,row.status==='observed'?(amount(row.value_usd)?fmt(row.value_usd):String(row.value_usd)):'—',
          row.status==='observed'?tr('有记录','Recorded'):row.status==='not_processed'?tr('月份未收录','Not included'):tr('无可用金额','No available value')].forEach(v=>line.append(make('td',v)));body.append(line);}
      table.append(body);scroll.append(table);numbers.append(scroll);chart.append(numbers);block.append(chart);
      const detail=make('details',undefined,'live-section');detail.append(make('summary',tr('商品范围、来源与计算说明','Product scope, sources and calculations')));
      p(detail,tr(`商品：${s.product_label}（${ex?'Schedule B':'HTS'} ${s.product_code}）；美国${partner}${ex?'出口':'进口'}；指标：${metric}。`,
        `Product: ${s.official_product_en||s.product_code} (${ex?'Schedule B':'HTS'} ${s.product_code}). U.S. ${metric} ${partner}.`));
      if(s.official_product_en)p(detail,tr(`美国官方商品定义：${s.official_product_en}`,`Official U.S. product description: ${s.official_product_en}`));
      p(detail,tr(ex?'来源为美国人口普查局商品出口明细。总出口包含国产出口与再出口，采用 FAS 口径。':'来源为美国人口普查局商品进口明细，采用消费进口额口径。',
        ex?'Source: U.S. Census monthly export detail. Total exports include domestic exports and re-exports and use the FAS basis.':'Source: U.S. Census monthly import detail, using imports-for-consumption values.'));
      p(detail,tr('金额可能受数量或价格变化影响，单凭这些数据不能确定变化原因或政策效果。','Values may change with quantity or price. These data alone do not establish causes or policy effects.'));
      for(const url of [...new Set([...(s.classification_source_urls||[]),...(part.sources||[])])].filter(url=>typeof url==='string'&&/^https:\/\/(www\.usitc\.gov|www\.census\.gov)\//.test(url)&&(!url.includes('/ex_m/')||ex)&&(!url.includes('/im_m/')||!ex))){
        const link=make('a',tr(url.includes('usitc.gov')?'美国国际贸易委员会：商品目录':'美国人口普查局：贸易数据',url.includes('usitc.gov')?'USITC commodity classification':'U.S. Census trade data'));
        link.href=url;link.target='_blank';link.rel='noopener';detail.append(link);}block.append(detail);target.append(block);
    });
    if(doc.policy){const section=make('section',undefined,'live-section trade-policy');section.append(make('h2',tr('本次检索的政策资料','Policy evidence from this search')));
      const labels={not_recorded:['该记录没有保存完整的政策检索状态。','This record does not retain complete policy search status.'],
        not_searched:['本轮未检索政策资料。','Policy evidence was not searched in this turn.'],
        no_evidence:['本地资料未找到匹配原文，不代表不存在相关政策。','No matching passage was found locally; this does not establish that no relevant policy exists.'],
        partial:['政策证据不完整，不能视为已完成适用性核查。','Policy evidence is partial; applicability has not been established.'],
        limited:['检索达到范围或预算上限，部分资料未纳入。','Search reached a scope or budget limit; some evidence was not included.'],
        scope_refused:['存档资料不能回答当前请求的税率或适用性。','Archived evidence cannot answer the requested current rate or applicability.'],
        incomplete_required_context:['已找到相关段落，仍需补充相关条件。','Relevant passages were found; related conditions still need to be retrieved.'],
        candidate_evidence:['找到候选相关原文；命中不等于已经确认适用。','Candidate passages were found; a match does not establish applicability.']};
      p(section,tr(...(labels[doc.policy.status]||labels.partial)));const refs=make('details');refs.append(make('summary',tr('原文、出处与相关条件','Passages, sources and related conditions')));
      for(const bundle of doc.policy.evidence_bundles||[])for(const item of [bundle.hit,...(bundle.required_context||[])]){if(!item)continue;
        p(refs,item.status==='verified_absent'?tr(item.boundary,'Absence was verified within this registered document only.'):`${item.citation_id||item.dependency||''}: ${item.text||''}`);
        if(typeof item.url==='string'&&/^https:\/\/(www\.)?(ustr\.gov|federalregister\.gov|govinfo\.gov|usitc\.gov|census\.gov)\//.test(item.url)){
          const a=make('a',item.url);a.href=item.url;a.target='_blank';a.rel='noopener';refs.append(a);}}
      section.append(refs);target.append(section);}
    for(const item of doc.unanswered)p(target,tr(item.text,item.text_en));return title;
  }
  globalThis.TradeIntelReportView=Object.freeze({buildTradeReportDocument,renderTradeReport});
})();
