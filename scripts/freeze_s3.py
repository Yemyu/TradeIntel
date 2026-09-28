"""Freeze reviewed S3 inputs without credentials or model calls."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.provider_executor import _load_view_package, _verify_named_freeze


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model', choices=['glm-4.7', 'glm-4.5-air'], default='glm-4.7')
    p.add_argument('--experiment-id', default='s3-live-20260920-v1')
    p.add_argument('--development-c-only', action='store_true',
                   help='One exploratory C call only; cannot unlock formal questions')
    args = p.parse_args()
    if args.output.exists(): raise SystemExit('refusing overwrite')
    package_root = ROOT/'tmp/s3-20260920-freeze-candidate'
    names = ['D1-r2-selected', 'Q1-primary-all', 'Q2-primary-single', 'Q3-r2-selected']
    if args.development_c_only:
        names = ['D1-r2-selected']
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    entries = []
    for name in names:
        package = package_root/'packages'/name
        _load_view_package(package)
        contracts = ('C',) if args.development_c_only else (('B', 'C') if name.startswith('D1') else ('C',))
        for contract in contracts:
            ref = package_root/'references'/f'{name}.reference.zh-CN.md'
            entries.append({'package': str(package.relative_to(ROOT)), 'contract': contract,
                            'stage': 'development' if name.startswith('D1') else 'formal',
                            'manifest_sha256': sha(package/'manifest.json'),
                            'reference': str(ref.relative_to(ROOT)), 'reference_sha256': sha(ref)})
    runtime = ['src/tradeintel_ai/provider_executor.py', 'src/tradeintel_ai/brief_business_view.py',
               'src/tradeintel_ai/evidence_linked_brief.py', 'src/tradeintel_ai/model_adapter.py',
               'scripts/run_fake_experiment.py', 'scripts/prepare_brief_v3_offline.py']
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', args.experiment_id):
        raise SystemExit('invalid experiment id')
    frozen = {'schema_version': 'bounded-provider-freeze-v1', 'experiment_id': args.experiment_id,
              'model': args.model, 'endpoint': 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
              'params': {'temperature': 0, 'max_tokens': 2000, 'thinking': {'type': 'disabled'}},
              'max_calls': 1 if args.development_c_only else 5, 'allowed_runs': entries,
              'runtime_sha256': {n: sha(ROOT/n) for n in runtime},
              'development_gate': {'path': f'tmp/{args.experiment_id}/d1-review.json'},
              'stop_rule': 'Any serious semantic error, invalid response, over-budget or unknown outcome stops this experiment; no automatic retry.',
              'reference_review': 'Astra: amount/share denominators; scope 2/18; initial 0 vs existing 50 vs unknown future; full FTZ qualification retained.',
              'protocol': 'docs/diagnostics/ASTRA_S3_FREEZE_REVIEW_20260920.zh-CN.md'}
    _verify_named_freeze(ROOT, frozen, frozen['experiment_id'],
                         package_root/'packages/D1-r2-selected', 'C' if args.development_c_only else 'B', {'events': []})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f: json.dump(frozen, f, ensure_ascii=False, indent=2)
    print(json.dumps({'freeze': str(args.output), 'sha256': sha(args.output),
                      'development_preflight': 'passed', 'api_calls': 0}))


if __name__ == '__main__': main()
