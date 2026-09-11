"""Independent development adapter; immutable evidence and no execution."""
from dataclasses import replace
import json
import re

from .intent_format import normalize_response
from .intent_guarded import propose_guarded, capability_feedback
from .intent_proposal import _pairs, _constant


def prepare_response(raw, question):
    response, changes = normalize_response(raw)
    candidate = None
    if response.tool_calls or response.metadata.get('finish_reason') != 'stop' or len(response.text) > 24000:
        return response, changes, candidate
    try:
        candidate = json.loads(response.text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        return response, changes, None
    if not isinstance(candidate, dict):
        return response, changes, None
    request = candidate.get('request')
    evidence = candidate.get('evidence')
    if not isinstance(request, dict) or request.get('task') != 'trade' or not isinstance(evidence, dict):
        return response, changes, candidate
    fields = request.get('request')
    quote = evidence.get('request.months')
    if (not isinstance(fields, dict) or not isinstance(fields.get('months'), list)
            or not isinstance(quote, str) or not quote or quote not in question):
        return response, changes, candidate
    updated = []
    converted = False
    for value in fields['months']:
        match = re.fullmatch(r'([0-9]{4})年([0-9]{1,2})月', value) if isinstance(value, str) else None
        if match and 1 <= int(match[1]) <= 9999 and 1 <= int(match[2]) <= 12 and value in quote:
            updated.append(f'{int(match[1]):04d}-{int(match[2]):02d}')
            converted = True
        else:
            updated.append(value)
    if converted:
        fields['months'] = updated
        changes = [*changes, 'literal_chinese_year_month']
        response = replace(response, text=json.dumps(candidate, ensure_ascii=False))
    return response, changes, candidate


def propose_presented(question, model, *, repository=None):
    captured = {}
    class PreparedModel:
        def complete(self, *, messages, tools):
            response, changes, candidate = prepare_response(model.complete(messages=messages, tools=tools), question)
            captured.update(changes=changes, candidate=candidate)
            return response
    result = propose_guarded(question, PreparedModel())
    result['version'] = 'intent-presentation-1'
    result['format_transformations'] = captured.get('changes', [])
    if result['parse_outcome'] == 'parse_failure':
        result.update(status='needs_review', response='本次模型返回未通过程序校验，尚未执行查询。需要检查解析记录；这不代表你的问题表达有误。')
    elif result['parse_outcome'] == 'model_clarification':
        labels = {'task': '本次要完成的单一任务', 'origin': '原产国家或国家范围',
                  'months': '年份和月份', 'policy_id': '政策范围', 'metric': '查询指标',
                  'granularity': '整体或商品粒度', 'hs6': '商品编码或整体范围',
                  'operation': '是否为只读查询', 'causal_effect': '描述数据还是要求因果结论',
                  'comparison_id': '登记比较项目', 'scope': '任务范围'}
        missing = captured['candidate']['missing']
        known = list(dict.fromkeys(labels[x.removeprefix('request.')] for x in missing if x.removeprefix('request.') in labels))
        result['clarification_fields'] = known
        result['response'] = '模型认为仍需确认：' + ('、'.join(known) if known else '任务或范围') + '。如果你已经说清，请纠正这份理解；尚未执行查询。'
    result = capability_feedback(result, repository=repository)
    assessment = result.get('capability_assessment', {})
    if assessment.get('status') == 'partially_in_coverage':
        outside = assessment['months_outside_declared_coverage']
        result['response'] += '\n注意：以下月份超出项目覆盖范围：' + '、'.join(outside) + '。原请求已完整保留，未自动删减月份，也未查询金额。'
    return result
