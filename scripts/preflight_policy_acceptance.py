"""Freeze then inspect a prospective policy module check. Never calls a model."""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tradeintel_ai.policy_workflow import load_frozen_corpus
from tradeintel_ai.policy_retrieval import PolicyRetriever

FILES=[
    'evals/policy_acceptance_v1.json','docs/decisions/0060-policy-prospective-acceptance.zh-CN.md',
    'src/tradeintel_ai/policy_workflow.py','src/tradeintel_ai/policy_response_format.py',
    'src/tradeintel_ai/policy_retrieval.py','src/tradeintel_ai/model_adapter.py',
    'src/tradeintel_ai/agent.py',
    'docs/experiments/phase13a-policy-retrieval/corpus.json',
    'scripts/preflight_policy_acceptance.py']
OUTPUT=ROOT/'docs/experiments/phase13f-preflight'


def inspect_cases(cases,retriever):
    rows=[]
    seen=set()
    for case in cases:
        if case['id'] in seen: raise ValueError('Duplicate question ID')
        seen.add(case['id'])
        found=retriever.search(case['question'],as_of=case['as_of'])
        violation=case['expected']=='no_evidence' and bool(found['hits'])
        rows.append({'id':case['id'],'status':found['status'],
            'evidence_ids':[h['id'] for h in found['hits']],
            'reason':found.get('reason'),'zero_call_boundary_violation':violation,
            'answer_quality':'not_evaluated'})
    return {'new_api_calls':0,'boundary_preflight_passed':not any(r['zero_call_boundary_violation'] for r in rows),
            'cases':rows,'semantic_acceptance':'not_run'}


def main():
    # Exclusive output: do not silently overwrite a frozen experiment.
    OUTPUT.mkdir(parents=True,exist_ok=False)
    fingerprints={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES}
    with (OUTPUT/'manifest.json').open('x') as file:
        json.dump({'files':fingerprints,'max_model_calls':5,'scope':'policy_module_only'},file,indent=2)
    corpus=load_frozen_corpus(ROOT)
    cases=json.loads((ROOT/FILES[0]).read_text())['cases']
    result=inspect_cases(cases,PolicyRetriever(corpus))
    with (OUTPUT/'result.json').open('x') as file:
        json.dump(result,file,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
