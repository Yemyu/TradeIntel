"""Describe policy-pre comparison support; no matching or effect estimation."""
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ('log_mean_monthly_china_import_value', 'pretrend_slope',
            'monthly_volatility', 'china_share_of_all_origin_imports')


def diagnose(path):
    with path.open(newline='') as handle:
        records = list(csv.DictReader(handle))
    if len({r['hs6_2017'] for r in records}) != len(records):
        raise ValueError('Duplicate product')
    if not records or any(not math.isfinite(float(r[f])) for r in records
                          for f in (*FEATURES, 'total_china_import_value_usd')):
        raise ValueError('Empty or nonfinite feature data')
    if any(r['selection_window'] != '2016-01_to_2018-05'
           or r['post_policy_activity_used_for_matching'] != '0' for r in records):
        raise ValueError('Unexpected feature window or post-policy selection')
    groups = defaultdict(lambda: {'treated': [], 'control': []})
    treated_all = [r for r in records if r['primary_role'] == 'treated_candidate']
    for row in records:
        if row['match_eligible'] != '1':
            continue
        role = {'treated_candidate': 'treated', 'control_candidate': 'control'}.get(row['primary_role'])
        if role:
            groups[row['naics3']][role].append(row)
    denominator = sum(float(r['total_china_import_value_usd']) for r in treated_all)
    if denominator <= 0:
        raise ValueError('No positive treated pre-policy value')
    rows = []
    for industry, group in sorted(groups.items()):
        treated, controls = group['treated'], group['control']
        if not treated:
            continue
        outside = {f: [] for f in FEATURES}
        for feature in FEATURES:
            values = [float(r[feature]) for r in controls]
            for row in treated:
                if not values or not min(values) <= float(row[feature]) <= max(values):
                    outside[feature].append(row['hs6_2017'])
        outside_any = set().union(*map(set, outside.values()))
        inside = [r for r in treated if r['hs6_2017'] not in outside_any]
        value = sum(float(r['total_china_import_value_usd']) for r in treated)
        rows.append({'naics3': industry, 'treated': len(treated), 'controls': len(controls),
                     'treated_pre_value_share': value / denominator,
                     'inside_each_feature_range': len(inside),
                     'inside_pre_value_share': sum(float(r['total_china_import_value_usd']) for r in inside) / denominator,
                     'outside_by_feature': {f: len(ids) for f, ids in outside.items()},
                     'outside_product_ids': outside})
    return {'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'feature_window': '2016-01_to_2018-05', 'post_outcomes_read': False,
            'new_matching_run': False, 'effect_estimated': False,
            'all_treated_candidates': len(treated_all),
            'eligible_treated': sum(r['treated'] for r in rows),
            'outside_counts': {f: sum(r['outside_by_feature'][f] for r in rows) for f in FEATURES},
            'inside_each_feature_range': sum(r['inside_each_feature_range'] for r in rows),
            'industries': rows,
            'limitation': 'Marginal ranges do not establish joint overlap, balance, parallel trends, or a usable matched sample. No industry is adopted.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(ROOT / 'data/processed/causal/control_candidate_features.csv')
    with args.output.open('x') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'industries'}, ensure_ascii=False, indent=2))
    for r in sorted(report['industries'], key=lambda x: -x['treated_pre_value_share']):
        print(r['naics3'], r['treated'], r['controls'], r['inside_each_feature_range'],
              round(r['treated_pre_value_share'] * 100, 2), r['outside_by_feature'])
