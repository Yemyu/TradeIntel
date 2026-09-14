"""Smoke-test an export of current non-ignored files, without keys or raw data.

Uses the existing interpreter: this checks file portability, NOT a clean
dependency installation or the committed Git revision. No live model calls.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import os


ROOT = Path(__file__).resolve().parents[1]


def main():
    scratch = ROOT / 'tmp'
    scratch.mkdir(exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix='portable-check-', dir=scratch))
    names = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT
    ).decode().split('\0')
    copied = 0
    for name in sorted(set(names) - {''}):
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe export path')
        if relative.parts[0] in {'.local', '.venv', '.git', 'tmp'} or relative.name.startswith('.env'):
            continue
        source = ROOT / relative
        if source.is_symlink() or not source.is_file():
            continue
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied += 1
    # Keep machine execution settings, but never inherit provider credentials
    # or Python path overrides into the isolated checkout.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('TRADEINTEL_MODEL_') and k not in {'PYTHONPATH', 'PYTHONHOME'}}
    result = subprocess.run(
        [sys.executable, str(snapshot / 'scripts/run_strict_offline_demo.py'),
         '--output', str(snapshot / 'tmp/demo')], cwd=snapshot, env=env,
        capture_output=True, text=True, timeout=120)
    # The offline fixture emits no credentials; keep the diagnostic local.
    (snapshot / 'portable-check.log').write_text(result.stdout + result.stderr)
    print(json.dumps({'snapshot': str(snapshot), 'copied_files': copied,
                      'returncode': result.returncode,
                      'uses_existing_interpreter': True,
                      'fresh_dependency_install_verified': False,
                      'live_model_calls': 0}, ensure_ascii=False, indent=2))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
