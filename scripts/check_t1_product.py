"""Frozen T1 responsibility inventory and credential-free clean-copy check.

Run .venv/bin/python scripts/check_t1_product.py --clean.
No packages are installed; the clean copy shares the selected Python runtime.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'request_and_parse': ['test_natural_v2', 'test_structured_task', 'test_policy_response_format'],
    'policy_facts': ['test_policy_facts_contract', 'test_fact_interpretation', 'test_solar_policy'],
    'calculations_and_output': ['test_research_brief_v2'],
    'business_integration': ['test_business_workflow', 'test_g1_repairs', 'test_primary_interpretation_flow'],
    'review_and_export': ['test_interpretation_review_store', 'test_review_revisions',
                          'test_reviewed_draft', 'test_run_review_routes'],
    'version_and_links': ['test_exposure_version_store', 'test_research_data_link', 'test_version_report'],
    'candidate_isolation': ['test_solar_release'],
    'web_routes': ['test_web_app'],
}
# This is a product scope boundary, not an assertion that excluded tests pass.
HISTORICAL = {'test_structured_workflow': '2018 list1 / v21 historical workflow, not T1 monthly v2'}
TREES = ['src', 'scripts', 'tests', 'web', 'data/processed/policy',
         'data/processed/policy_exposure', 'data/candidates/solar2024']
FILES = ['requirements.txt', 'data/raw/policy/review2025/cbp-63577329.html',
         'docs/experiments/solar-brief-pilot-v1.zh-CN.md']


def guard(event, args):
    if event == 'socket.getaddrinfo':
        host = args[0]
    elif event == 'socket.connect':
        address = args[1]
        if not isinstance(address, tuple):
            raise RuntimeError('non-IP socket blocked in T1 check')
        host = address[0]
    else:
        return
    if host == 'localhost':
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RuntimeError('external network blocked in T1 check')


def worker():
    sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
    sys.addaudithook(guard)
    results = {}
    for name, modules in GROUPS.items():
        suite = unittest.defaultTestLoader.loadTestsFromNames(['tests.' + m for m in modules])
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        results[name] = dict(tests=result.testsRun, failures=len(result.failures),
                            errors=len(result.errors), skipped=len(result.skipped),
                            passed=result.wasSuccessful())
    Path('t1-results.json').write_text(json.dumps(results, indent=2) + '\n')
    return 0 if all(r['passed'] for r in results.values()) else 1


def inventory():
    paths = []
    for relative in TREES:
        directory = ROOT / relative
        if not directory.is_dir():
            raise FileNotFoundError(relative)
        for path in sorted(directory.rglob('*')):
            if path.is_symlink():
                raise ValueError('symlink not allowed in portable inventory: ' + str(path))
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if path.name.startswith('.env') or path.suffix in {'.key', '.pem'}:
                raise ValueError('credential-like file in portable inventory')
            paths.append(path)
    paths.extend(ROOT / relative for relative in FILES)
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', action='store_true', help='Run in a temporary code/data copy')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker()
    if not args.clean:
        parser.error('use --clean; original workspace execution is deliberately disabled')
    manifest = inventory()
    selected = {m for group in GROUPS.values() for m in group}
    unclassified = sorted(p.stem for p in (ROOT / 'tests').glob('test_*.py')
                          if p.stem not in selected and p.stem not in HISTORICAL)
    node = shutil.which('node')
    # Never inherit provider credentials, PYTHONPATH, user HOME or dotenv files.
    with tempfile.TemporaryDirectory(prefix='tradeintel-t1-') as temporary:
        root = Path(temporary)
        for relative, digest in manifest.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError('copy digest mismatch: ' + relative)
        home = root / 'isolated-home'; home.mkdir()
        env = {'PATH':str(Path(sys.executable).parent) + os.pathsep + '/usr/bin:/bin',
               'HOME':str(home), 'PYTHONPATH':str(root) + os.pathsep + str(root / 'src'),
               'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONNOUSERSITE':'1', 'LANG':'en_US.UTF-8'}
        python = subprocess.run([sys.executable, 'scripts/check_t1_product.py', '--worker'],
                                cwd=root, env=env, capture_output=True, text=True, timeout=180)
        ui = subprocess.run([node, '--test', 'tests/interpretation_review_ui.test.cjs'],
                            cwd=root, env=env, capture_output=True, text=True, timeout=30) if node else None
        results = json.loads((root / 't1-results.json').read_text()) if (root / 't1-results.json').exists() else {}
        passed = python.returncode == 0 and ui is not None and ui.returncode == 0
        report = dict(schema='t1-clean-check-v1', passed=passed, groups=results,
                      ui_passed=ui.returncode == 0 if ui else False,
                      python=sys.version, interpreter=sys.executable, node=node,
                      python_exit=python.returncode, source_sha256=manifest,
                      temporary_root=str(root), credential_environment_inherited=False,
                      isolation='clean code/data copy; existing Python runtime, not fresh machine/container',
                      historical_exclusions=HISTORICAL, unclassified_test_modules=unclassified,
                      total_python_tests=sum(r['tests'] for r in results.values()),
                      ai_quality_evaluated=False, g1_adoption='pending_final_review')
        # Local generated artifacts only; never overwrite an earlier check.
        output = Path(tempfile.mkdtemp(prefix='t1-check-', dir=ROOT / 'tmp'))
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        (output / 'python.log').write_text(python.stdout + python.stderr)
        (output / 'ui.log').write_text(ui.stdout + ui.stderr if ui else 'Node.js unavailable; UI not checked\n')
        print(json.dumps({k:v for k,v in report.items() if k not in {'source_sha256','unclassified_test_modules'}}, ensure_ascii=False, indent=2))
        print(f'Unclassified test modules (not claimed passing): {len(unclassified)}')
        print(f'Full inventory and logs: {output}')
        return 0 if passed else 1


if __name__ == '__main__':
    (ROOT / 'tmp').mkdir(exist_ok=True)
    raise SystemExit(main())
