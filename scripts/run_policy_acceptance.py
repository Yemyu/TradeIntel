"""Execute protocol 0060 once, without placing review answers in model context."""
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
from tradeintel_ai.model_adapter import OpenAICompatibleConfig

OUTPUT=ROOT/'tmp/policy-acceptance-13g'


def preflight():
    manifest=json.loads((ROOT/'docs/experiments/phase13f-preflight/manifest.json').read_text())
    for name,digest in manifest['files'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Frozen file changed: '+name)
    cases=json.loads((ROOT/'evals/policy_acceptance_v1.json').read_text())['cases']
    retriever=PolicyRetriever(load_frozen_corpus(ROOT))
    rows=[]
    for case in cases:
        evidence=retriever.search(case['question'],as_of=case['as_of'])
        if case['expected']=='no_evidence' and evidence['hits']:
            raise ValueError('Zero-call boundary violation')
        rows.append((case['id'],evidence))
    if sum(bool(e['hits']) for _,e in rows)>5: raise ValueError('Call budget exceeded')
    return rows


def execute(rows,model,output,secret='',source_kind='live'):
    output.mkdir(parents=True,exist_ok=False)
    def save(name,value):
        with (output/name).open('x') as file:
            file.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    save('manifest.json',{'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_kind':source_kind,'max_calls':5,'questions':[i for i,_ in rows]})
    summary=[]
    stopped=False
    for case_id,evidence in rows:
        if stopped:
            summary.append({'id':case_id,'status':'not_executed_after_infrastructure_stop'})
            continue
        print('处理',case_id,'；有证据=',bool(evidence['hits']),flush=True)
        result=run_generation(model,evidence,output/case_id,secret=secret,source_kind=source_kind)
        summary.append({'id':case_id,'status':result['generation']['status'],
                        'api_calls':result['audit']['new_api_calls']})
        stopped=result['generation']['status']=='stopped_without_retry'
    save('summary.json',{'cases':summary,'infrastructure_stopped':stopped,
        'api_calls':sum(r.get('api_calls',0) for r in summary),'semantic_review':'pending'})
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    rows=preflight()
    if not args.execute:
        print('8题指纹和边界预检通过；最多5次请求；未调用模型。')
        raise SystemExit(0)
    if OUTPUT.exists(): raise SystemExit('本批目录已存在，禁止盲目续跑或覆盖')
    key=getpass.getpass('GLM密钥（隐藏输入，不保存）：').strip()
    if not key: raise SystemExit('密钥为空，停止')
    model=BoundedPolicyModel(OpenAICompatibleConfig('https://open.bigmodel.cn/api/paas/v4','glm-4.7',key,60,0))
    execute(rows,model,OUTPUT,secret=key)
    print('本批已结束，记录：',OUTPUT/'summary.json')
