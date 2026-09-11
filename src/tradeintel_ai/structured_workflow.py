"""Development host workflow for explicit requests, NOT a natural-language agent."""
from copy import deepcopy

from .capability_contract import assess_trade_request, source
from .evidence_v2 import EvidenceReport
from .evidence_v21 import EvidenceRegistryV21, report_v21
from .tools import ALLOWED_COMPARISONS
from .repository import RepositoryError


def execute_request(request, registry=None):
    registry = registry or EvidenceRegistryV21()
    base = {'version': 'structured-development-1', 'intent_verified': False,
            'task_success_verified': False, 'model_calls': 0,
            'model_selected_tools': [], 'host_selected_tools': [], 'tool_results': []}

    def message(status, reason, sources=None):
        report = EvidenceReport()
        report.add('处理说明', reason, sources or [source('src/tradeintel_ai/structured_workflow.py')])
        return {**base, 'status': status, 'response': report.render(),
                'facts': report.facts, 'sources': report.sources, 'structured_request_completed': False}

    if not isinstance(request, dict) or not isinstance(request.get('task'), str):
        return message('needs_clarification', '请提供明确的结构化任务；本接口不自动解释自然语言。')
    task = request['task']
    keys = {'trade': {'task', 'request'}, 'comparison': {'task', 'comparison_id'},
            **{name: {'task'} for name in ('counts', 'readiness', 'quality', 'policy')}}
    if task not in keys or set(request) != keys[task]:
        return message('needs_clarification', '未知任务或多余/缺失字段；没有忽略字段或执行其中一部分。')
    assessment = None
    if task == 'trade':
        try:
            assessment = assess_trade_request(request['request'], registry.repository)
        except (RepositoryError, OSError, KeyError, TypeError, ValueError):
            return message('execution_failed', '能力证据无法读取，停止执行；不能据此猜测可查范围。')
        base['capability_assessment'] = assessment
        state = assessment['status']
        if state == 'needs_clarification':
            return message(state, assessment['reason'])
        if state in ('unsupported_request', 'outside_coverage'):
            reasons = [r['reason'] for r in assessment['reasons']]
            if assessment['months_outside_declared_coverage']:
                reasons.append('所列月份超出2016-01至2019-12：' + ', '.join(assessment['months_outside_declared_coverage']))
            reasons.append('没有查询金额或执行写操作；不自动替换国家、指标或粒度。未知金额不能视为0。')
            return message('refused', '；'.join(reasons), assessment['capabilities']['sources'])
        trade = request['request']
        calls = [('get_trade_series', {'policy_id': trade['policy_id'], 'origin': trade['origin'],
                  'months': list(trade['months']), 'hs6': trade['hs6']})]
    elif task == 'comparison':
        cid = request['comparison_id']
        if not isinstance(cid, str) or cid not in ALLOWED_COMPARISONS:
            return message('needs_clarification', '请选择已登记的比较ID，不能默认替换比较窗口。')
        calls = [('get_descriptive_change', {'comparison_id': cid})]
    else:
        calls = [(name, {}) for name in {
            'counts': ['get_policy_event', 'get_causal_readiness'],
            'readiness': ['get_causal_readiness'], 'policy': ['get_policy_event'],
            'quality': ['get_data_quality_status']}[task]]
    if not any(name == 'get_causal_readiness' for name, _ in calls):
        calls.append(('get_causal_readiness', {}))
    try:
        for name, args in calls:
            base['host_selected_tools'].append(name)
            result = registry.call(name, args)
            base['tool_results'].append(result)
            if result.get('status') != 'ok' or result.get('tool_name') != name:
                return message('execution_failed', '登记工具未成功返回对应证据，停止发布金额；请检查执行记录。')
        results = base['tool_results']
        readiness = next(r['data'] for r in results if r['tool_name'] == 'get_causal_readiness')
        if (type(readiness.get('causal_allowed')) is not bool
                or readiness.get('status') in (None, '', 'unknown')):
            return message('execution_failed', '当前因果边界无法核验，停止发布。')
        if task == 'trade':
            data = results[0]['data']
            if (set(data['requested_months']) != set(trade['months'])
                    or len(data['requested_months']) != len(trade['months'])
                    or sorted(r['month'] for r in data['series']) != sorted(trade['months'])
                    or any(data[k] != trade[k] for k in ('origin', 'policy_id', 'hs6'))
                    or data['scope'] != 'section301_list1'):
                return message('execution_failed', '工具返回的月份或数据范围与明确请求不一致，停止发布金额。')
            values = [r['value_usd'] for r in data['series']]
            missing = [r['month'] for r in data['series'] if r['value_usd'] is None]
            observed_total = sum(v for v in values if type(v) is int)
            if (any(v is not None and (type(v) is not int or v < 0) for v in values)
                    or sorted(data['missing_months']) != sorted(missing)
                    or data['observed_total_usd'] != observed_total
                    or data['total_usd'] != (None if missing else observed_total)):
                return message('execution_failed', '金额、缺失状态与合计不一致，停止发布。')
        if task == 'comparison' and results[0]['data'].get('comparison_id') != cid:
            return message('execution_failed', '返回比较与请求不一致，停止发布。')
        report = report_v21(results)
        ledger = deepcopy({'facts': report.facts, 'sources': report.sources})
        labels = {f['label'] for f in report.facts}
        required = {'当前能力边界'}
        if task == 'counts':
            required |= {'三个计数为何不能混用', '合格处理商品分母', '至少有两个对照的处理商品数'}
            # Verify the policy count is actually rendered, not just that the call exists.
            if not any(f['label'] == '政策清单商品数量' and f.get('unit') == 'HTS8编码'
                       and type(f['value']) is int and f['value'] >= 0 for f in report.facts):
                return message('execution_failed', '政策清单计数证据不完整，停止发布。')
        if not required <= labels:
            return message('execution_failed', '任务所需解释或当前因果边界不完整，停止发布。')
        if task == 'trade':
            observed = [r for r in data['series'] if r['value_usd'] is not None]
            for fact in report.facts:
                if fact['label'] == '本次查询范围':
                    fact['value'] = {k: data[k] for k in ('policy_id', 'scope', 'hs6', 'origin')}
                    fact['value']['months'] = list(data['requested_months'])
                elif fact['label'] == '本次查询完整窗口合计':
                    fact['label'] = '所列请求月份合计'
                elif fact['label'] == '本次查询已观测月份合计' and not observed:
                    fact.update(value='无可计算观测', unit='')
                elif fact['label'] == '不可查月份说明':
                    fact['value'] = ('超出项目覆盖范围的月份金额未知，不能补零；不表示官方不存在数据。'
                        + ('已取得月份：' + ', '.join(r['month'] for r in observed) if observed else '没有取得可用月份金额。'))
        return {**base, 'status': 'evidence_ready', 'response': report.render(),
                'facts': report.facts, 'sources': report.sources, 'audit_ledger': ledger,
                'structured_request_completed': True,
                'limitation': 'Host execution of explicit input only; natural-language intent remains unverified.'}
    except (RepositoryError, OSError, KeyError, TypeError, ValueError):
        return message('execution_failed', '证据字段缺失或格式不符，停止发布；没有将部分结果当完整答案。')
