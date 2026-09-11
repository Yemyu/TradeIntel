"""Inventory economic comparison families, without reading outcome values."""
import csv
import hashlib
import json
from collections import defaultdict, Counter
from pathlib import Path
from build_hts6_mapping import read_annual_concordance

ROOT = Path(__file__).resolve().parents[1]


def summarize(records):
    groups = defaultdict(Counter)
    for r in records:
        if len(r['naics6']) != 1:
            continue
        key = r['naics6'][0] + ':' + r['hs6'][:4]
        groups[key][r['role']] += 1
    return {k: dict(v) for k, v in sorted(groups.items())}


def audit():
    risk = ROOT/'docs/experiments/proposal-scope-audit/candidate_proposal_risk.csv'
    mapping = ROOT/'data/processed/causal/hts_history_mapping.csv'
    concord = read_annual_concordance(2018)
    children = defaultdict(list)
    with mapping.open() as f:
        for r in csv.DictReader(f):
            if r['source_year'] == '2018' and r['historical_validity_status'] == 'valid':
                children[r['hs6_2017']].append(r)
    records = []
    with risk.open() as f:
        for r in csv.DictReader(f):
            role = ('treated' if r['candidate_role'] == 'treated_candidate' else
                    'proposal_control' if r['proposal_overlap'] == 'True' else 'nonproposal_control')
            details = [{'hts10': c['source_hts10'], 'naics6': c['naics6'],
                        'description': concord.get(c['source_hts10'], {}).get('description', '')}
                       for c in children[r['hs6_2017']]]
            records.append({'hs6': r['hs6_2017'], 'role': role,
                            'naics6': sorted({c['naics6'] for c in details}), 'children': details})
    groups = summarize(records)
    return {'status': 'metadata_inventory_not_comparability_adoption',
            'records': records, 'groups': groups,
            'two_sided_nonproposal_groups': {k:v for k,v in groups.items()
                if v.get('treated', 0) and v.get('nonproposal_control', 0)},
            'input_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (risk, mapping, Path(__file__))},
            'outcome_values_used': False, 'causal_adopted': False}


if __name__ == '__main__':
    result = audit()
    target = ROOT/'docs/experiments/comparison-family-audit.json'
    with target.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps(result['two_sided_nonproposal_groups'], indent=2))
