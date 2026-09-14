"""Render source-bound review material; never approve model semantics."""
from .policy_time_hints import annotate_clock_times


def render_policy_review(claims, evidence):
    hits = annotate_clock_times(evidence['hits'])
    refs = {hit['id']: hit for hit in hits}
    if len(refs) != len(hits):
        raise ValueError('duplicate evidence identifiers')
    lines = ['## AI解释与逐项原文核查', '',
             '以下解释由模型生成，尚未完成语义审阅。原文由程序从本次检索记录展示，不由模型改写。', '']
    for index, claim in enumerate(claims, 1):
        lines += [f'### 主张 {index}', '', claim['text'], '', '对应原文：', '']
        for source_id in dict.fromkeys(claim['citations']):
            hit = refs[source_id]
            lines += [f"[{source_id}]({hit['citation_url']})", '',
                      f"公告日期：{hit.get('published', '未记录')}；抓取时间：{hit.get('retrieved_at', '未记录')}。", '',
                      *('> ' + line for line in hit['text'].splitlines()), '']
            for hint in hit.get('derived_clock_hints', []):
                lines += [f"程序时刻提示：原文 `{hint['source_quote']}` → `{hint['clock_24h']}`（24小时制）；未转换时区、未推断日期或适用条件。", '']
    lines += ['## 人工核查清单（尚未勾选）', '',
              '- 商品编码、商品限定和原产地是否同时匹配？',
              '- 写的是额外税率还是综合税率？例外或排除条件有没有遗漏？',
              '- 日期、24小时制时刻、原文时区是否一致？',
              '- 生效判断是入境、供消费入境，还是从仓库提取供消费？不能混用。',
              '- 引用是否支持整句话，而不仅仅提到了相同商品？', '',
              '## 证据范围与未知', '',
              f"检索截止日：{evidence.get('as_of', '未记录')}。这不是现行税则核验日期。", '',
              'HTML段落序号不是PDF页码；当前网页的抓取副本不证明历史时点即可获得该版本。', '',
              '仅解释存档政策，不确认现行综合税率；本报告未计算贸易损失、政策因果效应或未来走势。', '']
    for limitation in evidence.get('limitations', []):
        lines.append('- ' + limitation)
    cited = {source_id for claim in claims for source_id in claim['citations']}
    uncited = [hit['id'] for hit in hits if hit['id'] not in cited]
    if uncited:
        lines += ['', '检索到但本次主张未引用的段落：' + '、'.join(uncited) + '。未引用不代表不适用，需检查遗漏条件。']
    return lines
