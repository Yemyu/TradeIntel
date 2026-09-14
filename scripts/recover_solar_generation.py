"""One explicit transport recovery, reusing the original plan and request."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.business_workflow import run_business_question
from tradeintel_ai.exposure_version_store import ExposureVersionStore
from tradeintel_ai.local_provider_config import load_config
from tradeintel_ai.policy_cases import CASES
from tradeintel_ai.provider_diagnostics import safe_provider_diagnostic
from tradeintel_ai.repository import DataPaths, EvidenceRepository
from tradeintel_ai.research_models import ResearchPlannerModel


class OneGenerationRecovery:
    def __init__(self, plan_text, request, provider, record):
        self.plan_text, self.request = plan_text, request
        self.provider, self.record = provider, record
        self.stage = 0

    def complete(self, *, messages, tools):
        self.stage += 1
        if self.stage == 1:
            return ModelResponse(text=self.plan_text)
        if self.stage != 2 or {'messages':messages, 'tools':tools} != self.request:
            raise ValueError('recovery request changed or call budget exceeded')
        self.record('started', None)
        try:
            response = self.provider.complete(messages=self.request['messages'], tools=self.request['tools'])
            self.record('received', response)
            return response
        except Exception as exc:
            self.record('failed', exc)
            raise


def recover(parent):
    parent = Path(parent).resolve()
    run = parent/'run'
    def read(path): return json.loads(path.read_text())
    status, freeze, old_ledger = read(run/'status.json'), read(parent/'freeze.json'), read(parent/'ledger.json')
    if status.get('error_type') != 'RemoteDisconnected' or (run/'policy-response.json').exists():
        raise ValueError('not the approved incomplete transport failure')
    for relative, expected in freeze['code_sha256'].items():
        path = (ROOT/relative).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('frozen code changed')
    if hashlib.sha256((ROOT/freeze['protocol']).read_bytes()).hexdigest() != freeze['protocol_sha256']:
        raise ValueError('original protocol changed')
    case = CASES['us_301_solar2024']
    workspace = parent/'workspace'
    store = ExposureVersionStore(workspace, workspace/case.versions)
    if store.active_version() != freeze['version']:
        raise ValueError('active recovery version changed')
    store.release_root(freeze['version'])
    output = parent/'generation-recovery-once'
    output.mkdir(exist_ok=False)  # Durable one-shot gate, even if interrupted.
    config = replace(load_config(), timeout_seconds=180.0, temperature=0.0)
    if not config.api_key: raise ValueError('local key unavailable')
    if config.model != read(run/'plan-response.json')['metadata']['requested_model']:
        raise ValueError('recovery model differs from original')
    def save(name, value):
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2).replace(config.api_key, '[REDACTED]'))
    originals = [run/name for name in ['policy-request.json','plan-response.json','trade-evidence.json','policy-evidence.json','scope-links.json']]
    save('freeze.json', {'version':freeze['version'], 'original_attempts':old_ledger['attempts'],
        'original_reported_tokens':old_ledger['total_tokens'], 'original_unreported_usage':True,
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in originals},
        'max_new_requests':1, 'retries':0,
        'settings':{'model':config.model,'max_tokens':3072,'timeout_seconds':180}})
    ledger = {'new_requests':0,'status':'prepared','new_reported_tokens':None,
              'original_attempts':old_ledger['attempts'],'total_attempts':old_ledger['attempts']}
    def record(event, value):
        ledger['status'] = event
        if event == 'started':
            ledger['new_requests'] = 1
            ledger['total_attempts'] += 1
        elif event == 'received':
            save('response.json', asdict(value))
            ledger['new_reported_tokens'] = value.metadata.get('usage', {}).get('total_tokens')
        elif event == 'failed':
            ledger['diagnostic'] = safe_provider_diagnostic(value)
        save('ledger.json', ledger)
    class Provider(ResearchPlannerModel): max_output_tokens = 3072
    record('prepared', None)
    model = OneGenerationRecovery(read(run/'plan-response.json')['text'], read(run/'policy-request.json'), Provider(config), record)
    original_version = ExposureVersionStore(ROOT).active_version()
    with patch.dict(CASES, {case.policy_id:replace(case,status='enabled')}):
        result = run_business_question(model, freeze['question'], output/'report',
            repository=EvidenceRepository(DataPaths(workspace)), secret=config.api_key, policy_id=case.policy_id)
    if ExposureVersionStore(ROOT).active_version() != original_version:
        raise ValueError('production version changed')
    save('result.json', result)
    return {'result':result, 'ledger':ledger}


if __name__ == '__main__':
    try:
        print(json.dumps(recover(ROOT/'tmp/solar-two-products-v1-first-20260914'), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status':'stopped','error_type':type(exc).__name__}))
        sys.exit(1)
