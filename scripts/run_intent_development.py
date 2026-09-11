"""Run the frozen 12-question intent development set once.

Offline preflight is the default. ``--execute`` is the only mode that calls a
provider, and it requires an explicit API key in the environment or a hidden
interactive prompt. No data tools are exposed to the model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.intent_proposal import propose_intent
from src.tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleConfig, OpenAICompatibleModel
from scripts.check_intent_development import CASES, load_cases

MANIFEST = ROOT / 'evals/intent_development_manifest.json'
DEFAULT_OUTPUT = ROOT / 'tmp/intent-development'
BASE_URL = 'https://open.bigmodel.cn/api/paas/v4'
MODEL = 'glm-4.5-air'
TIMEOUT = 60.0
TEMPERATURE = 0.0


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def preflight():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest.get('status') != 'frozen_for_development_run':
        raise ValueError('语义开发运行器尚未冻结')
    for relative, expected in manifest['files'].items():
        if digest(ROOT / relative) != expected:
            raise ValueError('冻结文件已变化：' + relative)
    cases = load_cases()
    if len(cases) != 12:
        raise ValueError('本次运行必须是12道独立开发题')
    return manifest, cases


def run(*, execute=False, output=None, api_key=None):
    manifest, cases = preflight()
    summary = {'status': 'preflight_passed', 'mode': 'intent_development',
               'questions': len(cases), 'maximum_api_requests': len(cases),
               'model': MODEL, 'temperature': TEMPERATURE, 'timeout_seconds': TIMEOUT,
               'model_adopted': False, 'semantic_accuracy': None, 'api_requests': 0}
    if not execute:
        return summary
    key = api_key if api_key is not None else os.environ.get('TRADEINTEL_MODEL_API_KEY', '')
    if not key:
        raise ValueError('缺少API Key；请用环境变量或交互终端隐藏输入')
    if not key.isascii() or any(c.isspace() for c in key):
        raise ValueError('API Key不得包含空白或非ASCII字符')
    output = Path(output or DEFAULT_OUTPUT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'))
    journal = output.with_suffix('.jsonl')
    if output.exists() or journal.exists() or output == journal:
        raise ValueError('不能覆盖已有运行记录，请使用新文件名')
    config = OpenAICompatibleConfig(BASE_URL, MODEL, key, TIMEOUT, TEMPERATURE)
    model = OpenAICompatibleModel(config, system_prompt='')
    report = {**summary, 'status': 'running', 'started_at_utc': utcnow(),
              'manifest': manifest, 'manifest_sha256': digest(MANIFEST),
              'cases_sha256': digest(CASES), 'questions': [],
              'output': str(output), 'journal': str(journal), 'stop_reason': None}
    output.parent.mkdir(parents=True, exist_ok=True)

    def serialise(value):
        # Key redaction is a final guard; the adapter never logs request headers.
        return json.dumps(value, ensure_ascii=False, allow_nan=False).replace(key, '[REDACTED]')

    with output.open('x', encoding='utf-8') as out, journal.open('x', encoding='utf-8') as log:
        def append(event):
            log.write(serialise(event) + '\n')
            log.flush()
            os.fsync(log.fileno())

        append({'event': 'run_started', 'started_at_utc': report['started_at_utc'],
                'manifest_sha256': report['manifest_sha256'], 'configuration':
                {'model': MODEL, 'provider': 'bigmodel.cn', 'temperature': TEMPERATURE,
                 'timeout_seconds': TIMEOUT, 'api_key_recorded': False}})
        order = list(cases)
        random.Random(20260908).shuffle(order)
        try:
            for index, case in enumerate(order, 1):
                print(f'开始 {index}/{len(cases)}：{case["id"]}（单次请求等待上限约60秒）', flush=True)
                started = time.perf_counter()
                append({'event': 'question_started', 'index': index, 'id': case['id'], 'started_at_utc': utcnow()})
                try:
                    result = propose_intent(case['question'], model, propagate_model_errors=True)
                except KeyboardInterrupt:
                    report['stop_reason'] = 'interrupted'
                    raise
                except ModelAdapterError as exc:
                    # Do not continue: a transport/auth/quota issue is not a semantic result.
                    report['stop_reason'] = 'model_request_error'
                    append({'event': 'question_failed', 'index': index, 'id': case['id'],
                            'error': str(exc), 'elapsed_ms': round((time.perf_counter()-started)*1000, 2)})
                    raise
                item = {'id': case['id'], 'question': case['question'],
                        'result': result, 'elapsed_ms': round((time.perf_counter()-started)*1000, 2)}
                report['questions'].append(item)
                report['api_requests'] += result.get('model_calls', 0)
                append({'event': 'answer_recorded', 'item': item})
                print(f'已记录 {index}/{len(cases)}；{result["status"]}；累计请求 {report["api_requests"]}/{len(cases)}', flush=True)
            report['status'] = 'collected_not_scored'
        except KeyboardInterrupt:
            report['status'] = 'interrupted'
        except ModelAdapterError:
            report['status'] = 'stopped'
        finally:
            report['finished_at_utc'] = utcnow()
            append({'event': 'run_finished', 'status': report['status'],
                    'recorded_answers': len(report['questions']), 'api_requests': report['api_requests'],
                    'stop_reason': report['stop_reason']})
            out.write(serialise(report) + '\n')
            out.flush()
            os.fsync(out.fileno())
    return {'status': report['status'], 'recorded_answers': len(report['questions']),
            'api_requests': report['api_requests'], 'output': str(output),
            'model_adopted': False, 'semantic_accuracy': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(run(), ensure_ascii=False), flush=True)
        if not args.execute:
            return 0
        key = os.environ.get('TRADEINTEL_MODEL_API_KEY', '')
        if not key:
            if not sys.stdin.isatty():
                raise ValueError('请在交互终端设置TRADEINTEL_MODEL_API_KEY')
            key = getpass.getpass('请粘贴GLM API Key并回车（输入不显示）：').strip()
        result = run(execute=True, output=args.output, api_key=key)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result['status'] == 'collected_not_scored' else 1
    except (ValueError, OSError, KeyError, ModelAdapterError):
        print('配置或冻结文件检查失败；没有显示密钥。请检查运行日志。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
