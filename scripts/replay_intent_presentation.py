"""Offline, exposed development replay; no API and no execution."""
import json
from pathlib import Path
import sys
import argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.review_intent_guarded import review as review_parent
from scripts.review_intent_continuation import review as review_child
from scripts.run_intent_guarded import preflight, digest
from scripts.check_intent_development import canonical
from src.tradeintel_ai.intent_presentation import propose_presented


def replay():
    parent=ROOT/'tmp/intent-guarded/20260908T160002375476Z.json'
    child=ROOT/'tmp/intent-continuation/20260908T162309929803Z.json'
    review_parent(parent);review_child(child)
    _,cases=preflight()
    records={}
    for path in (parent,child):
        for item in json.loads(path.read_text())['questions']:
            if item['id'] in records: raise ValueError('duplicate attempt')
            records[item['id']]=item
    rows=[]
    for case in cases:
        item=records[case['id']]
        if item['response'] is None:
            rows.append({'id':case['id'],'passed':False,'status':'missing_response'})
            continue
        class Recorded:
            def complete(self, **kwargs):
                if kwargs['tools']: raise ValueError('tools forbidden')
                return item['response']
        result=propose_presented(case['question'],Recorded())
        passed=(result['parse_outcome']=='model_clarification' if case['expected'] is None else
                result['parse_outcome']=='validated_proposal' and canonical(result['request'])==canonical(case['expected']))
        if item['exact_match'] and not passed: raise ValueError('regression')
        if result['executed'] or result['intent_verified']: raise ValueError('execution forbidden')
        rows.append({'id':case['id'],'passed':bool(passed),'previous_passed':item['exact_match'],'result':result})
    return {'mode':'exposed_development_replay','api_calls':0,'model_adopted':False,
            'planned':36,'returned':35,'passed':sum(r['passed'] for r in rows),
            'source_hashes':{str(p.relative_to(ROOT)):digest(p) for p in (parent,child)},
            'implementation_hashes':{p:digest(ROOT/p) for p in (
                'src/tradeintel_ai/intent_presentation.py','scripts/replay_intent_presentation.py',
                'docs/decisions/0030-intent-presentation.zh-CN.md')},'rows':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    result=replay()
    with Path(args.output).open('x',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
