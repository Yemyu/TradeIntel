"""Audited policy generation. Provider metadata is evidence, not semantic proof."""
from dataclasses import replace
import hashlib
import json
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from .model_adapter import OpenAICompatibleModel
from .request_capture import sanitize_request_capture
from .policy_response_format import normalize_policy_response
from .policy_retrieval import draft_answer


class BoundedPolicyModel(OpenAICompatibleModel):
    def _payload(self, *, messages, tools):
        payload=super()._payload(messages=messages,tools=tools)
        payload.update(thinking={'type':'disabled'},max_tokens=512,stream=False)
        return payload


def safe_diagnostic(exc):
    seen=set()
    current=exc
    while current is not None and id(current) not in seen and len(seen)<5:
        seen.add(id(current))
        if isinstance(current,HTTPError): return {'category':'http','http_status':current.code}
        if isinstance(current,TimeoutError): return {'category':'timeout'}
        if isinstance(current,URLError):
            return {'category':'timeout' if isinstance(current.reason,TimeoutError) else 'connection'}
        current=current.__cause__
    return {'category':'interrupted' if isinstance(exc,KeyboardInterrupt) else 'adapter_or_response_error'}


def safe_metadata(metadata):
    finish=metadata.get('finish_reason')
    result={'finish_reason':finish if finish in ('stop','length','tool_calls','content_filter') else None,
            'finish_reason_known':finish in ('stop','length','tool_calls','content_filter')}
    usage=metadata.get('usage')
    result['usage']={k:v for k,v in (usage.items() if isinstance(usage,dict) else [])
                     if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v>=0}
    capture = sanitize_request_capture(metadata.get('request_capture')) if isinstance(metadata, dict) else None
    if capture is not None:
        result['request_capture'] = capture
    return result


def run_generation(model,evidence,output:Path,*,source_kind='live',secret=''):
    if source_kind not in ('live','archived_replay','fixture'): raise ValueError('Unknown source kind')
    # New directory is an at-most-once boundary. Never overwrite previous attempts.
    output.mkdir(parents=True,exist_ok=False)
    attempt_id = secrets.token_urlsafe(12)
    def save(name,value):
        text=json.dumps(value,ensure_ascii=False,indent=2)
        if secret: text=text.replace(secret,'[REDACTED]')
        with (output/name).open('x') as file: file.write(text+'\n')
    save('attempt.json',{'attempt_id': attempt_id, 'source_kind':source_kind,
                         'max_calls':1,'semantic_verified':False})
    save('evidence.json',evidence)
    audit={'attempt_id': attempt_id, 'source_kind':source_kind, 'model_calls':0,
           'new_api_calls':0,'semantic_verified':False}
    started=time.monotonic()
    class AuditedModel:
        def complete(self,**kwargs):
            if audit['model_calls']: raise RuntimeError('Single-call limit')
            audit['model_calls']+=1
            audit['new_api_calls']=1 if source_kind=='live' else 0
            raw=model.complete(**kwargs)
            metadata=safe_metadata(raw.metadata)
            audit['provider']=metadata
            save('raw_response.json',{'text':raw.text,'tool_call_count':len(raw.tool_calls),**metadata})
            normalized=normalize_policy_response(raw)
            if source_kind=='live' and metadata['finish_reason']!='stop':
                audit['completion_gate']='rejected_not_stop'
                normalized=replace(normalized,text='')
            else:
                audit['completion_gate']='stop' if metadata['finish_reason']=='stop' else 'archive_completion_unknown'
            audit['format_changes']=normalized.metadata.get('policy_format_changes',[])
            save('normalized_response.json',{'text':normalized.text,'format_changes':audit['format_changes']})
            return normalized
    try:
        generation=draft_answer(AuditedModel(),evidence)
    except (Exception,KeyboardInterrupt) as exc:
        generation={'status':'stopped_without_retry','claims':[],'semantic_verified':False}
        audit['diagnostic']=safe_diagnostic(exc)
    audit['elapsed_seconds']=round(time.monotonic()-started,3)
    result={'generation':generation,'audit':audit}
    save('result.json',result)
    # Consumers receive the same redacted artifact that was persisted.
    return json.loads((output/'result.json').read_text())


def load_frozen_corpus(root):
    """Validate frozen evidence bytes, independently of evolving application code.

    Historical experiment runners must additionally validate their own code
    manifests. Loading unchanged evidence does not reproduce historical scores.
    """
    path=root/'docs/experiments/phase13a-policy-retrieval/corpus.json'
    corpus=json.loads(path.read_text())
    manifest=json.loads(path.with_name('development_results.json').read_text())
    digest=hashlib.sha256(json.dumps(corpus,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if digest!=manifest['corpus_sha256']: raise ValueError('Frozen corpus fingerprint mismatch')
    for name,digest in {(c['local_path'], c['sha256']) for c in corpus['chunks']}:
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Frozen policy source changed')
    return corpus
