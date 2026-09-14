"""One frozen synthetic comparison, not a policy accuracy benchmark."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tradeintel_ai.local_provider_config import load_config
from tradeintel_ai.research_models import ResearchPlannerModel, JsonResearchModel
from tradeintel_ai.provider_diagnostics import safe_provider_diagnostic

OUTPUT = ROOT/'tmp/json-mode-capability-v1'
MESSAGES = [
    {'role':'system','content':'只返回JSON对象，不要Markdown。唯一顶层键为items，值为数组。每个元素只能有id、status、value、citation四个字符串字段。每个输入ID恰好一次。找到记录时status必须为supported，value和citation逐字复制记录；无记录时status必须为unknown，value和citation为空字符串。禁止推测，禁止额外字段。'},
    {'role':'user','content':'这是虚构库存，不是政策。查询ID：A07、B12、C03。记录：A07的value为蓝色，citation为inventory:7；C03的value为绿色，citation为inventory:3。'}]


def judge(text):
    def unique(pairs):
        result = {}
        for k,v in pairs:
            if k in result: raise ValueError('duplicate key')
            result[k] = v
        return result
    try:
        obj = json.loads(text, object_pairs_hook=unique)
        if not isinstance(obj,dict) or set(obj) != {'items'}: return False
        items = obj['items']
        if not isinstance(items,list) or len(items)!=3: return False
        expected = {'A07':('supported','蓝色','inventory:7'),
                    'B12':('unknown','',''), 'C03':('supported','绿色','inventory:3')}
        seen = set()
        for item in items:
            if not isinstance(item,dict) or set(item)!={'id','status','value','citation'}: return False
            if not all(isinstance(v,str) for v in item.values()): return False
            key=item['id']
            if key in seen or key not in expected: return False
            seen.add(key)
            if tuple(item[k] for k in ('status','value','citation'))!=expected[key]: return False
        return seen == set(expected)
    except (ValueError,TypeError): return False


def run():
    config=replace(load_config(),model='glm-4.7',temperature=0.0,timeout_seconds=45.0)
    if not config.api_key: raise ValueError('local key unavailable')
    OUTPUT.mkdir(parents=True,exist_ok=False)
    def save(name,obj):
        (OUTPUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2).replace(config.api_key,'[REDACTED]'))
    models=[]
    for cls in (ResearchPlannerModel,JsonResearchModel):
        model=cls(config)
        model.max_output_tokens=512
        models.append(model)
    save('freeze.json',{'messages':MESSAGES,'settings':[m.effective_request_settings() for m in models],
        'max_calls':2,'max_output_tokens_per_call':512,'timeout_seconds':45,'retries':0,
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'protocol_sha256':hashlib.sha256((ROOT/'docs/experiments/json-mode-capability-v1.zh-CN.md').read_bytes()).hexdigest()})
    rows=[]
    for label,model in zip(('text','json_object'),models):
        row={'mode':label,'attempted':True}
        rows.append(row)
        save('results.json',rows)
        start=time.monotonic()
        try:
            reply=model.complete(messages=MESSAGES,tools=[])
            row.update(status='response_received',passed=judge(reply.text),text=reply.text,
                       usage=reply.metadata.get('usage'),seconds=round(time.monotonic()-start,3))
        except Exception as exc:
            row.update(status='failed',diagnostic=safe_provider_diagnostic(exc),seconds=round(time.monotonic()-start,3))
            save('results.json',rows)
            break
        save('results.json',rows)
    return [{k:v for k,v in row.items() if k!='text'} for row in rows]


if __name__=='__main__':
    print(json.dumps(run(),ensure_ascii=False))
