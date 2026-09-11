"""Offline development replay. Changed prompt is NOT tested by recorded responses."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_planner_development import preflight,digest
from scripts.check_intent_development import canonical
from src.tradeintel_ai.analysis_planner_v2 import AnalysisPlannerV2


def replay():
    manifest,cases=preflight()
    path=ROOT/'tmp/planner-development/20260908T165101969735Z.json'
    if digest(path)!='815286fe33435963889cc98770a76f0e26ad9c05a93c388f70d84d562889e36f':
        raise ValueError('source changed')
    run=json.loads(path.read_text())
    if run['manifest']!=manifest:raise ValueError('manifest changed')
    events=[json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
    if [e['item'] for e in events if e['event']=='answer_recorded']!=run['questions']:raise ValueError('journal differs')
    rows=[]
    for case,item in zip(cases,run['questions'],strict=True):
        if case['id']!=item['id']:raise ValueError('case differs')
        class Recorded:
            def complete(self, **kwargs):return item['response']
        result=AnalysisPlannerV2(Recorded()).propose(case['question'])
        result.pop('confirmation_token',None)
        reqs=[s['request'] for s in result.get('steps',[])] or None
        passed=result['status']==case['expected_status'] and canonical(reqs)==canonical(case['expected'])
        rows.append({'id':case['id'],'passed':bool(passed),'result':result})
    return {'api_calls':0,'planned':6,'passed':sum(r['passed'] for r in rows),'rows':rows,
            'mode':'archived_response_compatibility_only','prompt_effect_tested':False,'model_adopted':False,
            'source_sha256':digest(path),'implementation_sha256':digest(ROOT/'src/tradeintel_ai/analysis_planner_v2.py')}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=replay()
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
