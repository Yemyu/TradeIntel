"""Offline planning-stage regression only. No model/API or confirmation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.analysis_planner_v2 import AnalysisPlannerV2
from src.tradeintel_ai.plan_value_normalization import NormalizedPlanningModel


def replay(path):
    run = json.loads(path.read_text())
    cases = json.loads((ROOT / 'evals/planner_v4_development.json').read_text())
    by_id = {item['id']: item for item in run['questions']}
    rows = []
    for case in cases:
        item = by_id[case['id']]
        model = NormalizedPlanningModel(Mock(complete=Mock(return_value=item['responses'][0])))
        result = AnalysisPlannerV2(model).propose(case['question'])
        requests = [step['request'] for step in result.get('steps', [])] or None
        rows.append({'id': case['id'], 'status': result['status'],
                     'request_matches_reference': requests == case['expected'],
                     'transformations': model.transformations,
                     'executed': result['executed']})
    return {'scope': 'archived_planning_response_only', 'new_api_calls': 0,
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'independent_evaluation': False, 'coverage_review_tested': False,
            'old_live_score_unchanged': '2/4', 'rows': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.run)
    with args.output.open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
