"""One frozen offline development comparison; no model calls."""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tradeintel_ai.policy_workflow import load_frozen_corpus
from tradeintel_ai.policy_retrieval import PolicyRetriever
from tradeintel_ai.policy_context_window import expand_context


def main():
    out=ROOT/'docs/experiments/phase13h-context'
    out.mkdir(parents=True,exist_ok=False)
    files=['docs/decisions/0061-policy-context-window.zh-CN.md','src/tradeintel_ai/policy_context_window.py',
           'scripts/check_policy_context_window.py','evals/policy_acceptance_v1.json']
    (out/'manifest.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},indent=2))
    corpus=load_frozen_corpus(ROOT)
    retriever=PolicyRetriever(corpus)
    rows=[]
    for c in json.loads((ROOT/'evals/policy_acceptance_v1.json').read_text())['cases']:
        old=retriever.search(c['question'],as_of=c['as_of'])
        new=expand_context(old,corpus)
        phrase='in addition to all other applicable duties'
        def contains(hits): return any(phrase in ' '.join(h['text'].split()).lower() for h in hits)
        rows.append({'id':c['id'],**new['context_expansion'],
                     'old_has_additional_duties_clause':contains(old['hits']),
                     'new_has_additional_duties_clause':contains(new['hits']),
                     'same_hit_parents':[h['parent_chunk_id'] for h in new['hits']]==[h['id'] for h in old['hits']],
                     'status_unchanged':old['status']==new['status']})
        (out/(c['id']+'.json')).write_text(json.dumps(new,ensure_ascii=False,indent=2))
    result={'label':'exposed_question_offline_context_diagnostic','new_api_calls':0,'cases':rows}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
