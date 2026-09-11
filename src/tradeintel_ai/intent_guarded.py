"""Development candidate: exact quotes, syntax normalization and explicit refusal."""
from copy import deepcopy
from .intent_catalog import CATALOG, propose_catalog
from .intent_format import normalize_response
from .capability_contract import assess_trade_request
from .repository import RepositoryError

GUARDED_PROMPT = CATALOG + '''

请求转写与实际执行是两件事：这里只转写需求，绝不执行操作。
用户已明确指定但本系统不支持的值，不等于缺少信息。例如operation可以忠实记录
delete，granularity可以记录company，metric可以记录用户明确的其他指标名称。
返回proposal记录该意图，后续宿主将明确拒绝；不要把它们改成read或整体粒度，
也不要因为系统不支持就声称用户没有说清。只有信息确实缺失/歧义才clarify。
如果用户在引号内提到被明确排除执行的命令，仍只转写实际请求。
evidence的每个值必须逐字复制用户原文中的一段连续字符串，不加省略号、不翻译、
不改标点、不串接分散片段、不用枚举值代替原文。可以选覆盖该信息的完整连续句子。
comparison的证据路径是task和comparison_id；trade则是task和request.字段名。
'''


def propose_guarded(question, model):
    transformations=[]
    class GuardedModel:
        def complete(self, *, messages, tools):
            messages=deepcopy(messages)
            if messages[0] != {'role':'system','content':CATALOG} or tools:
                raise ValueError('unexpected prompt contract')
            messages[0]['content']=GUARDED_PROMPT
            response,changes=normalize_response(model.complete(messages=messages,tools=[]))
            transformations.extend(changes)
            return response
    result=propose_catalog(question,GuardedModel())
    result.update(version='intent-guarded-1',format_transformations=transformations)
    return result


def capability_feedback(result, *, repository=None):
    """Assess an already validated interpretation. Never query amounts or execute writes."""
    result=deepcopy(result)
    if result.get('parse_outcome')!='validated_proposal' or result.get('request',{}).get('task')!='trade':
        return result
    try:
        assessment=assess_trade_request(result['request']['request'],repository)
    except (RepositoryError,OSError,KeyError,TypeError,ValueError):
        result.update(status='needs_review',response='无法读取能力登记，尚未执行查询。')
        return result
    result['capability_assessment']=assessment
    if assessment['status'] in ('unsupported_request','outside_coverage'):
        request=result['request']['request']
        reasons=[]
        for reason in assessment['reasons']:
            value=request.get(reason['field'])
            reasons.append(f"{reason['field']}={value}：{reason['reason']}")
        if assessment['months_outside_declared_coverage']:
            reasons.append('这些月份超出2016-01至2019-12覆盖范围：'+', '.join(assessment['months_outside_declared_coverage']))
        result.update(status='interpreted_refusal',
            response='按当前理解，这项请求超出本项目能力：\n'+'\n'.join(reasons)
                     +'\n没有查询金额或执行写入操作；若以上理解不符，请纠正请求。',
            capability_sources=assessment['capabilities']['sources'])
    # The original interpretation remains visible; human confirmation is still required for execution.
    result.update(executed=False,intent_verified=False,task_success_verified=False)
    return result
