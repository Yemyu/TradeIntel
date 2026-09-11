"""One-shot policy RAG check. Hidden key input; no retry or credential storage."""
import argparse
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tradeintel_ai.policy_retrieval import PolicyRetriever, draft_answer
from tradeintel_ai.model_adapter import OpenAICompatibleConfig, OpenAICompatibleModel

OUTPUT = ROOT/'tmp/policy-smoke-13b'
CORPUS = ROOT/'docs/experiments/phase13a-policy-retrieval/corpus.json'
RESULTS = CORPUS.with_name('development_results.json')
QUESTION = '第一批关税何时生效，额外税率是多少？'


def safe_error(exc):
    """Whitelist transport diagnostics; never persist provider error bodies."""
    chain = []
    current = exc
    while current is not None and len(chain) < 5 and all(current is not e for e in chain):
        chain.append(current)
        current = current.__cause__
    for error in chain:
        if isinstance(error, HTTPError):
            return {'category':'http', 'http_status':int(error.code)}
        if isinstance(error, TimeoutError):
            return {'category':'timeout'}
        if isinstance(error, URLError):
            return {'category':'timeout' if isinstance(error.reason,TimeoutError) else 'connection'}
    if isinstance(exc,KeyboardInterrupt):
        return {'category':'interrupted'}
    return {'category':'adapter_or_response_error'}


def preflight():
    corpus = json.loads(CORPUS.read_text())
    reference = json.loads(RESULTS.read_text())
    digest = hashlib.sha256(json.dumps(corpus,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if digest != reference['corpus_sha256']:
        raise ValueError('冻结语料指纹不符，停止调用')
    for name, expected in reference['fingerprints'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise ValueError('冻结检索程序或题集已改变，停止调用')
    return PolicyRetriever(corpus).search(QUESTION, as_of='2018-07-06')


def run_once(model, evidence, output=OUTPUT, secret=''):
    if not evidence['hits']:
        raise ValueError('没有证据，不调用模型')
    output.mkdir(parents=True, exist_ok=True)
    # Exclusive durable claim survives crashes: never blindly resend a request.
    with (output/'attempt.json').open('x') as handle:
        json.dump({'status':'reserved', 'maximum_calls':1, 'question':QUESTION,
                   'independent_evaluation':False},handle,ensure_ascii=False)
    (output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))

    class Recorder:
        raw = None
        calls = 0
        def complete(self, **kwargs):
            if self.calls:
                raise RuntimeError('Single-call limit')
            self.calls += 1
            response = model.complete(**kwargs)
            # Only whitelisted values; never persist config, headers, or errors.
            self.raw = {'text':response.text, 'tool_call_count':len(response.tool_calls)}
            return response

    recorder = Recorder()
    try:
        generation = draft_answer(recorder, evidence)
        outcome = {'generation':generation, 'raw_response':recorder.raw,
                   'attempted_calls':recorder.calls, 'semantic_verified':False}
    except (Exception, KeyboardInterrupt) as exc:
        outcome = {'status':'stopped_without_retry', 'error_type':type(exc).__name__,
                   'diagnostic':safe_error(exc),
                   'attempted_calls':recorder.calls, 'semantic_verified':False}
    serialized = json.dumps(outcome,ensure_ascii=False,indent=2)
    if secret:
        serialized = serialized.replace(secret,'[REDACTED]')
    with (output/'result.json').open('x') as handle:
        handle.write(serialized+'\n')
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    evidence = preflight()
    if not args.execute:
        print(f'预检通过：{len(evidence["hits"])}个冻结证据片段；未调用模型。')
        return
    if (OUTPUT/'attempt.json').exists():
        raise ValueError('本次验证已尝试过，请先审查现有记录；不会自动重发')
    key = os.environ.get('TRADEINTEL_MODEL_API_KEY','').strip()
    if not key:
        if not sys.stdin.isatty():
            raise ValueError('请在自己的交互终端运行；此处不能隐藏输入密钥')
        key = getpass.getpass('粘贴GLM API Key后回车（输入不显示、不保存）：').strip()
    if not key:
        raise ValueError('密钥为空；没有调用')
    # Same provider/model as the project's previous planner run; no model sweep.
    config = OpenAICompatibleConfig('https://open.bigmodel.cn/api/paas/v4','glm-4.7',key,60,0)
    print('开始唯一一次GLM调用，最多等待约60秒；无自动重试。',flush=True)
    result = run_once(OpenAICompatibleModel(config),evidence,secret=key)
    print('记录已保存：',OUTPUT/'result.json')
    print('状态：',result.get('status',result.get('generation',{}).get('status')))
    print('这只是待核对草稿，不是准确率成绩。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError,FileExistsError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(2)
