"""Verify archived repair runs offline; no API requests and no model adoption."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.tradeintel_ai.intent_repair import propose_repaired
from src.tradeintel_ai.intent_catalog import propose_catalog
from scripts.check_intent_development import canonical, RecordedModel


def review(path):
    path=Path(path);run=json.loads(path.read_text())
    for relative,expected in run['manifest']['files'].items():
        p=(ROOT/relative).resolve()
        if not p.is_relative_to(ROOT) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError('archive runtime mismatch')
    events=[json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
    if not events or events[-1]['event']!='run_finished' or events[-1]['status']!=run['status']:
        raise ValueError('missing consistent finish')
    if [e['item'] for e in events if e['event']=='answer_recorded']!=run['questions']:
        raise ValueError('journal mismatch')
    if sum(e['event']=='request_started' for e in events)!=run['api_requests']:
        raise ValueError('request counter mismatch')
    cases=json.loads((ROOT/'evals/intent_development_cases.json').read_text())
    by_id={};rows=[];tokens=0
    for q in run['questions']:
        if q['id'] in by_id or q['id'] not in {c['id'] for c in cases}:raise ValueError('duplicate or unknown case')
        by_id[q['id']]=q
    for c in cases:
        q=by_id.get(c['id']);correct=False
        if q and q['response'] is not None:
            if q['question']!=c['question']:raise ValueError('question mismatch')
            parser = propose_catalog if q['result'].get('version')=='intent-catalog-1' else propose_repaired
            replay=parser(c['question'],RecordedModel(q['response']))
            if replay!=q['result']:raise ValueError('replay mismatch')
            correct=(replay['parse_outcome']=='model_clarification' if c['expected'] is None else
                     replay['parse_outcome']=='validated_proposal' and canonical(replay['request'])==canonical(c['expected']))
            tokens+=q['response']['metadata'].get('usage',{}).get('total_tokens',0)
        rows.append({'id':c['id'],'recorded':q is not None,'exact_match':bool(correct),
                     'parsed_request':q['result'].get('request') if q else None,
                     'reference':c['expected'],'source_quotes':q['result'].get('evidence') if q else None})
    return {'run':str(path.resolve()),'run_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'status':run['status'],'model':run['model'],'api_requests':run['api_requests'],
            'reported_tokens':tokens,'planned':12,'exact_matches':sum(r['exact_match'] for r in rows),
            'replay_verified':True,'api_calls_for_review':0,'model_adopted':False,
            'manual_semantic_review':'pending','rows':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args()
    result=review(args.run)
    with Path(args.output).open('x',encoding='utf-8') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2);handle.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
