"""Small evidence-only report contract; not a general semantic verifier."""
import json
import re
from datetime import date

FOLLOWUPS = {
    'product_breakdown': '核对本报告已列出的各税号份额与金额权重，选择值得深入的商品；这是阅读已有分项，不是声称缺少这些数据。',
    'origin_breakdown': '查询其他原产地分布：进口集中在哪些来源？需分国别金额；原产地统计本身不能识别转运。',
    'supply_conditions': '若要判断供应是否紧张，需补充国内产量、库存、价格和交货期等证据；进口金额不能证明没有短缺或存在替代产能。',
}
FACTS = ['all_origins_usd', 'china_usd', 'china_share_percent']
ANSWER_CONTRACT = {
    'version': 'exposure-actions-v2',
    'instruction': '仅返回一个JSON对象，唯一字段next_steps，从allowed_next_steps中选择1至3个不同ID，按优先级排序。不要返回facts、数字、解释或网址；数值及引用由程序从实际工具结果填入。',
    'schema_example': {'next_steps': ['origin_breakdown']},
    'allowed_next_steps': FOLLOWUPS,
    'boundary': '当前没有国内生产、库存、价格、交货期或转运证据；不得声称产能填补缺口、供应不短缺、政策有效或已去风险。',
}


def answer_contract(results):
    allowed = dict(FOLLOWUPS)
    if results and results[0]['data'].get('hts8') is not None:
        allowed.pop('product_breakdown')
    return {**ANSWER_CONTRACT, 'allowed_next_steps': allowed}


def parse_actions(text, results):
    """Accept a single exact JSON fence, never scrape JSON out of surrounding prose."""
    stripped = text.strip()
    fence = re.fullmatch(r'```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```', stripped)
    if fence:
        stripped = fence.group(1)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    payload = json.loads(stripped, object_pairs_hook=unique_object)
    if not isinstance(payload, dict) or set(payload) not in ({'next_steps'}, {'facts', 'next_steps'}):
        raise ValueError('unexpected report fields')
    # Legacy fixed IDs may be read, but are never requested or used as facts.
    if 'facts' in payload and payload['facts'] != FACTS:
        raise ValueError('legacy fact IDs changed; cannot silently discard claimed values')
    steps = payload['next_steps']
    allowed = answer_contract(results)['allowed_next_steps']
    if (not isinstance(steps, list) or not 1 <= len(steps) <= 3
            or any(not isinstance(s, str) or s not in allowed for s in steps)
            or len(set(steps)) != len(steps)):
        raise ValueError('unsupported next-step reference')
    return {'next_steps': steps, 'normalization': 'json_fence_removed' if fence else 'none',
            'legacy_fixed_ids': 'facts' in payload}


def render_exposure_report(text, results, *, report_date):
    """Render evidence plus scope-appropriate actions; never model-provided prose."""
    date.fromisoformat(report_date)
    steps = parse_actions(text, results)['next_steps']
    if not results:
        raise ValueError('no executed evidence')
    rows = []
    sources = []
    for result in results:
        data = result['data']
        if result['status'] != 'ok' or not data['coverage_complete'] or len(data['series']) != 1:
            raise ValueError('requires complete single-month evidence')
        row = data['series'][0]
        if row['month'] > report_date[:7]:
            raise ValueError('statistics after report cutoff')
        rows.append((data['policy_id'], data['hts8'], row['month'],
                     row['all_origins_value_usd'], row['china_value_usd']))
        result_sources = result['evidence']['sources']
        if not isinstance(result_sources, list) or not result_sources:
            raise ValueError('missing provenance')
        for source in result_sources:
            if source not in sources:
                sources.append(source)
    if any(row != rows[0] for row in rows):
        raise ValueError('inconsistent tool results')
    policy, hts8, month, world, china = rows[0]
    if (type(world) is not int or type(china) is not int or not 0 <= china <= world):
        raise ValueError('invalid monetary evidence')
    share = f'{china / world * 100:.2f}%' if world else '未知（总额为零）'
    scope = f'登记税号 {hts8}' if hts8 else '登记政策整体税号范围'
    lines = ['# 贸易暴露简报（受约束初稿，待审阅）', '',
             f'报告截止日：{report_date}；统计期：{month}。不是实时数据，也不是严格历史发布版本回测。', '',
             f'政策标识：`{policy}`；范围：{scope}。', '', '## 可核查事实', '',
             f'- 美国全部来源消费进口额：{world:,} 美元。',
             f'- 中国原产消费进口额：{china:,} 美元。',
             f'- 中国占上述进口额：{share}；分母不包含美国本土生产。', '',
             '## 能帮助判断什么', '',
             '确定登记范围当月进口规模与中国来源占比，为分商品、分来源调查提供起点；不是中国出口对美依赖率，也不是损失或因果效果。', '',
             '## AI 选择的后续调查顺序', '']
    lines.extend(f'{i}. {FOLLOWUPS[s]}' for i, s in enumerate(steps, 1))
    breakdown = results[0]['data']['series'][0].get('product_breakdown')
    if breakdown:
        if (sum(p['all_origins_value_usd'] for p in breakdown) != world
                or sum(p['china_value_usd'] for p in breakdown) != china
                or len({p['hts8'] for p in breakdown}) != len(breakdown)):
            raise ValueError('product breakdown does not reconcile')
        lines += ['', '## 分商品：合计份额不能代替单项判断', '',
                  '| HTS8 | 全来源进口额（美元） | 中国原产（美元） | 中国占该项进口 | 该项占范围总进口 |',
                  '|---|---:|---:|---:|---:|']
        for p in breakdown:
            total, target = p['all_origins_value_usd'], p['china_value_usd']
            if type(total) is not int or type(target) is not int or not 0 <= target <= total:
                raise ValueError('invalid product amounts')
            pct = f'{target / total * 100:.2f}%' if total else '未知'
            weight = f'{total / world * 100:.2f}%' if world else '未知'
            lines.append(f"| {p['hts8']} | {total:,} | {target:,} | {pct} | {weight} |")
        lines += ['', '中国占比的分母是该税号进口额；最后一列的分母是整个查询范围进口额。它们不是同一个指标。',
                  '合计份额是按进口金额加权的结果，大金额商品会主导合计值；这里不据份额高低直接认定风险或替代能力。']
    policy_evidence = results[0].get('policy_evidence', {})
    hits = policy_evidence.get('hits', [])
    lines += ['', '## 政策原文候选证据', '']
    for hit in hits:
        lines += [f"- 来源：{hit['citation_url']}；出版日：{hit['published']}；本地段落：{hit.get('paragraph_index', '未知')}",
                  '', '> ' + hit['text'].replace('\n', '\n> '), '']
    if not hits:
        lines += ['尚无政策原文检索结果，不能把登记表当成已检索原文。']
    metadata = results[0].get('policy_metadata', {})
    if metadata.get('dates'):
        dates = metadata['dates']
        lines += ['', f"日期区分：USTR 公告 {dates['announcement_date']}；Federal Register 出版 {dates['federal_register_publication_date']}；CBP 指引 {dates['cbp_guidance_publication_date']}；该次安排生效 {dates['effective_date']}。",
                  '日期依据：' + metadata['announcement_source'] + '；' + metadata['guidance_source'],
                  '81019910 的棒材范围排除仅经烧结得到的棒材；登记描述修订不改变本表按税号计算的金额。']
    lines += ['', '## 证据不足，不能下结论', '',
              '这些金额不能证明国内自给、产能填补缺口、没有供应短缺、第三国转运或政策效果。跨期编码连续性未审阅，不据本表推断趋势。', '',
              '## 来源', '']
    # Serialize host-returned provenance, not model-provided URLs or statements.
    lines += ['```json', json.dumps(sources, ensure_ascii=False, indent=2), '```', '',
              '说明：AI 选择调查方向；事实、边界文字和引用由程序生成。结构通过不等于独立研究质量验证。']
    return '\n'.join(lines) + '\n'
