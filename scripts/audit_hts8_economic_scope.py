"""Describe eligible 3332 candidates using official child-code NAICS6 metadata.

Classification does not establish comparability. No post-policy outcomes read.
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from build_hts6_mapping import read_annual_concordance
from inventory_census_import import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def audit():
    qpath = ROOT/'data/processed/causal/hts8_candidate_qualification_v2.csv'
    ipath = ROOT/'data/processed/causal/hts8_stable_inventory.json'
    with qpath.open() as handle:
        qualified = [r for r in csv.DictReader(handle) if r['naics4']=='3332' and r['main_route_candidate']=='1']
    inventory = {r['hts8']:r for r in json.loads(ipath.read_text())['records']}
    concordance = read_annual_concordance(2018)
    rows, groups = [], defaultdict(Counter)
    for q in qualified:
        children = inventory[q['hts8']]['children']
        descriptions = [{'hts10':code, 'naics6':concordance[code]['naics6'],
                         'description':concordance[code]['description']} for code in children]
        codes = sorted({d['naics6'] for d in descriptions})
        classification = '+'.join(codes)
        groups[classification][q['metadata_role']] += 1
        rows.append({'hts8':q['hts8'], 'role':q['metadata_role'], 'naics6':codes,
                     'children':descriptions, 'china_prepolicy_value_usd':int(q['china_value_usd'])})
    return {'scope':'3332 eligible candidates, pre-policy only', 'candidates':rows,
            'counts_by_exact_naics6_set':dict(groups),
            'qualification_sha256':sha256_file(qpath), 'inventory_sha256':sha256_file(ipath),
            'conclusion':'Industry membership alone does not establish economic comparability; no matching or causal estimate.'}


if __name__ == '__main__':
    result = audit()
    path = ROOT/'docs/experiments/phase12k-economic-scope.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result['counts_by_exact_naics6_set'], ensure_ascii=False, indent=2))
