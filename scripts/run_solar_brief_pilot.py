"""Isolated second-case development pilot; never activates production routing."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from scripts.replay_exposure_update import snapshot
from tradeintel_ai.policy_cases import CASES
from tradeintel_ai.business_workflow import run_business_question
from tradeintel_ai.exposure_version_store import ExposureVersionStore
from tradeintel_ai.repository import EvidenceRepository, DataPaths
from tradeintel_ai.local_provider_config import load_config
from tradeintel_ai.research_models import JsonResearchModel

QUESTION = '请解释85414300的存档政策商品限定、额外税率和生效条件，并结合2026-05美国该税号全部来源及中国原产消费进口金额和中国份额写一份简报。'


def run(output, model=None, *, question=QUESTION,
        protocol='docs/experiments/solar-brief-pilot-v1.zh-CN.md', interpretation_mode=False, structured_task=None):
    if structured_task is not None:
        from tradeintel_ai.structured_task import compile_task
        question, _ = compile_task(structured_task)
        interpretation_mode = True
    max_calls = 1 if structured_task is not None else 2
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    case = CASES['us_301_solar2024']
    original = ExposureVersionStore(ROOT).active_version()
    secret = ''
    ledger = {'attempts': 0, 'total_tokens': 0, 'stop': None}
    def save(name, value):
        text = json.dumps(value, ensure_ascii=False, indent=2)
        (output / name).write_text(text.replace(secret, '[REDACTED]') if secret else text)
    if model is None:
        config = replace(load_config(), timeout_seconds=180.0, temperature=0.0)
        if not config.api_key:
            raise ValueError('local key unavailable')
        secret = config.api_key
        class BoundedModel(JsonResearchModel):
            max_output_tokens = 3072
            def complete(self, *, messages, tools):
                if ledger['attempts'] >= max_calls or ledger['stop']:
                    raise ValueError('pilot stopped')
                ledger['attempts'] += 1
                save('ledger.json', ledger)
                try:
                    response = super().complete(messages=messages, tools=tools)
                    usage = response.metadata.get('usage', {}).get('total_tokens')
                    if type(usage) is not int or usage < 0:
                        ledger['stop'] = 'usage_missing'
                    else:
                        ledger['total_tokens'] += usage
                        if ledger['total_tokens'] >= 16000:
                            ledger['stop'] = 'reported_token_stop'
                    return response
                except Exception as exc:
                    from tradeintel_ai.provider_diagnostics import safe_provider_diagnostic
                    ledger['diagnostic'] = safe_provider_diagnostic(exc)
                    ledger['stop'] = 'provider_error_no_retry'
                    raise
                finally:
                    save('ledger.json', ledger)
        model = BoundedModel(config)
        mode = 'live_development_not_held_out'
    else:
        mode = 'fixture_integration_not_model_score'
    isolated = output / 'workspace'
    base = Path(case.manifest).parent
    shutil.copytree(ROOT / base, isolated / base, ignore=shutil.ignore_patterns('versions'))
    # Scope is this Python process and its isolated copy only, never the server.
    try:
        with patch.dict(CASES, {case.policy_id: replace(case, status='enabled')}):
            state = snapshot(isolated, case.end, policy_id=case.policy_id)
            store = ExposureVersionStore(isolated, isolated / case.versions)
            store.bootstrap(state)
            store.prepare_release(state['version'])
            save('freeze.json', {'mode': mode, 'question': question,
                'version': state['version'], 'max_calls': max_calls, 'retries': 0, 'interpretation_mode':interpretation_mode,
                'structured_task':structured_task, 'input_mode':'structured' if structured_task is not None else 'natural_language',
                'protocol': protocol,
                'protocol_sha256': hashlib.sha256((ROOT/protocol).read_bytes()).hexdigest(),
                'request_settings': model.effective_request_settings() if hasattr(model, 'effective_request_settings') else {'mode':'fixture'},
                'code_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [Path(__file__), *sorted((ROOT/'src/tradeintel_ai').glob('*.py'))]}})
            result = run_business_question(model, question, output/'run',
                repository=EvidenceRepository(DataPaths(isolated)), secret=secret,
                policy_id=case.policy_id, interpretation_mode=interpretation_mode, structured_task=structured_task)
            save('result.json', result)
            return result
    finally:
        if CASES[case.policy_id].status != case.status or ExposureVersionStore(ROOT).active_version() != original:
            raise RuntimeError('production state changed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--structured-month', help='显式月份YYYY-MM；启用结构化实验，最多一次解释调用')
    parser.add_argument('--structured-product', choices=['all','85414200','85414300'])
    parser.add_argument('--protocol', default='docs/experiments/solar-brief-pilot-v1.zh-CN.md')
    args = parser.parse_args()
    if bool(args.structured_month) != bool(args.structured_product):
        parser.error('structured-month和structured-product必须同时提供')
    task = {'policy_id':'us_301_solar2024','month':args.structured_month,
            'product':args.structured_product,'task':'source_and_investigation'} if args.structured_month else None
    try:
        print(json.dumps(run(args.output, structured_task=task, protocol=args.protocol), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status': 'stopped', 'error_type': type(exc).__name__}))
        sys.exit(1)
