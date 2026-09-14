"""Multi-month presentation and narrowly reviewed endpoint comparisons."""
import hashlib
import json

from .research_comparison import calculate


def summarize_series(evidence, comparison, *, review_path):
    data = evidence['data']
    series = data['series']
    if not data['coverage_complete'] or len(series) < 2:
        raise ValueError('complete multi-month series required')
    codes = {p['hts8'] for p in series[0]['product_breakdown']}
    for row in series:
        if {p['hts8'] for p in row['product_breakdown']} != codes:
            raise ValueError('product scope differs between months')
    result = {'status': 'sequence_only', 'comparison': comparison, 'data_version': evidence.get('data_version'),
              'reason': '逐月列示不自动计算首末变化；不代表编码定义已连续核查。'}
    if comparison['kind'] == 'sequence':
        return result
    result.update(status='comparability_unreviewed', reason='该商品和比较月份没有匹配的专项编码核查，保留金额，不输出变化率。')
    if (data['hts8'] != '38180000' or comparison['reference_month'] != '2026-06'
            or comparison['current_month'] != '2026-07' or not review_path.is_file()):
        return result
    raw = review_path.read_bytes()
    review = json.loads(raw)
    if (review.get('status') != 'reviewed_specific_transition'
            or review.get('reference_month') != comparison['reference_month']
            or review.get('current_month') != comparison['current_month']):
        raise ValueError('review scope mismatch')
    # Match the review to the actual pinned query's provenance, not mutable
    # workspace CSVs or model-supplied file paths.
    sources = {s['path']: s.get('sha256') for s in evidence['evidence']['sources'] if 'path' in s}
    expected_paths = {f"data/processed/policy_exposure/monthly/{data['policy_id']}_{m.replace('-', '_')}.csv"
                      for m in ('2026-06', '2026-07')}
    checked = review.get('sources', [])
    if ({s.get('path') for s in checked} != expected_paths or len(checked) != 2
            or any(sources.get(s['path']) != s.get('sha256') for s in checked)):
        raise ValueError('review source fingerprints differ from query')
    values = {r['month']: r for r in series}
    old, new = values['2026-06'], values['2026-07']
    if (old['all_origins_value_usd'] != review['comparison']['reference_value_usd']
            or new['all_origins_value_usd'] != review['comparison']['current_value_usd']):
        raise ValueError('review amounts differ from query')
    contract = {'kind':'endpoint', 'requested_months': sorted(values),
                'reference_months':['2026-06'], 'current_months':['2026-07']}
    metrics = {key: calculate(contract, [{'month':r['month'], 'value_usd':r[key]} for r in series])
               for key in ('all_origins_value_usd', 'china_value_usd')}
    share_delta = ((new['china_value_usd']/new['all_origins_value_usd']
                    - old['china_value_usd']/old['all_origins_value_usd'])*100
                   if old['all_origins_value_usd'] and new['all_origins_value_usd'] else None)
    return {**result, 'status':'reviewed_specific_transition', 'reason':review['scope_limit'],
            'review_sha256':hashlib.sha256(raw).hexdigest(), 'review_record':review,
            'metrics':metrics, 'china_share_change_percentage_points':share_delta}


def render_series(evidence, summary):
    data = evidence['data']
    lines = ['## 逐月贸易规模（程序计算）', '',
             f"统计期：{data['start']} 至 {data['end']}；美国消费进口；名义美元，未季节调整。", '',
             '| 月份 | HTS8 | 中国金额 | 全部来源金额 | 中国占该项进口 |', '|---|---|---:|---:|---:|']
    for row in data['series']:
        for product in row['product_breakdown']:
            china, world = product['china_value_usd'], product['all_origins_value_usd']
            share = f'{china/world*100:.2f}%' if world else '未知（分母为零）'
            lines.append(f"| {row['month']} | {product['hts8']} | {china:,} | {world:,} | {share} |")
    lines += ['', '## 跨期比较的依据与限制', '', summary['reason'], '']
    if summary['status'] == 'reviewed_specific_transition':
        lines += ['比较方向：2026-07 相对 2026-06；整个HTS8汇总全部子编码，不将拆分出的新代码历史缺失补零。', '']
        for key, label in [('all_origins_value_usd','全部来源'), ('china_value_usd','中国原产')]:
            metric = summary['metrics'][key]
            rate = metric['change_percent']
            lines.append(f"- {label}：变化 {metric['change_usd']:,} 美元；变化率：" + (rate+'%' if rate is not None else '基准为零，未定义') + '。')
        delta = summary['china_share_change_percentage_points']
        lines += ['', '中国份额变化：' + (f'{delta:.2f} 个百分点。' if delta is not None else '分母为零，未知。'), '',
                  f"[专项编码转移核查来源]({summary['review_record']['source_url']})；记录指纹 `{summary['review_sha256']}`。"]
    lines += ['', '月度名义金额变化可能包含价格、数量、季节与其他因素；没有数量或价格证据，不能把它写成需求变化或政策效果。',
              '本表不是走势预测；中国份额不是中国出口对美依赖率；贸易规模不是实际税基或损失。', '',
              '## 数据出处', '', '```json', json.dumps(evidence['evidence']['sources'], ensure_ascii=False, indent=2), '```', '']
    return lines
