"""Prepare all 48 planned review rows without assigning semantic scores."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_acceptance_v21 as evaluation


def prepare(path):
    questions,refs,_,manifest=evaluation.preflight()
    path=Path(path)
    run=json.loads(path.read_text())
    if run.get("manifest") != manifest or run.get("manifest_sha256") != evaluation.live.digest(evaluation.MANIFEST):
        raise ValueError("运行指纹与验收版本不一致")
    planned={(q['id'],r) for q in questions for r in (1,2)}
    records={}
    for item in run["questions"]:
        key=(item["id"],item["repeat"])
        if key not in planned or key in records:
            raise ValueError("出现重复或非计划记录")
        records[key]=item
    rows=[]
    for q in questions:
        ref=refs[q['id']]
        for repeat in (1,2):
            item=records.get((q['id'],repeat))
            result=item.get('result',{}) if item else {}
            checks=evaluation.structural_checks(result,ref)
            rows.append({"id":q['id'],"repeat":repeat,"category":ref['category'],
                "question":q['question'],"recorded":item is not None,
                "generation_complete":bool(item and item['generation_complete']),
                "automatic_checks":checks,"visible_response":result.get('response',''),
                "review_focus":ref['manual_focus'],"reviewer":None,
                "required_fact_reviews":[{"label":f[0],"expected":f[1],"source_suffix":f[2],
                    "numeric":type(f[1]) in (int,float) or (isinstance(f[1],str) and bool(re.fullmatch(r"-?\d+\.\d+",f[1]))),
                    "correct":None} for f in ref['facts']],
                "claim_reviews":[{"fact":f,"sources":{sid:result.get('sources',{}).get(sid) for sid in f['source_ids']},
                    "supported":None,"fabricated_source":None} for f in result.get('facts',[])],
                "task_complete":None,"tool_selection_correct":None,
                "boundary_correct":None,"unsupported_causal_claim":None,"rationale":None})
    return {"version":"acceptance-v21-review-template","run":str(path.resolve()),
            "run_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"planned_answers":48,
            "recorded_answers":len(records),"model_adopted":False,"semantic_scores":None,
            "review_status":"pending","rows":rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    report=prepare(args.run)
    with Path(args.output).open('x',encoding='utf-8') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2)
        handle.write('\n')
    print(json.dumps({"planned_answers":48,"recorded_answers":report['recorded_answers'],
                      "review_status":"pending","output":args.output}))


if __name__=='__main__':
    main()
