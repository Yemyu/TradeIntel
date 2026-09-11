"""Offline preflight or replay of archived normalized model responses; no network."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.intent_proposal import propose_intent

CASES = ROOT / 'evals/intent_development_cases.json'


def canonical(request):
    value = deepcopy(request)
    if isinstance(value, dict) and value.get('task') == 'trade':
        value['request']['months'] = sorted(value['request']['months'])
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def load_cases():
    cases = json.loads(CASES.read_text())
    if len(cases) != 12 or len({c['id'] for c in cases}) != 12:
        raise ValueError('开发集应含12道唯一题目')
    return cases


class RecordedModel:
    def __init__(self, response):
        self.response = response

    def complete(self, **kwargs):
        return deepcopy(self.response)


def evaluate(records):
    cases = load_cases()
    if not isinstance(records, list):
        raise ValueError('归档必须为列表')
    indexed = {}
    for record in records:
        if set(record) != {'id', 'response'} or record['id'] in indexed:
            raise ValueError('重复或非法归档字段')
        indexed[record['id']] = record['response']
    if not set(indexed) <= {c['id'] for c in cases}:
        raise ValueError('归档包含非计划题目')
    rows = []
    for case in cases:
        if case['id'] not in indexed:
            result = {'parse_outcome': 'missing_record', 'request': None}
        else:
            # Only the question reaches the parser; expected answers stay in the scorer.
            result = propose_intent(case['question'], RecordedModel(indexed[case['id']]))
        clarification = case['expected'] is None
        correct = (result['parse_outcome'] == 'model_clarification' if clarification else
                   result['parse_outcome'] == 'validated_proposal'
                   and canonical(result['request']) == canonical(case['expected']))
        rows.append({'id': case['id'], 'category': case['category'], 'expected_clarification': clarification,
                     'exact_request_match': bool(correct), 'result': result})
    return {'mode': 'offline_intent_development_replay', 'api_calls': 0,
            'planned': len(cases), 'recorded': len(indexed),
            'correct': sum(r['exact_request_match'] for r in rows),
            'parse_or_missing_failures': sum(r['result']['parse_outcome'] in ('parse_failure','missing_record') for r in rows),
            'wrong_proposals': sum(r['result']['parse_outcome']=='validated_proposal' and not r['exact_request_match'] for r in rows),
            'semantic_review_complete': False, 'model_adopted': False,
            'cases_sha256': hashlib.sha256(CASES.read_bytes()).hexdigest(),
            'parser_sha256': hashlib.sha256((ROOT/'src/tradeintel_ai/intent_proposal.py').read_bytes()).hexdigest(),
            'rows': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--responses', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.responses is None:
        print(json.dumps({'status': 'preflight_passed', 'development_questions': len(load_cases()),
                          'api_calls': 0, 'live_runner_available': False}))
    else:
        if args.output is None:
            parser.error('--responses requires --output')
        result = evaluate(json.loads(args.responses.read_text()))
        result['responses_sha256'] = hashlib.sha256(args.responses.read_bytes()).hexdigest()
        with args.output.open('x', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        print(json.dumps({k:v for k,v in result.items() if k != 'rows'}, ensure_ascii=False))
