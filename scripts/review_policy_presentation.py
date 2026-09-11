"""Review saved model wording offline; do not alter archived answers."""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tradeintel_ai.policy_focus import presentation_flags


if __name__=='__main__':
    sources=['tmp/policy-acceptance-13g/P01','tmp/policy-acceptance-13g/P02','tmp/policy-context-13i']
    rows=[]
    for relative in sources:
        path=ROOT/relative
        result=json.loads((path/'result.json').read_text())
        evidence=json.loads((path/'evidence.json').read_text())
        rows.append({'source':relative,'original_sha256':hashlib.sha256((path/'result.json').read_bytes()).hexdigest(),
                     **presentation_flags(evidence['question'],result['generation'])})
    output=ROOT/'docs/experiments/phase13j-presentation.json'
    with output.open('x') as f:json.dump({'new_api_calls':0,'label':'heuristic_review_not_accuracy','cases':rows},f,ensure_ascii=False,indent=2)
    print(json.dumps(rows,ensure_ascii=False,indent=2))
