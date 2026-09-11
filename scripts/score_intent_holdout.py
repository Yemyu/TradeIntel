"""Verify 48 planned slots and require explicit semantic review for adoption gates."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.tradeintel_ai.intent_catalog import propose_catalog
from scripts.check_intent_development import canonical, RecordedModel


def aggregate(rows, complete):
    rounds={}
    for repeat in (1,2):
        current=[r for r in rows if r['repeat']==repeat]
        reviewed=all(r['review'] is not None for r in current)
        def semantic(r):
            return bool(r['review'] and r['recorded'] and r['parse_outcome'] in ('validated_proposal','model_clarification')
                        and r['review']['semantic_correct'] and r['review']['quotes_supported']
                        and not r['review']['unsafe_scope_change'])
        n=sum(semantic(r) for r in current)
        clarifies=[r for r in current if r['category']=='clarify']
        cq=sum(semantic(r) and r['parse_outcome']=='model_clarification' for r in clarifies)
        unsafe=sum(bool(r['review'] and r['review']['unsafe_scope_change']) for r in current)
        rounds[str(repeat)]={'planned':24,'recorded':sum(r['recorded'] for r in current),
                            'exact_matches':sum(r['exact_match'] for r in current),
                            'semantic_correct':n if reviewed else None,
                            'required_clarifications_correct':cq if reviewed else None,
                            'unsafe_scope_changes':unsafe if reviewed else None,
                            'review_complete':reviewed,
                            'gate_passed':bool(complete and reviewed and len(current)==24 and n>=22 and cq==4 and unsafe==0)}
    return rounds


def score(path, review_path=None):
    path=Path(path);raw=path.read_bytes();run=json.loads(raw)
    run_sha=hashlib.sha256(raw).hexdigest()
    manifest_path=ROOT/'evals/intent_holdout_manifest.json'
    if run['manifest']!=json.loads(manifest_path.read_text()) or run['manifest_sha256']!=hashlib.sha256(manifest_path.read_bytes()).hexdigest():
        raise ValueError('manifest mismatch')
    for relative,expected in run['manifest']['files'].items():
        p=(ROOT/relative).resolve()
        if not p.is_relative_to(ROOT) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('source mismatch')
    events=[json.loads(l) for l in path.with_suffix('.jsonl').read_text().splitlines()]
    if [e['item'] for e in events if e['event']=='answer_recorded']!=run['questions']:raise ValueError('journal mismatch')
    if events[-1]['event']!='run_finished' or events[-1]['status']!=run['status']:raise ValueError('no consistent end')
    if sum(e['event']=='request_started' for e in events)!=run['api_requests']:raise ValueError('attempt count mismatch')
    refs=json.loads((ROOT/'evals/intent_holdout_reference.json').read_text())
    questions={q['id']:q['question'] for q in map(json.loads,(ROOT/'evals/intent_holdout_questions.jsonl').read_text().splitlines())}
    records={};reviews={};reviewer=None
    for q in run['questions']:
        key=(q['id'],q['repeat'])
        if key in records or q['id'] not in questions or q['repeat'] not in (1,2):raise ValueError('invalid slot')
        if q['question']!=questions[q['id']]:raise ValueError('question mismatch')
        if q['response'] is not None and propose_catalog(q['question'],RecordedModel(q['response']))!=q['result']:
            raise ValueError('replay mismatch')
        records[key]=q
    if review_path:
        review=json.loads(Path(review_path).read_text());reviewer=review.get('reviewer')
        if review['run_sha256']!=run_sha or not isinstance(reviewer,str) or not reviewer.strip():raise ValueError('invalid review attribution')
        for r in review['rows']:
            key=(r['id'],r['repeat'])
            if key in reviews or key not in {(i,n) for i in refs for n in (1,2)}:raise ValueError('invalid review slot')
            if any(type(r.get(k)) is not bool for k in ('semantic_correct','quotes_supported','unsafe_scope_change')):
                raise ValueError('explicit booleans required')
            if not isinstance(r.get('reason'),str) or not r['reason'].strip():raise ValueError('review reason required')
            reviews[key]=r
    rows=[];tokens=0
    for ident,ref in refs.items():
        for repeat in (1,2):
            q=records.get((ident,repeat));result=q['result'] if q else {}
            outcome=result.get('parse_outcome','missing_record')
            exact=(outcome=='model_clarification' if ref['expected'] is None else
                   outcome=='validated_proposal' and canonical(result['request'])==canonical(ref['expected']))
            if q and q['response']:tokens+=q['response']['metadata'].get('usage',{}).get('total_tokens',0)
            rows.append({'id':ident,'repeat':repeat,'category':ref['category'],'question':questions[ident],
                         'recorded':q is not None,'parse_outcome':outcome,'exact_match':bool(exact),
                         'request':result.get('request'),'evidence':result.get('evidence'),
                         'review':reviews.get((ident,repeat))})
    complete=run['status']=='collected_not_scored' and len(records)==48 and all(not q['result'].get('executed') for q in records.values())
    rounds=aggregate(rows,complete)
    return {'run_sha256':run_sha,'model':'glm-4.7','api_requests':run['api_requests'],'reported_tokens':tokens,
            'rounds':rounds,'rows':rows,'reviewer':reviewer,'independent_human_review':False,
            'internal_holdout_passed':all(r['gate_passed'] for r in rounds.values()),
            'production_model_adopted':False,'api_calls_for_scoring':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run');p.add_argument('--review');p.add_argument('--output',required=True);a=p.parse_args()
    result=score(a.run,a.review)
    with Path(a.output).open('x',encoding='utf-8') as h:json.dump(result,h,ensure_ascii=False,indent=2);h.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
