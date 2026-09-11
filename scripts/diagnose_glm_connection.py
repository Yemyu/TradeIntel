"""Single minimal GLM request; explicit output budget, no automatic retries."""
import getpass
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

from run_policy_smoke import safe_error, OpenAICompatibleConfig, OpenAICompatibleModel

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'tmp/glm-minimal-13c'


class MinimalModel(OpenAICompatibleModel):
    def _payload(self, *, messages, tools):
        payload=super()._payload(messages=messages,tools=tools)
        payload.update(thinking={'type':'disabled'}, max_tokens=16, stream=False)
        return payload


def probe(key, output=OUTPUT, opener=urlopen):
    output.mkdir(parents=True,exist_ok=True)
    with (output/'attempt.json').open('x') as file:
        json.dump({'model':'glm-4.7','max_calls':1,'thinking':'disabled','max_tokens':16},file)
    started=time.monotonic()
    timing={}
    def timed_open(request, timeout):
        try:
            response=opener(request,timeout=timeout)
        except HTTPError as exc:
            timing.update(headers_seconds=round(time.monotonic()-started,3),http_status=exc.code)
            raise
        timing.update(headers_seconds=round(time.monotonic()-started,3),http_status=response.status)
        return response
    model=MinimalModel(OpenAICompatibleConfig('https://open.bigmodel.cn/api/paas/v4','glm-4.7',key,60,0),
                       system_prompt='',opener=timed_open)
    try:
        response=model.complete(messages=[{'role':'user','content':'Reply only OK.'}],tools=[])
        result={'status':'response_received','content':response.text,'nonempty':bool(response.text.strip()),
                'exact_ok':response.text.strip()=='OK','business_quality_measured':False}
    except (Exception,KeyboardInterrupt) as exc:
        result={'status':'stopped_without_retry','diagnostic':safe_error(exc)}
    result.update(timing,total_seconds=round(time.monotonic()-started,3),attempted_calls=1)
    encoded=json.dumps(result,ensure_ascii=False,indent=2)
    if key: encoded=encoded.replace(key,'[REDACTED]')
    with (output/'result.json').open('x') as file: file.write(encoded+'\n')
    return result


if __name__=='__main__':
    if (OUTPUT/'attempt.json').exists():
        raise SystemExit('该诊断已尝试，禁止自动重发')
    key=getpass.getpass('GLM密钥（隐藏输入，不保存）：').strip()
    if not key: raise SystemExit('未提供密钥，停止')
    print('开始唯一一次最小请求，关闭思考，最多16输出tokens。',flush=True)
    result=probe(key)
    print('诊断完成：',result['status'],'；记录：',OUTPUT/'result.json')
