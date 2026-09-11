"""Inventory economic comparison support; never reads post-policy outcomes."""
import csv
import argparse
import json
from collections import defaultdict
from pathlib import Path
from build_hts6_mapping import RAW_POLICY_DIR, read_annual_concordance
from inventory_census_import import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def summarize(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    result = []
    for label, group in sorted(groups.items()):
        item = {'group': label}
        for role in ('treated', 'control'):
            members = [r for r in group if r['role'] == role]
            item[role] = {'hts8_count': len(members),
                          'hs6_family_count': len({r['hts8'][:6] for r in members}),
                          'codes': [r['hts8'] for r in members]}
        item['both_sides_present'] = bool(item['treated']['hts8_count'] and item['control']['hts8_count'])
        result.append(item)
    return result


def audit():
    qualification = ROOT / 'data/processed/causal/hts8_candidate_qualification_v2.csv'
    inventory_path = ROOT / 'data/processed/causal/hts8_stable_inventory.json'
    inventory = {r['hts8']: r for r in json.loads(inventory_path.read_text())['records']}
    concordance = read_annual_concordance(2018)
    with qualification.open() as stream:
        qualified = [r for r in csv.DictReader(stream) if r['main_route_candidate'] == '1']
    rows = []
    for row in qualified:
        if row['metadata_role'] not in ('treated', 'control'):
            raise ValueError('Unexpected role')
        children = [{'hts10': code, 'naics6': concordance[code]['naics6'],
                     'description': concordance[code]['description']}
                    for code in inventory[row['hts8']]['children']]
        sectors = sorted({child['naics6'] for child in children})
        if any(not sector.startswith(row['naics4']) for sector in sectors):
            raise ValueError('Sector mapping differs from qualified scope')
        rows.append({'hts8': row['hts8'], 'role': row['metadata_role'], 'naics6': sectors,
                     'single_naics6': len(sectors) == 1, 'children': children,
                     'china_observed_months': int(row['china_observed_months'])})
    single = [r for r in rows if r['single_naics6']]
    return {'status': 'comparison_support_inventory_not_causal_design', 'policy_post_outcomes_read': False,
            'matching_run': False, 'causal_effect_estimated': False,
            'candidate_count': len(rows), 'mixed_naics6_count': len(rows) - len(single),
            'by_naics6': summarize(single, lambda r: r['naics6'][0]),
            'by_naics6_and_hts4': summarize(single, lambda r: r['naics6'][0] + '/' + r['hts8'][:4]),
            'candidates': rows,
            'input_sha256': {str(p.relative_to(ROOT)): sha256_file(p) for p in
                             [qualification, inventory_path, RAW_POLICY_DIR / 'census-import-concordance-2018.xls']}}


def render(result):
    lines = ['# 因果比较基础全量盘点', '',
             '这是候选资料盘点，不是匹配通过、平行趋势成立或因果估计。没有读取政策后结果。', '',
             f"主路线候选{result['candidate_count']}个，其中{result['mixed_naics6_count']}个跨NAICS6，单列不强制归类。", '']
    for key, title in [('by_naics6', '单一NAICS6分类'), ('by_naics6_and_hts4', 'NAICS6与HTS4交叉分类')]:
        lines += ['## ' + title, '', '| 分类 | 处理HTS8/HS6家族 | 对照HTS8/HS6家族 | 两侧都有 |', '|---|---:|---:|---|']
        for item in result[key]:
            t, c = item['treated'], item['control']
            lines += [f"| {item['group']} | {t['hts8_count']}/{t['hs6_family_count']} | {c['hts8_count']}/{c['hs6_family_count']} | {'是，仍待用途审查' if item['both_sides_present'] else '否'} |"]
        lines += ['']
    lines += ['## 所有候选的官方子码说明', '']
    for row in result['candidates']:
        lines += [f"### {row['hts8']} / {row['role']} / {','.join(row['naics6'])}", '',
                  f"中国有记录月份：{row['china_observed_months']}/29。", '']
        lines += [f"- {child['hts10']}：{child['description']}" for child in row['children']]
        lines += ['']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='仅元数据比较基础盘点，不拟合、不读取政策后结果。')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/experiments/causal-comparison-support')
    args = parser.parse_args()
    result = audit()
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    (output / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (output / 'inventory.zh-CN.md').write_text(render(result))
    print(json.dumps({'candidate_count': result['candidate_count'],
                      'mixed_naics6_count': result['mixed_naics6_count'],
                      'both_sides_naics6': sum(g['both_sides_present'] for g in result['by_naics6']),
                      'both_sides_cross_classification': sum(g['both_sides_present'] for g in result['by_naics6_and_hts4']),
                      'output': str(output)}, ensure_ascii=False, indent=2))
