"""Read-only structural audit; NEVER optimizes, fits, or updates old results.

The matrix checks use arbitrary deterministic vectors, not candidate solutions.
Only policy-pre amounts enter the coverage and balance checks.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, stdev
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_prepolicy_matching as v1
from scripts import build_globally_balanced_matching as v2
from scripts import build_maximum_cardinality_matching as v3


def pooled_sd(first, second):
    # Frozen protocol uses degrees-of-freedom weighting, not equal group weights.
    return math.sqrt(((len(first) - 1) * stdev(first) ** 2 + (len(second) - 1) * stdev(second) ** 2) / (len(first) + len(second) - 2))


def independent_smd(records, pairs):
    treated = [v for v in records.values() if v['match_eligible'] and v['primary_role'] == 'treated_candidate']
    controls = [v for v in records.values() if v['match_eligible'] and v['primary_role'] == 'control_candidate']
    selected = sorted({p['treated_hs6'] for p in pairs})
    result = {}
    for feature in v1.CONTINUOUS_FEATURES:
        denominator = pooled_sd([v[feature] for v in treated], [v[feature] for v in controls])
        control_mean = sum(records[p['control_hs6']][feature] * float(p['edge_weight']) for p in pairs) / sum(float(p['edge_weight']) for p in pairs)
        result[feature] = (mean(records[k][feature] for k in selected) - control_mean) / denominator
    return result


def matrix_audit(records):
    edges, te, ce, _ = v3.build_edges(records)
    treated = sorted(k for k, v in records.items() if v['match_eligible'] and v['primary_role'] == 'treated_candidate')
    controls = sorted(k for k, v in records.items() if v['match_eligible'] and v['primary_role'] == 'control_candidate')
    matrix, _, _, _ = v3._build_matrix(records, edges, te, ce, include_minimum=True)
    rng = np.random.default_rng(20260911)
    max_error = 0.0
    for _ in range(5):
        # These are test vectors only. No attempt to satisfy constraints.
        x = rng.random(len(edges))
        z = dict(zip(treated, rng.random(len(treated))))
        direct = [sum(x[i] for i in te[k]) - 3 * z[k] for k in sorted(te)]
        direct += [sum(x[i] for i in ce[k]) for k in sorted(ce)]
        for f in v1.CONTINUOUS_FEATURES:
            sd = pooled_sd([records[k][f] for k in treated], [records[k][f] for k in controls])
            difference = 3 * sum(z[k] * records[k][f] for k in treated) - sum(x[i] * records[e['control_hs6']][f] for i, e in enumerate(edges))
            tolerance = 3 * v3.INTERNAL_SMD_LIMIT * sd * sum(z.values())
            direct.extend([difference - tolerance, -difference - tolerance])
        direct.append(sum(z.values()))
        actual = matrix @ np.concatenate([x, list(z.values())])
        max_error = max(max_error, float(np.max(np.abs(actual - np.array(direct)))))
    return {
        'treated': len(treated), 'controls': len(controls), 'edges': len(edges),
        'matrix_shape': list(matrix.shape), 'tested_vectors': 5,
        'maximum_absolute_formula_error': max_error,
        'formula_check_passed': max_error < 1e-7,
        'treated_without_edges': sorted(set(treated) - set(te)),
        'minimum_control_degree': min(map(len, te.values())),
        'matrix_variable_count': matrix.shape[1],
        'solver_cost_variable_count': len(edges) + len(te),
    }


def prepanel_audit(path, eligible):
    expected = {(k, y, m) for k in eligible for y, m in v1.month_keys(v1.PRE_START, v1.PRE_END)}
    seen, duplicate, blank = set(), [], []
    with path.open(newline='') as handle:
        for row in csv.DictReader(handle):
            key = row['hs6_2017'], int(row['year']), int(row['month'])
            if key not in expected:
                continue  # never access policy-post amounts
            if key in seen:
                duplicate.append(key)
            seen.add(key)
            if any(not row[f].strip() for f in ('china_import_value_consumption_usd', 'all_origin_import_value_consumption_usd')):
                blank.append(key)
    return {'expected_rows': len(expected), 'present_rows': len(seen),
            'missing_keys': sorted(expected - seen), 'duplicate_keys': duplicate, 'blank_value_keys': blank,
            'limitation': 'Presence of aggregate rows does not independently prove absent source-country observations are true zeros.'}


def audit():
    records = v2.load_feature_records(v1.DEFAULT_FEATURES)
    with v1.DEFAULT_PAIRS.open(newline='') as handle:
        pairs = list(csv.DictReader(handle))
    baseline = json.loads(v1.DEFAULT_REPORT_JSON.read_text())
    archived = json.loads((v1.CAUSAL_DIR / 'matching_balance_report_v3.json').read_text())
    smd = independent_smd(records, pairs)
    matrix = matrix_audit(records)
    inputs = [v1.DEFAULT_FEATURES, v1.DEFAULT_PAIRS, v1.DEFAULT_DESIGN, v1.DEFAULT_PANEL,
              v1.DEFAULT_REPORT_JSON, v1.CAUSAL_DIR / 'matching_balance_report_v3.json',
              Path(v1.__file__), Path(v2.__file__), Path(v3.__file__), Path(__file__).resolve()]
    return {
        'audit_id': 'frozen-causal-structural-audit-20260911',
        'optimization_calls': 0, 'effect_estimation_calls': 0, 'model_calls': 0,
        'old_results_modified': False, 'post_outcomes_used_for_selection': False,
        'input_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        'matrix': matrix,
        'matches_archived_matrix_dimensions': matrix['matrix_shape'] == [archived['solver']['stage_one']['constraint_count'], archived['solver']['stage_one']['variable_count']],
        'nonfinite_feature_cells': sum(not math.isfinite(v[f]) for v in records.values() for f in v1.CONTINUOUS_FEATURES),
        'baseline_smd': smd,
        'maximum_smd_difference_from_archive': max(abs(smd[f] - baseline['balance']['features'][f]['matched_smd']) for f in smd),
        'prepanel': prepanel_audit(v1.DEFAULT_PANEL, {k for k, v in records.items() if v['match_eligible']}),
        'interpretation': ('Structural checks agree; not an independent solver infeasibility proof.'
                           if matrix['formula_check_passed'] and max(abs(smd[f] - baseline['balance']['features'][f]['matched_smd']) for f in smd) < 1e-9
                           else 'Structural discrepancy requires review; no causal or solver conclusion.'),
        'method_issues_requiring_new_protocol': [
            'Clean-pre label includes March action and April proposed-list announcement; anticipation must be reassessed.',
            'Infeasibility applies to internal SMD <= 0.09, not every design permitting SMD < 0.10.',
            'Three controls, reuse <= 10 and 80 percent coverage are protocol choices, not universal causal identification laws.',
            'Distance and effective-sample-size gates are post-solution adoption checks, not causes of stage-one infeasibility.',
        ],
        'latent_code_risks_not_triggered_by_current_inputs': [
            'v3 sizes cost vector by treated with edges but matrix by all treated; a no-edge treated would cause a dimension mismatch.',
            'v1 converts missing panel rows/empty amount cells to zero; this scan found none among eligible pre rows but cannot validate source-level structural zeros.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Audit output already exists; refusing to overwrite')
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\n')
    print(json.dumps({k: result[k] for k in ('audit_id', 'optimization_calls', 'matches_archived_matrix_dimensions', 'maximum_smd_difference_from_archive')}))


if __name__ == '__main__':
    main()
