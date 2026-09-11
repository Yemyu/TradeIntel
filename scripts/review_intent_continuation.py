"""Offline audit of exposed development questions; never an adoption score."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_intent_continuation import preflight, digest, MANIFEST, PARENT
from scripts.check_intent_development import canonical
from src.tradeintel_ai.intent_guarded import propose_guarded, capability_feedback


def review(path):
    path=Path(path)
    manifest,cases=preflight()
    run=json.loads(path.read_text())
    events=[json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
    assert run['manifest']==manifest and run['manifest_sha256']==digest(MANIFEST)
    assert [e['item'] for e in events if e['event']=='answer_recorded']==run['questions']
    assert sum(e['event']=='request_started' for e in events)==run['api_requests']
    assert events[-1]['event']=='run_finished'
    assert [q['id'] for q in run['questions']]==[c['id'] for c in cases[:len(run['questions'])]]
    records={q['id']:q for q in run['questions']}
    rows=[]
    for case in cases:
        item=records.get(case['id'])
        if not item or not item['response']:
            rows.append({'id':case['id'],'exact_match':False,'status':'missing_response'})
            continue
        class Recorded:
            def complete(self, **kwargs):
                assert kwargs['tools']==[]
                return item['response']
        parsed=propose_guarded(case['question'],Recorded())
        assert parsed==item['result'], 'raw replay differs'
        feedback=capability_feedback(parsed)
        assert feedback==item['feedback'], 'capability feedback differs'
        assert not feedback.get('executed') and not feedback.get('intent_verified')
        matched=(parsed['parse_outcome']=='model_clarification' if case['expected'] is None else
                 parsed['parse_outcome']=='validated_proposal' and canonical(parsed['request'])==canonical(case['expected']))
        assert bool(matched)==item['exact_match']
        rows.append({'id':case['id'],'exact_match':bool(matched),'status':feedback['status'],
                     'question':case['question'],'request':parsed.get('request'),
                     'evidence':parsed.get('evidence'),'response':feedback.get('response')})
    tokens=sum(json.loads(e['body']).get('usage',{}).get('total_tokens',0)
               for e in events if e['event']=='http_response')
    return {'parent_sha256':digest(PARENT),'run_sha256':digest(path),'api_requests':run['api_requests'],'known_tokens':tokens,
            'exact_matches':sum(r['exact_match'] for r in rows),'planned':23,
            'statuses':dict(Counter(r['status'] for r in rows)), 'rows':rows,
            'independent_evaluation':False,'model_adopted':False,
            'limitation':'Exposed development references; exact-match audit is not independent semantic review.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args()
    report=review(args.run)
    with Path(args.output).open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False))
