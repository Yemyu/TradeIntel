"""Reproduce a local-data report preview; no network, API or human approval.

The explanation below was authored in the assistant conversation. This is a
presentation sample using real program output, not an end-to-end acceptance.
"""
import argparse
import json
from pathlib import Path

from tradeintel_ai.session_brief import build_session_brief
from tradeintel_ai.exposure_version_store import ExposureVersionStore
from tradeintel_ai.policy_cases import CASES
from tradeintel_ai.bounded_explanation import parse

QUESTION = '美国对登记的多晶硅、晶圆及钨产品加征关税后，我应优先关注哪些商品？请用2026年7月的进口金额和中国来源占比说明，并列出还需调查的问题。'
EXPLANATIONS = {
    'amount_leader': '该商品适合作为贸易金额规模的优先核查对象，但金额较大不能直接推出企业损失更大；还需结合具体企业采购及适用条款判断。',
    'share_leader': '该商品适合优先核查进口来源结构。中国来源占比较高，只说明中国在美国该商品进口中的比重，不能代替对美国国内供给或替代供应能力的调查。',
    'rank_contrast': '金额排序用于识别交易规模较大的对象，来源占比排序用于识别进口来源结构的特点。研究优先级取决于用户关注采购金额还是来源结构，不能只选一个榜首代表所有风险。',
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    policy_id = 'us_301_review2025_tungsten_solar'
    version = ExposureVersionStore(root, root / CASES[policy_id].versions).active_version()
    brief = build_session_brief(root, {'policy_id': policy_id, 'month': '2026-07',
                                     'product': 'all', 'focus': 'contrast'}, data_version=version)
    catalog = brief['catalog']
    answer = {
        'interpretations': {f'slot{i}': EXPLANATIONS[o['type']]
                            for i, o in enumerate(catalog['observations'], 1)},
        'missing_evidence': '需要企业采购合同、实际成交价格、入境日期、逐笔适用条款以及替代供应商的产能和认证资料。',
        'question': '哪些企业存在与这些商品对应的采购敞口，能否调整来源，以及哪些交易实际满足公告适用条件？',
    }
    raw = json.dumps(answer, ensure_ascii=False)
    checked = parse(raw, catalog)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'program-report-A3.zh-CN.md').write_text(brief['a3_markdown'], encoding='utf-8')
    (out / 'chat-answer.json').write_text(raw, encoding='utf-8')
    (out / 'validation.json').write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding='utf-8')
    rates = {r['hts8']: r for r in catalog['policy_facts']['product_rates']}
    lines = ['# 贸易政策研究简报：应优先关注哪些商品？', '',
             '> 展示稿，待人工审阅。金额和比例由项目程序重新计算；解释由当前Astra对话提供并经E协议解析。没有API调用，不是模型独立评测或完整会话导出演示。', '',
             '## 用户问题', '', QUESTION, '',
             '## 本次如何得到报告', '',
             '确认已登记政策和五个税号→读取已发布版本的当月统计→检索存档政策证据→计算金额与占比→对话补充解释→结构校验→展示待审稿。', '',
             '使用的是项目现有数据快照，没有本次联网抓取。统计期为2026年7月；政策条款为存档事件口径，不代表已核验今天所有税则修订。', '',
             '## 主要结果', '',
             '| HTS8 | 登记名称（中文） | 美国全部来源进口额（美元） | 中国原产金额（美元） | 中国来源占该商品进口比例 |',
             '|---|---|---:|---:|---:|']
    for row in brief['evidence_rows']:
        name = rates[row['hts8']].get('details', {}).get('registered_name_zh', row['hts8'])
        share = '未知' if row['china_share_percent'] is None else f"{row['china_share_percent']:.4f}%"
        lines.append(f"| {row['hts8']} | {name} | {row['world_import_usd']:,} | {row['china_import_usd']:,} | {share} |")
    lines += ['', '比例分母：美国从全部来源进口该商品的金额；不是中国出口总额，也不是美国总供给。', '',
              '## 为什么值得关注', '']
    for i, observation in enumerate(catalog['observations'], 1):
        lines += [f"### {observation['meaning']}", '',
                  f"程序观察：{json.dumps(observation['value'], ensure_ascii=False)}", '',
                  answer['interpretations'][f'slot{i}'], '']
    lines += ['## 政策证据', '',
              '项目存档公告记录的生效日为2025年1月1日；硅及晶圆相关登记税号的额外税率为50%，钨产品登记税号为25%。这些是存档额外税率，不能直接当作当前综合税率。逐笔条件、例外及后续修订尚需核对。', '',
              '## 下一步调查', '', answer['missing_evidence'], '', answer['question'], '',
              '## 当前不能回答', '',
              '本报告没有识别政策造成了多少变化，也未预测未来进口、价格或企业利润。进口金额不能直接乘存档税率得到真实税款或损失。', '',
              '## 数据与政策来源', '']
    urls = list(dict.fromkeys(s.get('url') for s in catalog['sources'] if s.get('url')))
    for url in urls:
        lines.append(f'- {url}')
    lines += ['', f'数据版本：`{version}`',
              f"事实目录摘要：`{catalog['catalog_sha256']}`", '',
              '完整事实、逐商品条件、原文及局限见同目录 program-report-A3.zh-CN.md；结构校验记录见 validation.json。所有审阅警示均保留，尚未人工批准。', '']
    (out / 'report-preview.zh-CN.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'output': str(out), 'rows': len(brief['evidence_rows']),
                      'validation': checked['status'], 'approved': False, 'api_calls': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
