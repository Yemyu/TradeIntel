"""One-shot continuation of unattempted guarded development questions."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import time
import ssl
import socket
import http.client
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.intent_repair import BoundedModel
from src.tradeintel_ai.intent_guarded import propose_guarded as propose_repaired, capability_feedback
from src.tradeintel_ai.intent_diagnostics import diagnose_response
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig
from scripts.check_intent_development import canonical

from scripts.run_intent_guarded import preflight as parent_preflight
from scripts.review_intent_guarded import review as parent_review
MANIFEST = ROOT / 'evals/intent_continuation_manifest.json'
PARENT = ROOT / 'tmp/intent-guarded/20260908T160002375476Z.json'


def safe_error(exc):
    cause = exc.reason if isinstance(exc, URLError) else exc
    kinds = [(ssl.SSLError,'tls'), (TimeoutError,'timeout'),
             (http.client.IncompleteRead,'incomplete_read'),
             (http.client.RemoteDisconnected,'remote_disconnected'),
             (ConnectionResetError,'connection_reset'), (socket.gaierror,'dns'),
             (ConnectionError,'connection'), (KeyboardInterrupt,'interrupted')]
    category = next((label for cls,label in kinds if isinstance(cause,cls)), 'transport_unknown')
    if isinstance(exc,HTTPError): category='http'
    result={'category':category}
    if isinstance(exc,HTTPError): result['http_status']=int(exc.code)
    if isinstance(cause,OSError) and isinstance(cause.errno,int): result['errno']=cause.errno
    return result


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight():
    manifest = json.loads(MANIFEST.read_text())
    for relative, expected in manifest['files'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or digest(path) != expected:
            raise ValueError('frozen file mismatch')
    _, cases = parent_preflight()
    parent_review(PARENT)
    events=[json.loads(line) for line in PARENT.with_suffix('.jsonl').read_text().splitlines()]
    attempted={e['id'] for e in events if e['event']=='request_started'}
    remaining=[c for c in cases if c['id'] not in attempted]
    if len(remaining)!=23: raise ValueError('unexpected continuation scope')
    return manifest,remaining


def run(*, execute=False, output=None, api_key='', opener=urlopen, claim_dir=None):
    manifest, cases = preflight()
    if not execute:
        return {'status':'preflight_passed','model':'glm-4.7','maximum_api_requests':23}
    if not api_key or not api_key.isascii() or any(c.isspace() for c in api_key): raise ValueError('missing key')
    output = Path(output or ROOT/'tmp/intent-continuation'/ (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'))
    journal = output.with_suffix('.jsonl')
    if output.suffix!='.json' or output.exists() or journal.exists(): raise ValueError('invalid output')
    claims=Path(claim_dir or ROOT/'tmp/intent-continuation/claims')
    claims.mkdir(parents=True,exist_ok=True)
    if any((claims/(c['id']+'.json')).exists() for c in cases):
        raise ValueError('continuation already claimed; inspect existing logs')
    output.parent.mkdir(parents=True,exist_ok=True)
    report = {'status':'running','manifest':manifest,'manifest_sha256':digest(MANIFEST),
              'model':'glm-4.7','api_requests':0,'planned':23,'questions':[], 'model_adopted':False,
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
                    if state['attempted'] or report['api_requests']>=23: raise ValueError('budget exceeded')
                    with (claims/(case['id']+'.json')).open('x') as claim:
                        json.dump({'id':case['id'],'output':str(output),'parent_sha256':digest(PARENT)},claim)
                        claim.flush();os.fsync(claim.fileno())
                    started=time.monotonic()
                    state['attempted']=True; report['api_requests']+=1
                    append({'event':'request_started','id':case['id'],'number':report['api_requests'],
                            'payload':json.loads(request.data)})
                    try:
                        with opener(request,**kwargs) as response: body=response.read()
                    except BaseException as exc:
                        detail=safe_error(exc)
                        state['error']=detail['category']
                        append({'event':'request_failed','id':case['id'],**detail,
                                'elapsed_seconds':round(time.monotonic()-started,3)})
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
                print(f'开始 {index}/23：{case["id"]}（仅未尝试题，无重试）',flush=True)
                result=propose_repaired(case['question'],Capture())
                diagnostic=diagnose_response(case['question'],state['response']) if state['response'] else {'stage':state['error'] or 'missing_response'}
                matched=(result['parse_outcome']=='model_clarification' if case['expected'] is None else
                         result['parse_outcome']=='validated_proposal' and canonical(result['request'])==canonical(case['expected']))
                item={'id':case['id'],'question':case['question'],'response':state['response'],'result':result,
                      'diagnostic':diagnostic,'exact_match':bool(matched), 'feedback':capability_feedback(result)}
                report['questions'].append(item);append({'event':'answer_recorded','item':item})
                print(f'已记录 {index}/23：{diagnostic["stage"]}；请求结构符合参考={bool(matched)}',flush=True)
                if state['error'] or diagnostic['stage']=='unexpected_tool_call':
                    report.update(status='stopped',stop_reason=state['error'] or diagnostic['stage']);break
            else: report['status']='collected_not_scored'
        except KeyboardInterrupt: report.update(status='interrupted',stop_reason='interrupted')
        except Exception: report.update(status='stopped',stop_reason='host_error')
        finally:
            report['finished_at']=datetime.now(timezone.utc).isoformat()
            report['exact_matches']=sum(q['exact_match'] for q in report['questions'])
            append({'event':'run_finished','status':report['status'],'api_requests':report['api_requests']})
            out.write(json.dumps(clean(report),ensure_ascii=False,indent=2)+'\n');out.flush();os.fsync(out.fileno())
    return {'status':report['status'],'api_requests':report['api_requests'],'exact_matches':report['exact_matches'],
            'planned':23,'output':str(output)}


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
