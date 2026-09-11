"""Bounded model planning, local whole-plan confirmation, deterministic execution."""
from copy import deepcopy
import json
import secrets
from .agent import _normalise_response
from .intent_proposal import SYSTEM, _pairs, _constant
from .intent_presentation import propose_presented
from .intent_guarded import capability_feedback
from .evidence_v21 import EvidenceRegistryV21
from .structured_workflow import execute_request

PLAN_PROMPT = '''你是本项目的受限经济分析规划器，不是执行器。
下面的单任务字段和引文契约适用于每个子任务，但覆盖其“多个任务必须澄清”规则：
可以规划1至3个不同子任务，覆盖用户全部实际要求，不忽略否定、不替换范围。
输出仅JSON：{"status":"plan","steps":[单任务proposal对象],"missing":[]}，
或者{"status":"clarify","steps":[],"missing":["task或范围字段"]}。
每个steps对象有status,request,evidence,missing，按以下契约填写。
不能执行SQL、调用工具、编造数值。不要生成解释性答案。超过3项或无法完整覆盖时澄清。
用户只问政策后变化但没有明确登记窗口时澄清，不默认选择窗口。
每个任务独立保留国家、月份、指标及原文依据，不能把跨任务缺失字段猜出来。
counts是商品计数口径，readiness是匹配及因果分析条件，quality是数据质量，policy是政策资料。
只问能否归因属于readiness；要求计算未经支持的新因果效应不能换成描述查询。
''' + SYSTEM + '''
最终优先规则：上述单任务JSON仅用于steps中的元素。顶层只能是status、steps、missing。
1至3个明确任务应输出plan，不因为多个任务而clarify。超过3个或存在不可消解歧义才clarify。
每个子任务继续遵守原单任务字段与逐字引用契约。不要输出单任务顶层对象。
'''


class AnalysisPlanner:
    def __init__(self, model, registry=None):
        self.model=model
        self.registry=registry or EvidenceRegistryV21()
        self._pending=None

    def propose(self, question):
        self._pending=None
        base={'version':'analysis-plan-1','executed':False,'intent_verified':False,'model_calls':0}
        if not isinstance(question,str) or not question.strip() or len(question)>12000:
            return {**base,'status':'needs_clarification','response':'请提供不超过12000字的问题。'}
        base['model_calls']=1
        try:
            raw=_normalise_response(self.model.complete(messages=[{'role':'system','content':PLAN_PROMPT},
                                                                  {'role':'user','content':question}],tools=[]))
            if raw.tool_calls or raw.metadata.get('finish_reason')!='stop' or len(raw.text)>24000:
                raise ValueError('response contract')
            obj=json.loads(raw.text,object_pairs_hook=_pairs,parse_constant=_constant)
            if not isinstance(obj,dict) or set(obj)!={'status','steps','missing'}:raise ValueError('envelope')
            if obj['status']=='clarify':
                if obj['steps']!=[] or not isinstance(obj['missing'],list) or not obj['missing'] or any(
                    not isinstance(x,str) or not x.strip() or len(x)>100 for x in obj['missing']):raise ValueError('clarification')
                return {**base,'status':'needs_clarification','response':'模型尚不能明确覆盖全部要求，请确认任务数量和各任务范围；未执行。'}
            if obj['status']!='plan' or obj['missing']!=[] or not isinstance(obj['steps'],list) or not 1<=len(obj['steps'])<=3:
                raise ValueError('plan bounds')
            previews=[]
            for candidate in obj['steps']:
                class Recorded:
                    def complete(self, **kwargs):
                        return {'text':json.dumps(candidate,ensure_ascii=False),'metadata':{'finish_reason':'stop'}}
                preview=propose_presented(question,Recorded(),repository=self.registry.repository)
                if preview['parse_outcome']!='validated_proposal':raise ValueError('step invalid')
                previews.append(preview)
            requests=[p['request'] for p in previews]
            if len({json.dumps(r,sort_keys=True) for r in requests})!=len(requests):raise ValueError('duplicate step')
            text='请核对整个计划是否覆盖你的全部要求（程序尚不能证明没有遗漏）：\n'+ '\n\n'.join(
                f'子任务{i+1}：\n'+p['response'] for i,p in enumerate(previews))
            if any(p['status']!='needs_confirmation' for p in previews):
                return {**base,'status':'plan_blocked','steps':previews,'response':text+'\n整个计划未执行，请先调整不支持的任务。'}
            token=secrets.token_urlsafe(24)
            self._pending=(token,deepcopy(previews))
            return {**base,'status':'needs_confirmation','steps':previews,'confirmation_token':token,'response':text}
        except Exception:
            return {**base,'status':'needs_review','response':'规划未通过校验，未执行任何子任务；需要检查模型返回。'}

    def cancel(self):
        self._pending=None

    def confirm(self, token):
        if self._pending is None or not isinstance(token,str) or token!=self._pending[0]:
            return {'status':'confirmation_rejected','user_confirmed':False,'execution_attempted':False}
        _,previews=self._pending
        self._pending=None
        base={'user_confirmed':True,'intent_verified':False,'execution_attempted':False,'results':[]}
        # Recheck every capability before querying any amounts.
        for preview in previews:
            checked=capability_feedback(preview,repository=self.registry.repository)
            if checked['status']!='needs_confirmation':
                return {**base,'status':'plan_blocked','response':'能力复核未通过，整个计划未执行。'}
        base['execution_attempted']=True
        for preview in previews:
            result=execute_request(deepcopy(preview['request']),self.registry)
            base['results'].append(result)
            if result['status']!='evidence_ready':
                return {**base,'status':'incomplete','response':'计划未完整完成；已执行子任务保留在记录中，不发布部分报告作为完整答案。'}
        return {**base,'status':'evidence_ready','response':'\n\n'.join(
            f'子任务{i+1}报告\n'+r['response'] for i,r in enumerate(base['results'])),
            'limitation':'Separate evidence reports, not model-generated synthesis or verified intent coverage.'}
