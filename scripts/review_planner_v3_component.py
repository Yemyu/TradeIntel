"""Raw replay audit, six-item denominator. No API or automatic confirmation."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_planner_v3_component import preflight,digest,MANIFEST,propose_repaired
from scripts.check_intent_development import canonical


def review(path):
    path=Path(path);manifest,cases=preflight()
    run=json.loads(path.read_text())
    events=[json.loads(l) for l in path.with_suffix('.jsonl').read_text().splitlines()]
    if run['manifest']!=manifest or run['manifest_sha256']!=digest(MANIFEST):raise ValueError('manifest mismatch')
    if [e['item'] for e in events if e['event']=='answer_recorded']!=run['questions']:raise ValueError('journal mismatch')
    if sum(e['event']=='request_started' for e in events)!=run['api_requests']:raise ValueError('attempt mismatch')
    if not events or events[-1]['event']!='run_finished':raise ValueError('incomplete journal')
    if [q['id'] for q in run['questions']]!=[c['id'] for c in cases[:len(run['questions'])]]:raise ValueError('order mismatch')
    byid={q['id']:q for q in run['questions']};rows=[]
    for c in cases:
        item=byid.get(c['id'])
        if not item or item['response'] is None:
            rows.append({'id':c['id'],'passed':False,'status':'missing_response'});continue
        class Recorded:
            def complete(self,**kwargs):return item['response']
        result=propose_repaired(c['question'],Recorded())
        if result!=item['result']:raise ValueError('replay mismatch')
        req=[s['request'] for s in result.get('steps',[])] or None
        passed=result['status']==c['expected_status'] and canonical(req)==canonical(c['expected'])
        if bool(passed)!=item['exact_match'] or result['executed']:raise ValueError('score mismatch')
        rows.append({'id':c['id'],'question':c['question'],'passed':bool(passed),'result':result})
    tokens=sum(json.loads(e['body']).get('usage',{}).get('total_tokens',0) for e in events if e['event']=='http_response')
    return {'source_sha256':digest(path),'planned':6,'passed':sum(r['passed'] for r in rows),
            'api_requests':run['api_requests'],'known_tokens':tokens,'rows':rows,
            'mode':'archived_plans_live_coverage_review','model_adopted':False,'independent_evaluation':False,'semantic_review_required':True}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=review(args.run)
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
