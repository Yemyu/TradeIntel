/* Read-only report rendering shared by saved cases and the local workspace. */
(() => {
  function renderTradeReport(target, result, {language='zh', readerView=null}={}) {
    if (!['trade-query-v1','trade-query-both-v1'].includes(result?.kind)||!result.scope)
      throw new Error('Unsupported saved report');
    const english = () => language === 'en';
    const tr = (zh,en) => english()?en:zh;
    const fmt = value => Number(value).toLocaleString(english()?'en-US':'zh-CN');
    const make = (tag,text,className) => {
      const el=(target.ownerDocument||document).createElement(tag);
      if(text!==undefined)el.textContent=text;
      if(className)el.className=className;
      return el;
    };
    const addParagraph = (parent,text) => parent.append(make('p',text));
  const englishTrend = series => {
    const measured=series.filter(row=>row.status==='observed'&&Number.isFinite(row.value_usd));
    if(!measured.length)return 'No published monthly value is available for this range.';
    if(measured.length===1)return `Only ${measured[0].month} has a published value; one month does not establish a trend.`;
    const first=measured[0],last=measured.at(-1);
    const high=Math.max(...measured.map(row=>row.value_usd));
    const low=Math.min(...measured.map(row=>row.value_usd));
    const highs=measured.filter(row=>row.value_usd===high).map(row=>row.month).join(', ');
    const lows=measured.filter(row=>row.value_usd===low).map(row=>row.month).join(', ');
    const change=last.value_usd-first.value_usd;
    return `Across ${measured.length} published months, ${last.month} is ${fmt(Math.abs(change))} USD ${change>=0?'above':'below'} ${first.month}. `+
      `The highest value was ${fmt(high)} USD (${highs}); the lowest was ${fmt(low)} USD (${lows}). These values alone do not establish a cause.`;
  };
  const englishNote = note => ({
    '本报告只使用美国商品总出口额（国产出口与再出口之和，FAS），不包含进口。':
      'This report uses U.S. total exports (domestic exports plus re-exports, FAS); it does not include imports.',
    '本报告只使用美国消费进口额，不包含出口。':
      'This report uses U.S. imports for consumption; it does not include exports.',
    '金额变化可能来自数量或价格，不能仅凭金额判断政策效果。':
      'Value changes may reflect quantity or price. These values alone cannot establish a policy effect.',
    '金额变化可能来自进口数量或价格；仅凭金额不能判断政策效果。':
      'Value changes may reflect import quantity or price. These values alone cannot establish a policy effect.',
    '金额变化不等于商品数量变化，也不能单凭本报告归因于某项政策。':
      'A change in value is not necessarily a change in quantity and cannot, by itself, be attributed to a policy.'
  })[note] || `Data note (original Chinese): ${note}`;
  const directionEnglish = value => ({'增加':'increased','减少':'decreased','持平':'was unchanged'})[value]||'changed';
  function englishRelation(card){
    const flow=card.flow==='export'?'Export value':'Import value';
    if(card.id==='both.latest_relation'){
      return `In ${card.months.at(-1)}, import value ${directionEnglish(card.import_direction)} and export value ${directionEnglish(card.export_direction)} from the previous month. The two directions moved ${card.relation==='同向'?'in the same direction':'in different directions'}; these measures are shown separately, not subtracted.`;
    }
    if(card.id.endsWith('.recent_run'))return `By ${card.months.at(-1)}, ${flow.toLowerCase()} had ${card.direction==='增加'?'increased':'decreased'} month over month for ${card.consecutive_changes} consecutive changes. This does not describe the entire selected period.`;
    if(card.id.endsWith('.recent_turn'))return `The ${flow.toLowerCase()} moved from ${card.previous_direction==='增加'?'up':'down'} in ${card.months[1]} to ${card.direction==='增加'?'up':'down'} in ${card.months[2]}. This describes only the latest three observed months.`;
    return card.fact;
  }
  function englishYearPeak(card){
    const flow=card.flow==='export'?'exports':'imports';
    const peakMonths=(card.high_months||[]).join(', ');
    if(card.gap_usd===0)
      return `Among observed ${card.year} months, ${peakMonths} was the ${flow} high at ${fmt(card.high_usd)} USD; ${card.latest_month} was at the same level.`;
    return `Among observed ${card.year} months, ${peakMonths} was the ${flow} high at ${fmt(card.high_usd)} USD; ${card.latest_month} was ${fmt(card.latest_usd)} USD, ${fmt(card.gap_usd)} USD below that high.`;
  }
  function appendYearPeakCard(target,observations,flow){
    const card=observations.find(item=>item.id===flow+'.same_year_peak_gap'&&item.status==='available');
    if(!card)return;
    const section=make('section',undefined,'live-section trade-year-peak');
    section.append(make('h3',tr('按同年已观察月份比较','Compare observed months within the year')));
    const item=make('article',undefined,'trade-relation-card');
    item.append(make('h4',tr('同年峰值与最新已观察月','Year peak and latest observed month')));
    addParagraph(item,english()?englishYearPeak(card):card.fact);
    section.append(item);target.append(section);
  }
  function appendRelationCards(target, cards, flow){
    const eligible=cards.filter(card=>card.status==='available'&&card.eligible_for_ai&&card.flow===flow);
    if(!eligible.length)return;
    const section=make('section',undefined,'live-section trade-relations');
    section.append(make('h3',tr(flow==='both'?'进口和出口放在一起看':'最近几个月的变化',
      flow==='both'?'Imports and exports together':'Recent monthly movement')));
    for(const card of eligible){
      const item=make('article',undefined,'trade-relation-card');
      const title=card.id.endsWith('.recent_turn')?tr('最近出现转向','Recent direction change'):
        card.id.endsWith('.recent_run')?tr('连续几个月同向变化','Consecutive monthly changes'):
          tr('进出口方向对照','Import and export comparison');
      item.append(make('h4',title));
      addParagraph(item,english()?englishRelation(card):card.fact);
      section.append(item);
    }
    target.append(section);
  }
  function appendTradeDirection(target, result, observations=[]) {
    const {scope,summary,series}=result;
    const exportFlow=scope.flow==='export';
    const direction=exportFlow?'出口':'进口';
    const metric=exportFlow?'商品总出口额（FAS）':'消费进口额';
    target.append(make('h2',tr(`美国${direction} · ${scope.product_code} 商品组`,
      `U.S. ${exportFlow?'exports':'imports'} · product group ${scope.product_code}`)));
    const intro=make('section',undefined,'live-section');intro.append(make('h3',tr('先看数字','Key figures')));
    const latest=summary.latest_value_usd;
    const counterpart=scope.partner==='CHINA'?(exportFlow?'向中国':'从中国'):(exportFlow?'向全部目的地':'从全部来源');
    addParagraph(intro,latest===null?tr(`${summary.latest_month} 没有可用金额。`,
      `No published value is available for ${summary.latest_month}.`):
      tr(`${summary.latest_month}，美国${counterpart}的${metric}为 ${fmt(latest)} 美元。`,
        `In ${summary.latest_month}, U.S. ${exportFlow?'total exports (FAS)':'imports for consumption'} ${scope.partner==='CHINA'?(exportFlow?'to China':'from China'):(exportFlow?'to all destinations':'from all origins')} were ${fmt(latest)} USD.`));
    if(summary.month_change_usd!==null)addParagraph(intro,
      tr(`比 ${summary.previous_month} ${summary.month_change_usd>=0?'增加':'减少'} ${fmt(Math.abs(summary.month_change_usd))} 美元；仅凭金额不能判断原因。`,
        `That is ${fmt(Math.abs(summary.month_change_usd))} USD ${summary.month_change_usd>=0?'higher':'lower'} than ${summary.previous_month}. The value change alone does not tell us why.`));
    else if(series.length===1)addParagraph(intro,tr(`这份报告只含一个月，不能据此判断${direction}走势。`,
      'This report covers only one month, so it cannot establish a trend.'));
    if(summary.period_total_usd!==null && series.length>1)addParagraph(intro,
      tr(`${scope.start_month} 至 ${scope.end_month} 的合计为 ${fmt(summary.period_total_usd)} 美元。`,
        `The sum from ${scope.start_month} through ${scope.end_month} was ${fmt(summary.period_total_usd)} USD.`));
    if(scope.coverage_note)addParagraph(intro,tr(scope.coverage_note,
      scope.coverage_note_en || (exportFlow
        ? `Only ${series.length} export months are available for this query; fewer than 12 months cannot establish a long-term trend.`
        : scope.coverage_note)));
    target.append(intro);
    const trendFact=observations.find(item=>item.id===scope.flow+'.trend');
    if(trendFact){
      const trend=make('section',undefined,'live-section trade-trend-fact');
      trend.append(make('h3',tr('这段时间的走势','Over this period')));
      addParagraph(trend,english()?englishTrend(series):trendFact.fact);
      target.append(trend);
    }
    appendYearPeakCard(target,observations,scope.flow);
    appendRelationCards(target,observations,scope.flow);
    const chart=make('section',undefined,'live-section');chart.append(make('h3',tr('逐月金额','Monthly values')));
    addParagraph(chart,tr(`每条横线表示该月的${metric}，不代表商品数量。`,
      `Each bar shows ${exportFlow?'total exports (FAS)':'imports for consumption'} in that month, not the quantity of goods.`));
    const max=Math.max(1,...series.map(row=>row.value_usd||0));
    const bars=make('div',undefined,'trade-bars');
    for(const row of series){const line=make('div',undefined,'trade-bar-row');
      line.append(make('span',row.month));const track=make('div',undefined,'trade-bar-track');
      const fill=make('div',undefined,'trade-bar-fill');
      fill.style.width=`${Math.max(0,(row.value_usd||0)/max*100)}%`;track.append(fill);line.append(track,
        make('span',row.status==='observed'?tr(`${fmt(row.value_usd)} 美元`,`${fmt(row.value_usd)} USD`):
          tr('无可用金额','No published value')));bars.append(line);}
    chart.append(bars);
    const numbers=make('details',undefined,'monthly-data');numbers.append(make('summary',tr('逐月金额表','Monthly values table')));
    const scroll=make('div',undefined,'table-scroll');const table=make('table');
    const head=make('thead');const headings=make('tr');
    [tr('月份','Month'),tr(`美国${metric} / 美元`,`${exportFlow?'U.S. total exports (FAS)':'U.S. imports for consumption'} / USD`),
      tr('记录状态','Record status')].forEach(label=>headings.append(make('th',label)));
    head.append(headings);table.append(head);const body=make('tbody');
    for(const row of series){const line=make('tr');
      [row.month,row.status==='observed'?fmt(row.value_usd):'—',
       row.status==='observed'?tr('有记录','Published'):row.status==='not_processed'?tr('月份未加工','Not processed'):tr('无可用金额','No published value')]
        .forEach(value=>line.append(make('td',value)));
      body.append(line);
    }table.append(body);scroll.append(table);numbers.append(scroll);chart.append(numbers);target.append(chart);
    const detail=make('details',undefined,'live-section');detail.append(make('summary',tr('商品范围、来源与计算说明','Product scope, sources and calculations')));
    if(scope.coverage_note)addParagraph(detail,tr(scope.coverage_note,scope.coverage_note_en||scope.coverage_note));
    addParagraph(detail,tr(`商品：${scope.product_label}，${exportFlow?'Schedule B':'HTS'} ${scope.product_code}。方向：美国${direction}；指标：${metric}；${exportFlow?'目的地':'来源地'}：${scope.partner==='CHINA'?'中国':'全部'}。`,
      `Product: ${scope.official_product_en||scope.product_code}, ${exportFlow?'Schedule B':'HTS'} ${scope.product_code}. Direction: U.S. ${exportFlow?'exports':'imports'}. Measure: ${exportFlow?'total exports (FAS)':'imports for consumption'}. ${exportFlow?'Destination':'Origin'}: ${scope.partner==='CHINA'?'China':'all'}.`));
    if(scope.official_product_en)addParagraph(detail,tr(`美国官方英文商品范围：${scope.official_product_en}。`,
      `Official U.S. product description: ${scope.official_product_en}.`));
    addParagraph(detail,tr(exportFlow?'金额来自美国人口普查局逐月商品出口明细；总出口是本国产品出口与再出口之和，采用 FAS 口径。':'金额来自美国人口普查局逐月商品进口明细，采用消费进口额口径。',
      exportFlow?'Values come from U.S. Census monthly export detail. Total exports include domestic exports and re-exports and use the FAS basis.':
        'Values come from U.S. Census monthly import detail and use imports-for-consumption values.'));
    for(const url of [...new Set([...(scope.classification_source_urls||[]),...(result.sources||[])])].filter(url=>
      typeof url==='string' && /^https:\/\/(www\.usitc\.gov|www\.census\.gov)\//.test(url) &&
      (!url.includes('/ex_m/')||exportFlow) && (!url.includes('/im_m/')||!exportFlow))){
      const link=make('a',url);link.href=url;link.target='_blank';link.rel='noopener';detail.append(link,make('br'));
    }
    for(const note of result.notes||[])if(!note.startsWith('目前未运行模型解释'))addParagraph(detail,english()?englishNote(note):note);
    target.append(detail);
  }
    const scope=result.scope;
    const title=scope.flow==='both'?'进出口':scope.flow==='export'?'出口':'进口';
    const englishDirection=scope.flow==='both'?'imports and exports':scope.flow==='export'?'exports':'imports';
    const reportTitle=tr(result.question||`美国${scope.product_code}${title}情况`,
      `U.S. ${englishDirection} · ${scope.official_product_en||`product group ${scope.product_code}`}`);
    target.append(make('p',tr('美国贸易数据','U.S. trade data'),'eyebrow'),make('h1',reportTitle));
    addParagraph(target,tr(`${scope.start_month} 至 ${scope.end_month} · ${scope.product_code} 商品组。完整商品范围见报告末尾。`,
      `${scope.start_month} to ${scope.end_month} · product group ${scope.product_code}. The full product scope appears below.`));
    if(result.kind==='trade-query-both-v1'){
      addParagraph(target,tr('进口与出口来自不同统计口径，下面分别展示；两项金额不能直接相减称为贸易差额。',
        'Imports and exports use different statistical bases and are shown separately. Do not subtract these values and call the difference a trade balance.'));
      const observations=result.explanation?.observations||result.observations||[];
      appendTradeDirection(target,result.import_report,observations);
      appendTradeDirection(target,result.export_report,observations);
      appendRelationCards(target,observations,'both');
    }else appendTradeDirection(target,result,result.explanation?.observations||result.observations||[]);
    if(readerView){
      const section=make('section',undefined,'live-section');
      section.append(make('h2',tr('数据摘要','Data summary')));
      for(const fact of readerView.facts||[])addParagraph(section,tr(fact.text,fact.text_en));
      for(const missing of readerView.unanswered||[])addParagraph(section,tr(missing.text,missing.text_en));
      const method=make('details');method.append(make('summary',tr('来源与方法','Sources and method')));
      addParagraph(method,tr(readerView.method.text,readerView.method.text_en));section.append(method);
      target.append(section);
    }
    return reportTitle;
  }
  globalThis.TradeIntelReportView=Object.freeze({renderTradeReport});
})();
