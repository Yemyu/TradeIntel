"""Fixed internal temporal validation of a pre-policy weighted comparator."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
MONTHS = [(y, m) for y in (2016, 2017, 2018) for m in range(1, 13) if (y,m)<=(2018,5)]


def predict(X, w):
    return np.array([math.fsum(float(a)*float(b) for a,b in zip(row,w)) for row in X])


def fit(X, y):
    X, y = np.asarray(X, float), np.asarray(y, float)
    n = X.shape[1]
    if n < 10 or len(y) != len(X) or not np.isfinite(X).all() or not np.isfinite(y).all():
        raise ValueError('Invalid training inputs')
    uniform = np.full(n, 1/n)
    def loss(w):
        residual = predict(X,w)-y
        return float(np.mean(residual**2)+.001*np.sum((w-uniform)**2))
    def gradient(w):
        residual = predict(X,w)-y
        return np.array([2*math.fsum(float(a)*float(b) for a,b in zip(X[:,j],residual))/len(y)
                         for j in range(n)]) + .002*(w-uniform)
    result = minimize(loss, uniform, jac=gradient, method='SLSQP', bounds=[(0,.1)]*n,
                      constraints={'type':'eq','fun':lambda w: np.sum(w)-1,
                                   'jac':lambda w: np.ones(n)},
                      options={'maxiter':1000,'ftol':1e-12})
    w=result.x
    if (not result.success or not np.isfinite(w).all() or abs(sum(w)-1)>1e-7
            or min(w)<-1e-7 or max(w)>.1000001):
        raise RuntimeError('Weight optimization failed validation')
    return w


def metrics(actual, predicted):
    delta = np.asarray(actual)-np.asarray(predicted)
    return {'rmse':float(np.sqrt(np.mean(delta**2))), 'max_abs_error':float(np.max(np.abs(delta)))}


def evaluate(X, y):
    w=fit(X[:24],y[:24])
    estimate=predict(X,w)
    equal=X.mean(axis=1)
    seasonal=equal[24:]+(y[12:17]-equal[12:17])
    main=metrics(y[24:],estimate[24:])
    baseline=metrics(y[24:],equal[24:])
    season=metrics(y[24:],seasonal)
    drop=int(np.argmax(w))
    reduced=np.delete(X,drop,axis=1)
    reduced_w=fit(reduced[:24],y[:24])
    sensitivity=float(np.max(np.abs(predict(reduced[24:],reduced_w)-estimate[24:])))
    ess=float(1/np.sum(w*w))
    gates={'rmse':main['rmse']<=.10, 'maximum_error':main['max_abs_error']<=.20,
           'beats_both_baselines_by_20pct':main['rmse']<=.8*min(baseline['rmse'],season['rmse']),
           'effective_controls':ess>=20, 'remove_largest_control':sensitivity<=.05}
    return {'proceed_to_research_design':all(gates.values()), 'gates':gates,
            'fit_metrics':metrics(y[:24],estimate[:24]), 'validation_metrics':main,
            'equal_weight_baseline':baseline, 'seasonal_gap_baseline':season,
            'effective_controls':ess, 'max_control_weight':float(max(w)),
            'drop_largest_validation_max_change':sensitivity, 'dropped_control_index':drop,
            'weights':w.tolist(), 'target':y.tolist(), 'prediction':estimate.tolist()}


def run():
    source=ROOT/'data/processed/causal/control_candidate_features.csv'
    if hashlib.sha256(source.read_bytes()).hexdigest()!='4bca77853b5a2171618fb049859da8a6a79fbcca69309cba718272ba4eff9132':
        raise ValueError('Unexpected feature source')
    with source.open(newline='') as f:
        candidates=[r for r in csv.DictReader(f) if r['naics3']=='333' and r['match_eligible']=='1']
    treated=sorted(r['hs6_2017'] for r in candidates if r['primary_role']=='treated_candidate')
    controls=sorted(r['hs6_2017'] for r in candidates if r['primary_role']=='control_candidate')
    if (len(treated),len(controls))!=(158,61):raise ValueError('Unexpected population')
    wanted=set(treated+controls); values={}; monthset=set(MONTHS)
    panel=ROOT/'data/processed/causal/causal_trade_hs6_monthly.csv'
    with panel.open(newline='') as f:
        for r in csv.DictReader(f):
            month=(int(r['year']),int(r['month']))
            if month not in monthset or r['hs6_2017'] not in wanted:continue
            key=(r['hs6_2017'],month)
            if key in values:raise ValueError('Duplicate product month')
            value=int(r['china_import_value_consumption_usd'])
            if value<0:raise ValueError('Negative amount')
            values[key]=math.log1p(value)
    if len(values)!=len(wanted)*len(MONTHS):raise ValueError('Missing product months')
    def matrix(ids):
        result=np.array([[values[(hs,m)] for hs in ids] for m in MONTHS])
        return result-result[:12].mean(axis=0)
    X=matrix(controls); y=matrix(treated).mean(axis=1)
    result=evaluate(X,y)
    result.update(industry='333',treated_count=len(treated),control_count=len(controls),
                  control_ids=controls,months=[f'{y}-{m:02d}' for y,m in MONTHS],
                  model_api_calls=0,causal_estimate_produced=False,independent_holdout=False,
                  post_policy_amounts_parsed=False,
                  protocol_sha256=hashlib.sha256((ROOT/'docs/decisions/0043-prepolicy-trajectory-protocol.zh-CN.md').read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  panel_sha256=hashlib.sha256(panel.read_bytes()).hexdigest())
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    with args.output.open('x') as f:
        r=run();json.dump(r,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in r.items() if k not in ('weights','target','prediction','control_ids','months')},ensure_ascii=False,indent=2))
