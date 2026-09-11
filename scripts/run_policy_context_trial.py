"""One development request using frozen expanded P03 evidence."""
import argparse
import getpass
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tradeintel_ai.policy_workflow import BoundedPolicyModel,load_frozen_corpus,run_generation
from tradeintel_ai.policy_retrieval import PolicyRetriever
from tradeintel_ai.policy_context_window import expand_context
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
OUTPUT=ROOT/'tmp/policy-context-13i'


def preflight():
    for relative in ['docs/experiments/phase13f-preflight/manifest.json','docs/experiments/phase13h-context/manifest.json']:
        manifest=json.loads((ROOT/relative).read_text())
        for name,digest in manifest.get('files',manifest).items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen file changed: '+name)
    corpus=load_frozen_corpus(ROOT)
    case=next(c for c in json.loads((ROOT/'evals/policy_acceptance_v1.json').read_text())['cases'] if c['id']=='P03')
    result=expand_context(PolicyRetriever(corpus).search(case['question'],as_of=case['as_of']),corpus)
    if result!=json.loads((ROOT/'docs/experiments/phase13h-context/P03.json').read_text()):raise ValueError('Expanded evidence changed')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    evidence=preflight()
    if not args.execute:print('指纹、窗口和预算预检通过；零API。');raise SystemExit(0)
    if OUTPUT.exists():raise SystemExit('本轮已存在，不重发')
    key=getpass.getpass('GLM密钥（隐藏输入，不保存）：').strip()
    if not key:raise SystemExit('密钥为空，停止')
    model=BoundedPolicyModel(OpenAICompatibleConfig('https://open.bigmodel.cn/api/paas/v4','glm-4.7',key,60,0))
    print('开始唯一一次扩窗开发请求，最多60秒，不重试。',flush=True)
    result=run_generation(model,evidence,OUTPUT,secret=key)
    print(result['generation']['status'],OUTPUT/'result.json')
