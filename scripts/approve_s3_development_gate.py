#!/usr/bin/env python3
"""Create a human-reviewed D1 gate; never calls a provider.

This is deliberately explicit. It only approves formal runs after both D1
contracts have completed and a reviewer records the three hard checks and the
2/3 explanation threshold. It does not judge prose automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.provider_executor import verify_development_review, _canonical


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--d1-b-run', type=Path, required=True)
    p.add_argument('--d1-c-run', type=Path, required=True)
    p.add_argument('--reviewer', required=True)
    p.add_argument('--freeze', type=Path, required=True)
    p.add_argument('--hard-checks', nargs=3, type=int, choices=(0, 1), required=True,
                   metavar=('NO_SCOPE_ERROR', 'NO_POLICY_ERROR', 'NO_UNSUPPORTED_CLAIM'))
    p.add_argument('--gain-checks', nargs=3, type=int, choices=(0, 1), required=True,
                   metavar=('EXPLAINS_DIFFERENCE', 'RESEARCH_FOCUS', 'DATA_NEED'))
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    frozen = json.loads(args.freeze.read_text(encoding='utf-8'))
    experiment = frozen['experiment_id']
    from src.tradeintel_ai.provider_executor import _safe_key
    _safe_key(experiment, 'experiment_id')
    ledger = json.loads((ROOT/'.local/experiments'/f'provider-ledger-{experiment}-real.json').read_text())
    if args.output.resolve() != (ROOT/frozen['development_gate']['path']).resolve():
        raise SystemExit('output must match the fixed review path')
    if not args.reviewer.strip():
        raise SystemExit('reviewer must be non-empty')
    runs = []
    for path, contract in ((args.d1_b_run, 'B'), (args.d1_c_run, 'C')):
        manifest = json.loads((path / 'run-manifest.json').read_text(encoding='utf-8'))
        if manifest.get('status') != 'completed' or manifest.get('contract') != contract:
            raise SystemExit(f'D1 {contract} must be completed before approval')
        if manifest.get('validation_status') == 'invalid_response':
            raise SystemExit(f'D1 {contract} response is invalid')
        runs.append({'contract': contract, 'run_manifest': str((path/'run-manifest.json').resolve()),
                     'run_manifest_sha256': sha(path/'run-manifest.json')})
    if any(args.hard_checks) != 0:
        raise SystemExit('all three D1 hard checks must be 0 errors')
    if sum(args.gain_checks) < 2:
        raise SystemExit('D1 explanation gain must reach at least 2/3')
    record = {'schema': 's3-development-gate-v1', 'status': 'approved',
              'experiment_id': experiment,
              'freeze_sha256': hashlib.sha256(_canonical(frozen).encode()).hexdigest(),
              'reviewer': args.reviewer, 'reviewed_at': datetime.now(timezone.utc).isoformat(),
              'd1_runs': runs, 'hard_checks': args.hard_checks, 'gain_checks': args.gain_checks,
              'boundary': '人工审阅记录，不是自动准确率或泛化证明。'}
    verify_development_review(ROOT, frozen, ledger, record)
    if args.output.exists():
        raise SystemExit('refusing to overwrite existing gate')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
