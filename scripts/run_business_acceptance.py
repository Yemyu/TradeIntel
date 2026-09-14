"""One bounded, non-resumable live development batch. Never reads gold answers."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.local_provider_config import load_config
from tradeintel_ai.research_models import ResearchPlannerModel
from tradeintel_ai.business_workflow import run_business_question
from tradeintel_ai.exposure_version_store import pin_repository
from tradeintel_ai.repository import EvidenceRepository

INPUT_HASH = '6d0419c517b1cb64ae7fb88bf84dac3eef05140ca9fb9315f4f2b292ac530a71'


def run(output, *, input_path=None, input_hash=INPUT_HASH, max_calls=12, token_stop=30000, baselines=True):
    raw = (input_path or ROOT / 'evals/business_tasks_v1.inputs.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != input_hash:
        raise ValueError('input freeze changed')
    cases = json.loads(raw)['cases']
    config = replace(load_config(), timeout_seconds=180.0, temperature=0.0)
    if not config.api_key:
        raise ValueError('local API key unavailable')
    repo = pin_repository(EvidenceRepository())
    output.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2).replace(config.api_key, '[REDACTED]') + '\n')
    ledger = dict(attempts=0, total_tokens=0, stop=None, requests=[])
    class BoundedModel(ResearchPlannerModel):
        max_output_tokens = 2048
        def complete(self, *, messages, tools):
            if ledger['stop'] or ledger['attempts'] >= max_calls or ledger['total_tokens'] >= token_stop:
                ledger['stop'] = ledger['stop'] or 'budget_exhausted'
                raise RuntimeError('batch stopped')
            ledger['attempts'] += 1
            n = ledger['attempts']
            item = dict(attempt=n, status='started')
            ledger['requests'].append(item)
            save('ledger.json', ledger)
            save(f'request-{n:02d}.json', dict(messages=messages, tools=tools))
            start = time.monotonic()
            try:
                response = super().complete(messages=messages, tools=tools)
                save(f'response-{n:02d}.json', asdict(response))
                usage = response.metadata.get('usage', {})
                tokens = usage.get('total_tokens')
                if type(tokens) is not int or tokens < 0:
                    ledger['stop'] = 'usage_missing'
                    raise RuntimeError('usage missing')
                ledger['total_tokens'] += tokens
                item.update(status='received', usage=usage)
                return response
            except Exception as exc:
                item.update(status='failed', error_type=type(exc).__name__)
                ledger['stop'] = ledger['stop'] or 'provider_error_no_retry'
                raise
            finally:
                item['seconds'] = round(time.monotonic()-start, 3)
                save('ledger.json', ledger)
    model = BoundedModel(config)
    files = sorted((ROOT / 'src/tradeintel_ai').glob('*.py')) + [Path(__file__)]
    save('freeze.json', dict(input_sha256=input_hash, data_version=getattr(repo,'exposure_version',None),
         code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
         settings=model.effective_request_settings(), max_calls=max_calls, reported_token_stop=token_stop, baselines=baselines,
         retries=0, evaluation_scope='assistant-designed development acceptance; not held-out'))
    results=[]
    for case in cases:
        if ledger['stop'] or ledger['total_tokens'] >= token_stop or ledger['attempts'] >= max_calls:
            results.append(dict(id=case['id'], status='not_run', baseline='not_run'))
            continue
        state = run_business_question(model, case['question'], output / case['id'], repository=repo, secret=config.api_key)
        entry=dict(id=case['id'], **state, baseline='not_run')
        if baselines and not ledger['stop']:
            try:
                baseline=model.complete(messages=[
                    {'role':'system','content':'回答用户的问题，按其要求给中文结果、金额单位和依据。你没有访问项目数据库或原文的工具，不能假称已读项目文件；未知请说明。不要编造金额、来源或现行适用性。'},
                    {'role':'user','content':case['question']}],tools=[])
                save(case['id']+'-baseline.json',asdict(baseline))
                entry['baseline']='received_needs_review'
            except Exception:
                entry['baseline']='failed'
        results.append(entry)
        save('results.json',results)
        print(json.dumps(dict(id=case['id'],status=state['status'],baseline=entry['baseline'],attempts=ledger['attempts']),ensure_ascii=False),flush=True)
    save('results.json',results)
    return dict(results=results, attempts=ledger['attempts'], total_tokens=ledger['total_tokens'], stop=ledger['stop'])


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(run(args.output),ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'status':'stopped','error_type':type(exc).__name__}))
        sys.exit(1)
