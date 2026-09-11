"""Reference-gated developer replay into read-only tools; not an independent eval."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.review_intent_repair_run import review
from src.tradeintel_ai.structured_workflow import execute_request


def replay(path):
    audit=review(path)
    rows=[]
    for row in audit['rows']:
        if not row['exact_match']:
            result={'status':'skipped_mismatch_or_missing','executed':False}
        elif row['parsed_request'] is None:
            result={'status':'needs_clarification','executed':False}
        else:
            result=execute_request(row['parsed_request'])
        rows.append({'id':row['id'],'result':result})
    statuses={}
    for row in rows:
        status=row['result']['status'];statuses[status]=statuses.get(status,0)+1
    return {'mode':'reference_gated_developer_replay','source_run_sha256':audit['run_sha256'],
            'model':audit['model'],'api_calls':0,'statuses':statuses,'rows':rows,
            'model_adopted':False,'independent_evaluation':False,
            'limitation':'Known development references gate execution; not natural-language production accuracy.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args()
    result=replay(args.run)
    with Path(args.output).open('x',encoding='utf-8') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2);handle.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
