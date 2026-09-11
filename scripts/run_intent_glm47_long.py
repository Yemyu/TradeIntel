"""GLM-4.7 matched-config development: 3 pilot cases, then remaining 9 only if all pass."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.intent_repair import BoundedModel, propose_repaired
from src.tradeintel_ai.intent_diagnostics import diagnose_response
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig
from scripts.check_intent_development import canonical

MANIFEST = ROOT / 'evals/intent_glm47_long_manifest.json'
PILOT = ('D01', 'D07', 'D12')


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight():
    manifest = json.loads(MANIFEST.read_text())
    for relative, expected in manifest['files'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or digest(path) != expected:
            raise ValueError('frozen file mismatch')
    cases = json.loads((ROOT/'evals/intent_development_cases.json').read_text())
    order = [next(c for c in cases if c['id']==i) for i in PILOT]
    order += [c for c in cases if c['id'] not in PILOT]
    return manifest, order


def run(*, execute=False, output=None, api_key='', opener=urlopen):
    manifest, cases = preflight()
    if not execute:
        return {'status':'preflight_passed','model':'glm-4.7','pilot':3,'maximum_api_requests':12}
    if not api_key or not api_key.isascii() or any(c.isspace() for c in api_key): raise ValueError('missing key')
    output = Path(output or ROOT/'tmp/intent-glm47-long'/ (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'))
    journal = output.with_suffix('.jsonl')
    if output.suffix!='.json' or output.exists() or journal.exists(): raise ValueError('invalid output')
    output.parent.mkdir(parents=True,exist_ok=True)
    report = {'status':'running','manifest':manifest,'manifest_sha256':digest(MANIFEST),
              'model':'glm-4.7','api_requests':0,'planned':12,'questions':[], 'model_adopted':False,
              'started_at':datetime.now(timezone.utc).isoformat()}
    def clean(value):
        if isinstance(value,str): return value.replace(api_key,'[REDACTED]')
        if isinstance(value,list): return [clean(v) for v in value]
        if isinstance(value,dict): return {clean(k):clean(v) for k,v in value.items()}
        return value
    with output.open('x',encoding='utf-8') as out, journal.open('x',encoding='utf-8') as log:
        def append(e):
            log.write(json.dumps(clean(e),ensure_ascii=False)+'\n'); log.flush(); os.fsync(log.fileno())
        append({'event':'run_started','manifest_sha256':report['manifest_sha256']})
        try:
            for index,case in enumerate(cases,1):
                state={'attempted':False,'response':None,'error':None}
                def capture(request, **kwargs):
                    if state['attempted'] or report['api_requests']>=12: raise ValueError('budget exceeded')
                    state['attempted']=True; report['api_requests']+=1
                    append({'event':'request_started','id':case['id'],'number':report['api_requests'],
                            'payload':json.loads(request.data)})
                    try:
                        with opener(request,**kwargs) as response: body=response.read()
                    except BaseException as exc:
                        state['error']=('http_'+str(exc.code) if isinstance(exc,HTTPError) else
                            'timeout' if isinstance(exc,TimeoutError) else 'connection' if isinstance(exc,URLError)
                            else 'interrupted' if isinstance(exc,KeyboardInterrupt) else 'transport')
                        append({'event':'request_failed','id':case['id'],'category':state['error']})
                        raise
                    append({'event':'http_response','id':case['id'],'body':body.decode('utf-8',errors='replace')})
                    return io.BytesIO(body)
                provider=BoundedModel(OpenAICompatibleConfig('https://open.bigmodel.cn/api/paas/v4','glm-4.7',api_key,180,0),
                                      system_prompt='',opener=capture)
                class Capture:
                    def complete(self,*,messages,tools):
                        try: response=provider.complete(messages=messages,tools=tools)
                        except BaseException:
                            state['error']=state['error'] or 'response_contract'
                            raise
                        state['response']=asdict(response)
                        append({'event':'response_recorded','id':case['id'],'response':state['response']})
                        return response
                print(f'开始 {index}/12：{case["id"]}（前三题通过才继续）',flush=True)
                result=propose_repaired(case['question'],Capture())
                diagnostic=diagnose_response(case['question'],state['response']) if state['response'] else {'stage':state['error'] or 'missing_response'}
                matched=(result['parse_outcome']=='model_clarification' if case['expected'] is None else
                         result['parse_outcome']=='validated_proposal' and canonical(result['request'])==canonical(case['expected']))
                item={'id':case['id'],'question':case['question'],'response':state['response'],'result':result,
                      'diagnostic':diagnostic,'exact_match':bool(matched)}
                report['questions'].append(item);append({'event':'answer_recorded','item':item})
                print(f'已记录 {index}/12：{diagnostic["stage"]}；请求结构符合参考={bool(matched)}',flush=True)
                if state['error'] or diagnostic['stage']=='unexpected_tool_call':
                    report.update(status='stopped',stop_reason=state['error'] or diagnostic['stage']);break
                if index==3 and not all(q['exact_match'] for q in report['questions']):
                    report.update(status='stopped',stop_reason='pilot_gate_not_met');break
            else: report['status']='collected_not_scored'
        except KeyboardInterrupt: report.update(status='interrupted',stop_reason='interrupted')
        except Exception: report.update(status='stopped',stop_reason='host_error')
        finally:
            report['finished_at']=datetime.now(timezone.utc).isoformat()
            report['exact_matches']=sum(q['exact_match'] for q in report['questions'])
            append({'event':'run_finished','status':report['status'],'api_requests':report['api_requests']})
            out.write(json.dumps(clean(report),ensure_ascii=False,indent=2)+'\n');out.flush();os.fsync(out.fileno())
    return {'status':report['status'],'api_requests':report['api_requests'],'exact_matches':report['exact_matches'],
            'planned':12,'output':str(output)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:
        print(json.dumps(run(),ensure_ascii=False),flush=True)
        if args.execute:
            result=run(execute=True,api_key=os.environ.get('TRADEINTEL_MODEL_API_KEY',''))
            print(json.dumps(result,ensure_ascii=False),flush=True)
            sys.exit(0 if result['status']=='collected_not_scored' else 1)
    except (ValueError,OSError,KeyError):
        print('预检/配置失败，未显示敏感信息。',flush=True);sys.exit(2)
