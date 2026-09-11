"""Three-call GLM-4.6V diagnostic, offline by default, durable raw responses."""
import argparse
from datetime import datetime, timezone
from dataclasses import asdict
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig, OpenAICompatibleModel
from src.tradeintel_ai.intent_proposal import propose_intent
from src.tradeintel_ai.intent_diagnostics import diagnose_response

MANIFEST = ROOT / 'evals/glm46v_diagnostic_manifest.json'
IDS = ('D01', 'D07', 'D12')
MODEL = 'glm-4.6v'
BASE = 'https://open.bigmodel.cn/api/paas/v4'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight():
    manifest = json.loads(MANIFEST.read_text())
    if manifest['model'] != MODEL or manifest['question_ids'] != list(IDS):
        raise ValueError('configuration mismatch')
    for relative, expected in manifest['files'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or sha(path) != expected:
            raise ValueError('frozen files changed')
    cases = json.loads((ROOT / 'evals/intent_development_cases.json').read_text())
    return manifest, [{'id': ident, 'question': next(c['question'] for c in cases if c['id'] == ident)} for ident in IDS]


def run(*, execute=False, api_key='', output=None, opener=urlopen):
    manifest, cases = preflight()
    if not execute:
        return {'status': 'preflight_passed', 'model': MODEL, 'maximum_requests': 3, 'api_requests': 0}
    if not api_key or not api_key.isascii() or any(c.isspace() for c in api_key):
        raise ValueError('invalid key')
    output = Path(output or ROOT / 'tmp/glm46v-diagnostic' /
                  (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'))
    journal = output.with_suffix('.jsonl')
    if output.suffix != '.json' or output.exists() or journal.exists():
        raise ValueError('output already exists or invalid suffix')
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'model': MODEL, 'manifest': manifest,
              'manifest_sha256': sha(MANIFEST), 'api_requests': 0, 'planned_questions': 3,
              'questions': [], 'model_adopted': False, 'started_at': datetime.now(timezone.utc).isoformat()}
    def clean(value):
        # Redact structurally so even escaped strings containing the exact key are covered.
        if isinstance(value, str): return value.replace(api_key, '[REDACTED]')
        if isinstance(value, list): return [clean(v) for v in value]
        if isinstance(value, dict): return {clean(k): clean(v) for k,v in value.items()}
        return value
    with output.open('x', encoding='utf-8') as out, journal.open('x', encoding='utf-8') as log:
        def append(event):
            log.write(json.dumps(clean(event), ensure_ascii=False, allow_nan=False) + '\n')
            log.flush(); os.fsync(log.fileno())
        append({'event': 'run_started', 'manifest_sha256': report['manifest_sha256']})
        try:
            for index, case in enumerate(cases, 1):
                print(f'开始 {index}/3：{case["id"]}；等待GLM-4.6V（单次超时设置60秒）', flush=True)
                state = {'attempted': False, 'request_error': False, 'response': None}
                def capture_http(request, **kwargs):
                    if state['attempted'] or report['api_requests'] >= 3:
                        raise ValueError('request budget exceeded')
                    state['attempted'] = True
                    report['api_requests'] += 1
                    append({'event': 'request_started', 'id': case['id'], 'request_number': report['api_requests'],
                            'payload': json.loads(request.data.decode())})
                    try:
                        with opener(request, **kwargs) as remote:
                            body = remote.read()
                    except BaseException:
                        state['request_error'] = True
                        append({'event': 'request_failed', 'id': case['id']})
                        raise
                    append({'event': 'http_response', 'id': case['id'], 'body': body.decode('utf-8', errors='replace')})
                    return io.BytesIO(body)
                provider = OpenAICompatibleModel(OpenAICompatibleConfig(BASE, MODEL, api_key, 60, 0),
                                                  system_prompt='', opener=capture_http)
                class CaptureModel:
                    def complete(self, *, messages, tools):
                        if tools: raise ValueError('no tools allowed')
                        try:
                            response = provider.complete(messages=messages, tools=[])
                        except BaseException:
                            state['request_error'] = True
                            raise
                        state['response'] = asdict(response)
                        append({'event': 'response_recorded', 'id': case['id'], 'response': state['response']})
                        return response
                try:
                    result = propose_intent(case['question'], CaptureModel())
                except KeyboardInterrupt:
                    append({'event': 'question_interrupted', 'id': case['id']})
                    raise
                diagnostic = (diagnose_response(case['question'], state['response']) if state['response'] is not None
                              else {'stage': 'provider_or_response_error', 'executed': False})
                item = {**case, 'result': result, 'diagnostic': diagnostic, 'response': state['response']}
                report['questions'].append(item)
                append({'event': 'answer_recorded', 'item': item})
                print(f'已记录 {index}/3：{diagnostic["stage"]}；累计请求 {report["api_requests"]}/3', flush=True)
                if state['request_error'] or diagnostic['stage'] == 'unexpected_tool_call':
                    report.update(status='stopped', stop_reason=diagnostic['stage'])
                    break
            else:
                report['status'] = 'collected_not_scored'
        except KeyboardInterrupt:
            report['status'] = 'interrupted'
        except Exception:
            report.update(status='stopped', stop_reason='host_error')
        finally:
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            append({'event': 'run_finished', 'status': report['status'], 'api_requests': report['api_requests']})
            out.write(json.dumps(clean(report), ensure_ascii=False, indent=2) + '\n')
            out.flush(); os.fsync(out.fileno())
    return {'status': report['status'], 'api_requests': report['api_requests'],
            'output': str(output), 'journal': str(journal), 'model_adopted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(run(), ensure_ascii=False), flush=True)
        if args.execute:
            key = os.environ.get('TRADEINTEL_MODEL_API_KEY', '')
            if not key:
                if not sys.stdin.isatty(): raise ValueError('interactive terminal required')
                key = getpass.getpass('粘贴原来的GLM API Key并回车（输入不显示）：').strip()
            result = run(execute=True, api_key=key)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            sys.exit(0 if result['status'] == 'collected_not_scored' else 1)
    except (ValueError, OSError, KeyError):
        print('预检或配置失败；未显示密钥，请告知助手。', flush=True)
        sys.exit(2)
