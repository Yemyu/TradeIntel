"""Offline format-only development regression; does not replace holdout scores."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.score_intent_holdout import score
from scripts.check_intent_development import RecordedModel,canonical
from src.tradeintel_ai.intent_format import normalize_response
from src.tradeintel_ai.intent_catalog import propose_catalog


def replay(path):
    baseline=score(path)
    run=json.loads(Path(path).read_text());refs=json.loads((ROOT/'evals/intent_holdout_reference.json').read_text())
    rows=[]
    for q in run['questions']:
        before=q['exact_match'];correct=False;changes=[];result=q['result']
        if q['response']:
            normalized,changes=normalize_response(q['response'])
            result=propose_catalog(q['question'],RecordedModel(normalized))
            expected=refs[q['id']]['expected']
            correct=(result['parse_outcome']=='model_clarification' if expected is None else
                     result['parse_outcome']=='validated_proposal' and canonical(result['request'])==canonical(expected))
        if before and not correct:raise ValueError('regression: previously matched request failed')
        rows.append({'id':q['id'],'repeat':q['repeat'],'before':before,'after':bool(correct),
                     'transformations':changes,'result':result})
    return {'mode':'offline_development_format_regression','source_run_sha256':baseline['run_sha256'],
            'api_calls':0,'planned':48,'recorded':len(rows),'original_matches':sum(r['before'] for r in rows),
            'replay_matches':sum(r['after'] for r in rows),'recovered':sum(r['after'] and not r['before'] for r in rows),
            'model_adopted':False,'original_holdout_passed':False,'rows':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run');p.add_argument('--output',required=True);a=p.parse_args()
    result=replay(a.run)
    with Path(a.output).open('x',encoding='utf-8') as h:json.dump(result,h,ensure_ascii=False,indent=2);h.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
