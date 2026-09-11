"""Pre-policy geometry diagnostics; never estimates effects or adopts weights."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import linprog

from diagnose_prepolicy_support import FEATURES, diagnose

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = '4bca77853b5a2171618fb049859da8a6a79fbcca69309cba718272ba4eff9132'


def solve(c, *, A_ub, b_ub, A_eq, b_eq):
    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                     bounds=(0, None), method='highs', options={'time_limit': 5})
    if result.status == 2:
        return None
    if not result.success:
        raise RuntimeError(f'Diagnostic solver failed: {result.status}')
    x = result.x
    # Independent scalar sums avoid platform BLAS warnings and validate finiteness.
    if not np.isfinite(x).all():
        raise RuntimeError('Nonfinite solver solution')
    ub = np.array([math.fsum(float(a)*float(b) for a,b in zip(row,x)) for row in A_ub])
    eq = np.array([math.fsum(float(a)*float(b) for a,b in zip(row,x)) for row in A_eq])
    if (not np.isfinite(ub).all() or not np.isfinite(eq).all()
            or np.max(ub - b_ub) > 1e-7 or np.max(np.abs(eq - b_eq)) > 1e-7
            or np.min(x) < -1e-7):
        raise RuntimeError('Solution residual check failed')
    return x


def joint_residual(controls, target):
    """Minimum standardized L-infinity distance to the control convex hull."""
    controls = np.asarray(controls, dtype=float)
    target = np.asarray(target, dtype=float)
    n, k = controls.shape
    scale = controls.std(axis=0, ddof=1) if n > 1 else np.ones(k)
    scale = np.where(scale > 0, scale, 1.0)
    centered = ((controls - target) / scale).T
    A = np.vstack([np.column_stack([centered, -np.ones(k)]),
                   np.column_stack([-centered, -np.ones(k)])])
    eq = np.array([[*np.ones(n), 0.]])
    x = solve(np.r_[np.zeros(n), 1.], A_ub=A, b_ub=np.zeros(2*k), A_eq=eq, b_eq=np.ones(1))
    if x is None:
        raise RuntimeError('Residual problem unexpectedly infeasible')
    return float(x[-1])


def balanced_mean(controls, treated, tolerance=0.09):
    controls, treated = np.asarray(controls, float), np.asarray(treated, float)
    n, k = controls.shape
    # Same pooled sample SD formula as a two-group balance diagnostic, within industry.
    scale = np.sqrt(((n-1)*controls.var(axis=0, ddof=1)
                     +(len(treated)-1)*treated.var(axis=0, ddof=1))/(n+len(treated)-2))
    scale = np.where(scale > 0, scale, 1.)
    centered = ((controls - treated.mean(axis=0))/scale).T
    A = np.vstack([np.column_stack([centered, np.zeros(k)]),
                   np.column_stack([-centered, np.zeros(k)]),
                   np.column_stack([np.eye(n), -np.ones(n)])])
    x = solve(np.r_[np.zeros(n), 1.], A_ub=A, b_ub=np.r_[np.full(2*k, tolerance), np.zeros(n)],
              A_eq=np.array([[*np.ones(n), 0.]]), b_eq=np.ones(1))
    if x is None:
        return {'feasible': False}
    weights = x[:-1]
    return {'feasible': True, 'minimum_maximum_weight': float(x[-1]),
            'effective_control_count': float(1 / np.sum(weights**2)),
            'positive_weight_controls': int(np.sum(weights > 1e-7)),
            'max_abs_standardized_mean_difference': max(abs(math.fsum(float(a)*float(b) for a,b in zip(row, weights))) for row in centered),
            'weights_adopted': False}


def run():
    source = ROOT / 'data/processed/causal/control_candidate_features.csv'
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('Feature fingerprint mismatch')
    diagnose(source)  # validates unique IDs, window, finite values, no post-selection flag
    with source.open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    all_value = sum(float(r['total_china_import_value_usd']) for r in rows if r['primary_role']=='treated_candidate')
    reports = []
    for industry in ('333', '334'):
        group = [r for r in rows if r['naics3']==industry and r['match_eligible']=='1']
        treated = [r for r in group if r['primary_role']=='treated_candidate']
        controls = [r for r in group if r['primary_role']=='control_candidate']
        C = np.array([[float(r[f]) for f in FEATURES] for r in controls])
        T = np.array([[float(r[f]) for f in FEATURES] for r in treated])
        details = []
        for row, target in zip(treated, T):
            residual = joint_residual(C, target)
            details.append({'hs6': row['hs6_2017'], 'residual': residual, 'geometrically_representable': residual<=1e-7,
                            'pre_value': float(row['total_china_import_value_usd'])})
        inside = [r for r in details if r['geometrically_representable']]
        total = sum(r['pre_value'] for r in details)
        entry = {'industry': industry, 'treated_count': len(T), 'control_count': len(C),
                 'joint_representable_count': len(inside),
                 'joint_representable_pre_value_share_within_industry': sum(r['pre_value'] for r in inside)/total,
                 'joint_representable_pre_value_share_all_candidates': sum(r['pre_value'] for r in inside)/all_value,
                 'residual_quantiles': dict(zip(('median','p90','max'), map(float, np.quantile([r['residual'] for r in details], [.5,.9,1])))),
                 'full_industry_mean_balance': balanced_mean(C,T), 'products': details}
        reports.append(entry)
        print(json.dumps({k:v for k,v in entry.items() if k!='products'}, ensure_ascii=False), flush=True)
    return {'source_sha256': SOURCE_SHA, 'scipy_version': scipy.__version__,
            'protocol_sha256': hashlib.sha256((ROOT/'docs/decisions/0041-joint-support-protocol.zh-CN.md').read_bytes()).hexdigest(),
            'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'post_outcomes_read': False, 'causal_estimate_produced': False, 'sample_adopted': False,
            'industries': reports}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.output.open('x') as handle:
        json.dump(run(), handle, ensure_ascii=False, indent=2)
