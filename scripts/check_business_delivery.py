"""Archived N01 plan -> explicit test confirmation -> real read-only report.

No API. Does not exercise the model coverage reviewer or measure model quality.
"""
import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.analysis_planner_v2 import AnalysisPlannerV2
from src.tradeintel_ai.plan_value_normalization import NormalizedPlanningModel

ARCHIVE = ROOT / 'tmp/planner-v4/20260909T051132007290Z.json'
ARCHIVE_SHA = '6eae4a0595f26c876b5e657d630f556dbeff3eed267d57f2e1a6c8ae63ce343b'


def check_delivery():
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError('Archived response fingerprint changed')
    run = json.loads(ARCHIVE.read_text())
    item = next(q for q in run['questions'] if q['id'] == 'N01')
    case = next(q for q in json.loads((ROOT / 'evals/planner_v4_development.json').read_text()) if q['id'] == 'N01')

    class Recorded:
        def complete(self, **kwargs):
            return item['responses'][0]

    flow = AnalysisPlannerV2(NormalizedPlanningModel(Recorded()))
    preview = flow.propose(case['question'])
    checks = {'exact_plan': [s['request'] for s in preview.get('steps', [])] == case['expected'],
              'confirmation_required': preview['status'] == 'needs_confirmation' and not preview['executed']}
    if not all(checks.values()):
        return {'passed': False, 'checks': checks}, ''
    token = preview['confirmation_token']
    result = flow.confirm(token)  # explicit test-only confirmation, not a user UI action
    checks['complete_report'] = result['status'] == 'evidence_ready' and len(result['results']) == 2
    checks['confirmation_single_use'] = flow.confirm(token)['status'] == 'confirmation_rejected'
    if not checks['complete_report']:
        return {'passed': False, 'checks': checks}, ''
    policy, trade = result['results']
    policy_path = ROOT / 'data/processed/policy/section301_list1_event.csv'
    with policy_path.open(newline='') as file:
        policy_row = next(r for r in csv.DictReader(file) if r['policy_id'] == 'us_301_list1_2018')
    policy_facts = {f['label']: f['value'] for f in policy['facts']}
    checks['policy_date_equal_source_csv'] = policy_facts.get('生效日期') == policy_row['effective_date']
    checks['policy_rate_equal_source_csv'] = Decimal(str(policy_facts.get('额外税率'))) == Decimal(policy_row['additional_rate']) * 100
    data = next(t['data'] for t in trade['tool_results'] if t['tool_name'] == 'get_trade_series')
    # Separate CSV reader, not the production repository/tool calculation.
    path = ROOT / 'data/processed/analysis/policy_case_monthly.csv'
    with path.open(newline='') as file:
        expected = {r['month_label']: int(r['other_origins_import_value_consumption_usd'])
                    for r in csv.DictReader(file) if r['month_label'] in ('2018-09', '2018-10')}
    actual = {r['month']: r['value_usd'] for r in data['series']}
    checks['amounts_equal_source_csv'] = len(expected) == 2 and actual == expected
    checks['total_equal_source_csv'] = data['total_usd'] == sum(expected.values())
    checks['origin_preserved'] = data['origin'] == 'other_origins'
    checks['sources_present'] = all(r['sources'] for r in result['results'])
    checks['causal_block_preserved'] = all(
        next(t['data'] for t in r['tool_results'] if t['tool_name'] == 'get_causal_readiness')['causal_allowed'] is False
        and any(f['label'] == '当前能力边界' for f in r['facts']) for r in result['results'])
    checks['monthly_amounts_rendered'] = all(
        any(f['label'] == month + ' / other_origins 进口额' and f['value'] == value for f in trade['facts'])
        for month, value in expected.items())
    report = '# 政策与进口额查询：离线业务演示\n\n'
    report += '> 使用历史模型规划响应；真实读取本地数据。未调用 API，未运行模型覆盖复核；确认由测试程序模拟，不是新模型验收成绩。\n\n'
    report += '## 用户问题\n\n' + case['question'] + '\n\n## 实际交付\n\n' + result['response'] + '\n'
    audit = {'passed': all(checks.values()), 'scope': 'archived_plan_to_real_report',
             'new_api_calls': 0, 'coverage_review_tested': False, 'independent_model_evaluation': False,
             'confirmation_actor': 'test_harness', 'checks': checks, 'amounts_usd': actual,
             'total_usd': data['total_usd'], 'source_csv_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
             'policy_csv_sha256': hashlib.sha256(policy_path.read_bytes()).hexdigest(),
             'archive_sha256': ARCHIVE_SHA}
    return audit, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    audit, report = check_delivery()
    (args.output_dir / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    (args.output_dir / 'report.zh-CN.md').write_text(report)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    sys.exit(0 if audit['passed'] else 1)
