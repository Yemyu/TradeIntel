"""Phase13d: original evidence question with explicit bounded GLM generation."""
import getpass
from pathlib import Path
from run_policy_smoke import preflight,run_once,OpenAICompatibleConfig,OpenAICompatibleModel

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'tmp/policy-bounded-13d'


class PolicyBoundedModel(OpenAICompatibleModel):
    def _payload(self, *, messages, tools):
        result=super()._payload(messages=messages,tools=tools)
        result.update(thinking={'type':'disabled'},max_tokens=512,stream=False)
        return result


if __name__=='__main__':
    evidence=preflight()
    if (OUTPUT/'attempt.json').exists(): raise SystemExit('本轮已尝试，禁止自动重发')
    key=getpass.getpass('GLM密钥（隐藏输入，不保存）：').strip()
    if not key: raise SystemExit('密钥为空，停止')
    model=PolicyBoundedModel(OpenAICompatibleConfig('https://open.bigmodel.cn/api/paas/v4','glm-4.7',key,60,0))
    print('开始本轮唯一一次政策请求：关闭思考，最多512输出tokens。',flush=True)
    result=run_once(model,evidence,OUTPUT,secret=key)
    print('记录已保存：',OUTPUT/'result.json')
    print('状态：',result.get('status',result.get('generation',{}).get('status')))
