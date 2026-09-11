"""26-month candidate preparation, not matching or causal estimation."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_control_eligibility as old
from scripts.build_prepolicy_matching import compute_preperiod_features, unique_naics3

START, END = (2016, 1), (2018, 2)
MONTHS = old.month_keys(START, END)
MIN_POSITIVE = 22
PROTOCOL = ROOT / 'docs/decisions/0067-preannouncement-preparation.zh-CN.md'
OLD_FEATURES = ROOT / 'data/processed/causal/control_candidate_features.csv'


def read_panel(path):
    panel = defaultdict(dict)
    totals, positive = defaultdict(int), defaultdict(set)
    with path.open(newline='') as handle:
        for row in csv.DictReader(handle):
            month = int(row['year']), int(row['month'])
            if not START <= month <= END:
                continue
            code = row['hs6_2017']
            if month in panel[code]:
                raise ValueError(f'Duplicate {code}/{month}')
            china = int(row['china_import_value_consumption_usd'])
            world = int(row['all_origin_import_value_consumption_usd'])
            if not 0 <= china <= world:
                raise ValueError(f'Invalid amounts {code}/{month}')
            panel[code][month] = (china, world)
            totals[code] += china
            if china > 0:
                positive[code].add(month)
    observed = {m for months in panel.values() for m in months}
    if observed != set(MONTHS):
        raise ValueError('Announce-pre monthly coverage incomplete')
    return dict(panel), dict(totals), dict(positive)


def build_features(row, months):
    missing = sorted(set(MONTHS) - set(months))
    naics, reason = unique_naics3(row['naics3_candidates'])
    result = {'hs6_2017': row['hs6_2017'], 'candidate_role': row['primary_role'],
              'naics3': naics, 'industry_flag': reason,
              'missing_months': '|'.join(f'{y}-{m:02d}' for y, m in missing),
              'feature_status': 'blocked_missing_months' if missing else 'computed',
              'selection_window': '2016-01_to_2018-02',
              'proposed_list_exposure_review': 'not_yet_audited',
              'causal_adopted': False}
    if not missing:
        result.update(compute_preperiod_features(
            [months[m][0] for m in MONTHS], [months[m][1] for m in MONTHS]))
    return result


def compare_rows(new, previous):
    by_new = {r['hs6_2017']: r for r in new}
    fields = ['primary_role', 'assignment_status', 'exclusion_reasons', 'positive_pre_months',
              'minimum_positive_pre_months', 'pre_china_value_usd', 'list1_pre_china_value_usd',
              'list1_pre_value_share']
    result = []
    for code in sorted(set(by_new) | set(previous)):
        a, b = previous.get(code, {}), by_new.get(code, {})
        item = {'hs6_2017': code, 'role_changed': a.get('primary_role') != b.get('primary_role'),
                'assignment_changed': a.get('assignment_status') != b.get('assignment_status')}
        for f in fields:
            item['old_' + f] = a.get(f, '')
            item['new_' + f] = b.get(f, '')
        result.append(item)
    return result


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('x', newline='') as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader(); writer.writerows(rows)


def prepare(output):
    if output.exists():
        raise ValueError('Output directory exists; refusing overwrite')
    inputs = [old.DEFAULT_MAPPING, old.DEFAULT_LIST1_TRADE, old.DEFAULT_ALL_ORIGIN_PANEL,
              old.DEFAULT_EXPOSURE, old.DEFAULT_EXCLUSIONS, old.DEFAULT_ELIGIBILITY,
              old.DEFAULT_DESIGN, OLD_FEATURES, PROTOCOL, Path(__file__).resolve(), Path(old.__file__),
              ROOT / 'scripts/build_prepolicy_matching.py']
    before = {str(p.relative_to(ROOT)): old.sha256_file(p) for p in inputs}
    mapping, valid2018, naics = old.load_mapping(old.DEFAULT_MAPPING)
    policy_rows, policy, unmatched = old.expand_policy_exposure(old.DEFAULT_EXPOSURE, valid2018)
    if unmatched:
        raise ValueError('Unexpanded existing policy scopes')
    with old.DEFAULT_EXPOSURE.open(newline='') as handle:
        list1 = {old.digits(r['hts_code']) for r in csv.DictReader(handle) if r['policy_id'] == 'us_301_list1_2018'}
    audit, treated_values, exceptions = old.audit_list1_preperiod(
        old.DEFAULT_LIST1_TRADE, mapping, pre_start=START, pre_end=END, official_list1_hts8=list1)
    panel, totals, positive = read_panel(old.DEFAULT_ALL_ORIGIN_PANEL)
    excluded, exclusion_audit = old.map_explicit_exclusions(old.DEFAULT_EXCLUSIONS, mapping)
    rows, counts = old.classify_families(china_value_by_hs6=totals,
        positive_months_by_hs6=positive, list1_value_by_hs6=treated_values, policy_hs6=policy,
        explicit_exclusion_hs6=excluded, naics3_by_hs6=naics,
        minimum_positive_months=MIN_POSITIVE, selection_window='2016-01_to_2018-02')
    candidates = [r for r in rows if r['primary_role'] != 'excluded']
    features = [build_features(r, panel[r['hs6_2017']]) for r in candidates]
    role_values = Counter()
    for row in candidates:
        role_values[row['primary_role']] += row['pre_china_value_usd']
    for row in rows:
        row.update(proposed_list_exposure_review='not_yet_audited', causal_adopted=False)
        denominator = role_values[row['primary_role']]
        row['candidate_role_value_share'] = row['pre_china_value_usd'] / denominator if denominator else ''
    with old.DEFAULT_ELIGIBILITY.open(newline='') as handle:
        previous = {r['hs6_2017']: r for r in csv.DictReader(handle)}
    diff = compare_rows(rows, previous)
    with OLD_FEATURES.open(newline='') as handle:
        prior_features = {r['hs6_2017']: r for r in csv.DictReader(handle)}
    new_features = {r['hs6_2017']: r for r in features}
    feature_diff = []
    for code in sorted(set(prior_features) | set(new_features)):
        item = {'hs6_2017': code, 'new_feature_status': new_features.get(code, {}).get('feature_status', 'not_candidate')}
        for field in ('log_mean_monthly_china_import_value', 'pretrend_slope', 'monthly_volatility', 'china_share_of_all_origin_imports'):
            item['old_' + field] = prior_features.get(code, {}).get(field, '')
            item['new_' + field] = new_features.get(code, {}).get(field, '')
        feature_diff.append(item)
    transitions = Counter(f"{r['old_primary_role'] or 'absent'} -> {r['new_primary_role'] or 'absent'}" for r in diff)
    if any(old.sha256_file(ROOT / p) != digest for p, digest in before.items()):
        raise ValueError('Inputs changed during preparation')
    report = {
        'status': 'prepared_not_adopted_pending_policy_scope_review', 'protocol': '0067',
        'window': ['2016-01', '2018-02'], 'months': 26, 'minimum_positive_months': MIN_POSITIVE,
        'model_calls': 0, 'optimization_calls': 0, 'post_announcement_amounts_used_for_selection': False,
        'input_sha256': before, 'classification_counts': dict(counts),
        'mapping_audit': audit, 'exclusion_audit': exclusion_audit,
        'role_transitions': dict(sorted(transitions.items())),
        'role_changed_count': sum(r['role_changed'] for r in diff),
        'assignment_changed_count': sum(r['assignment_changed'] for r in diff),
        'assignment_changed_among_present_in_both': sum(r['assignment_changed'] and bool(r['old_assignment_status']) and bool(r['new_assignment_status']) for r in diff),
        'absent_in_new_window': [r['hs6_2017'] for r in diff if not r['new_primary_role']],
        'feature_status_counts': dict(Counter(r['feature_status'] for r in features)),
        'candidate_role_value_totals': dict(role_values),
        'feature_industry_flag_counts': dict(Counter(r['industry_flag'] or 'unique' for r in features)),
        'blockers': ['Proposed April list exposure not mapped; control_candidate is not verified anticipation-free.',
                     'Description-based exclusions are not fully coded; no continuously-active-duty estimand.',
                     'Aggregate source zeros and economic comparability require separate review.'],
        'old_causal_status': json.loads(old.DEFAULT_DESIGN.read_text())['status'],
        'causal_adopted': False,
    }
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / 'candidate_eligibility.csv', rows)
    write_csv(output / 'candidate_features.csv', features)
    write_csv(output / 'old_new_comparison.csv', diff)
    write_csv(output / 'old_new_features.csv', feature_diff)
    write_csv(output / 'policy_scope.csv', policy_rows)
    if exceptions:
        write_csv(output / 'mapping_exceptions.csv', exceptions)
    report['output_sha256'] = {p.name: old.sha256_file(p) for p in sorted(output.glob('*.csv'))}
    with (output / 'summary.json').open('x') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False); handle.write('\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.output)
    print(json.dumps({k: result[k] for k in ['status','role_transitions','feature_status_counts','mapping_audit']}, ensure_ascii=False, indent=2))
