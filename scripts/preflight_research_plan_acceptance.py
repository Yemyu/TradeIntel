"""Freeze and check the 24-question research-plan-1 acceptance set offline."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.unified_research import validate_plan

QUESTIONS = ROOT / 'evals/research_plan_acceptance_questions.jsonl'
REFERENCE = ROOT / 'evals/research_plan_acceptance_reference.json'
PROMPT = ROOT / 'src/tradeintel_ai/unified_research.py'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_questions():
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    if len(rows) != 24 or len({row.get('id') for row in rows}) != 24:
        raise ValueError('acceptance set must contain 24 unique questions')
    if any(set(row) != {'id', 'category', 'question'} for row in rows):
        raise ValueError('question schema changed')
    if any(row['category'] not in {'answerable', 'clarification', 'boundary'} for row in rows):
        raise ValueError('unknown category')
    counts = {category: sum(row['category'] == category for row in rows)
              for category in ('answerable', 'clarification', 'boundary')}
    if counts != {'answerable': 12, 'clarification': 6, 'boundary': 6}:
        raise ValueError(f'category counts changed: {counts}')
    return rows


def preflight():
    questions = load_questions()
    reference = json.loads(REFERENCE.read_text())
    if reference.get('purpose') is None or set(reference) - {'purpose'} != {row['id'] for row in questions}:
        raise ValueError('reference and questions do not match')
    answerable, clarification, boundary = [], [], []
    question_by_id = {row['id']: row['question'] for row in questions}
    for row in questions:
        ref = reference[row['id']]
        if ref['expected_status'] == 'plan':
            if row['category'] != 'answerable':
                raise ValueError('category/reference mismatch')
            trade = {'policy_id': 'us_301_list1_2018', 'operation': 'read',
                     'metric': 'import_value_consumption_usd', 'origin': ref['origin'],
                     'granularity': ref['granularity'], 'months': ref['months'],
                     'hs6': ref['hs6'], 'causal_effect': False}
            policy_question = ref['policy_question']
            q = question_by_id[row['id']]
            # The reference records the human-known plan; the exact field quotes
            # are checked against the question without asking a model to generate.
            evidence = {
                'policy_question_quote': policy_question,
                'policy_as_of_quote': ref['policy_as_of'],
                'trade.policy_id': '第一批关税',
                'trade.operation': '查询' if '查询' in q else '读取',
                'trade.metric': '美元消费进口额',
                'trade.origin': {'China': '中国', 'other_origins': '其他原产地整体',
                                 'all_origins': '全部原产地'}[ref['origin']],
                'trade.granularity': '政策整体范围' if ref['granularity'] == 'policy_aggregate' else 'HS6',
                'trade.months': next((piece for piece in ('2018-09和2018-10', '2017-02、2017-03和2017-04',
                    '2019-04至2019-06', '2018-01和2018-02', '2018-08、2018-09', '2018年3月、2018年4月',
                    '2016-07、2016-08和2016-09', '2019-01和2019-02', '2018年9月和10月',
                    '2019-10、2019-11、2019-12', '2016年11月和2017年1月', '2018-05和2018-06')
                    if piece in q), q),
                'trade.hs6': '政策整体范围' if ref['hs6'] is None else ref['hs6'],
                'trade.causal_effect': next((piece for piece in
                    ('只做描述性比较，不做因果分析', '仅作金额描述，不进行因果分析',
                     '只做描述性分析，不要求因果效果', '只作描述性金额查询，不作因果分析',
                     '仅作描述性比较，不推断因果', '只做描述分析，不要求因果结论',
                     '只做描述性分析，不做因果分析', '仅作描述性金额查询，不进行因果推断',
                     '只做描述性比较，不估计因果效果', '只作描述性分析，不把变化解释为因果',
                     '只作描述性查询，不要求因果效果', '只做描述性分析，不进行因果分析')
                    if piece in q), q),
            }
            candidate = {'status': 'plan', 'policy_question': policy_question,
                         'policy_as_of': ref['policy_as_of'], 'trade': trade,
                         'tasks': ['policy', 'trade'], 'evidence': evidence, 'missing': []}
            validate_plan(candidate, q)
            answerable.append(row['id'])
        elif ref['expected_status'] in {'clarify', 'needs_review', 'capability_blocked'}:
            if row['category'] not in {'clarification', 'boundary'}:
                raise ValueError('clarification reference mismatch')
            if row['category'] == 'clarification':
                clarification.append(row['id'])
            elif row['category'] == 'boundary':
                boundary.append(row['id'])
            else:
                raise ValueError('clarification reference category mismatch')
            if ref['expected_status'] == 'clarify' and 'missing' not in ref:
                raise ValueError('clarification reference missing fields')
            if ref['expected_status'] != 'clarify' and not ref.get('reason'):
                raise ValueError('boundary reference needs reason')
        else:
            raise ValueError('unknown expected status')
    return {'version': 'research-plan-acceptance-preflight-1', 'question_count': 24,
            'counts': {'answerable': len(answerable), 'clarification': len(clarification),
                       'boundary': len(boundary)}, 'answerable_ids': answerable,
            'clarification_ids': clarification, 'boundary_ids': boundary,
            'model_calls': 0, 'online_run': False, 'semantic_scores': None,
            'purpose': 'Freeze plan/clarification categories before any online call.',
            'sha256': {'questions': digest(QUESTIONS), 'reference': digest(REFERENCE),
                       'unified_research': digest(PROMPT)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/experiments/research-plan-acceptance-preflight.json')
    args = parser.parse_args()
    report = preflight()
    if args.output.exists():
        raise ValueError('refusing to overwrite existing preflight report')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
