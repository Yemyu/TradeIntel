"""Literal request coverage, not an independent semantic correctness judge."""
from copy import deepcopy
import json


UNIT_KEYS = {'start', 'end', 'quote', 'kind', 'target'}
TARGETS = {'policy', 'trade_series', 'trade_comparison', 'unsupported', 'none'}
TASK_IDS = {'policy': 'policy_question', 'trade_series': 'trade_series',
            'trade_comparison': 'trade_comparison'}


def materialize_units(units, question):
    """Derive offsets from ordered exact quotes, never fuzzy-match or skip text."""
    if not isinstance(units, list) or not units or len(units) > 100:
        raise ValueError('quoted units must contain 1–100 units')
    result = []
    cursor = 0
    for item in units:
        if not isinstance(item, dict) or set(item) != {'quote', 'kind', 'target'}:
            raise ValueError('quoted unit fields')
        quote = item['quote']
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError('empty quoted unit')
        start = question.find(quote, cursor)
        if start < 0 or question[cursor:start].strip():
            raise ValueError('quote changed, reordered or request text omitted')
        cursor = start + len(quote)
        result.append({**item, 'start': start, 'end': cursor})
    # Reuse the original coverage/type validation; derived positions do not
    # relax coverage and do not verify the model's semantic labels.
    validate_units(result, question)
    return result


def validate_units(units, question):
    if not isinstance(units, list) or not units or len(units) > 100:
        raise ValueError('request_units must contain 1–100 units')
    end_previous = 0
    result = []
    requests = 0
    # Validate before sorting: invalid types should be format failures.
    for unit in units:
        if not isinstance(unit, dict) or set(unit) != UNIT_KEYS:
            raise ValueError('request unit fields')
        if type(unit['start']) is not int or type(unit['end']) is not int:
            raise ValueError('request unit offsets')
    for unit in sorted(units, key=lambda item: item['start']):
        start, end = unit['start'], unit['end']
        if not 0 <= start < end <= len(question) or start < end_previous:
            raise ValueError('request units overlap or invalid range')
        if question[end_previous:start].strip():
            raise ValueError('request text omitted')
        if unit['quote'] != question[start:end] or not unit['quote'].strip():
            raise ValueError('request quote mismatch')
        if unit['kind'] not in ('request', 'context', 'constraint') or unit['target'] not in TARGETS:
            raise ValueError('request kind or target')
        if unit['kind'] == 'request' and unit['target'] == 'none':
            raise ValueError('request has no target')
        if unit['kind'] != 'request' and unit['target'] != 'none':
            raise ValueError('context cannot create execution task')
        item = deepcopy(unit)
        if unit['kind'] == 'request':
            requests += 1
            item['id'] = f'request-{requests:03d}'
            item['task_id'] = TASK_IDS.get(unit['target'])
        else:
            item['id'] = None
            item['task_id'] = None
        result.append(item)
        end_previous = end
    if question[end_previous:].strip():
        raise ValueError('request text omitted at end')
    return result


def validate_mapping(units, plan):
    """Check claimed links; model misclassification still needs evaluation."""
    if plan['status'] == 'clarify':
        return
    requested = [u for u in units if u['kind'] == 'request']
    targets = {u['target'] for u in requested}
    tasks = set(plan['tasks'])
    if ('policy' in tasks) != ('policy' in targets):
        raise ValueError('policy task/request mismatch')
    if ('trade' in tasks) != bool(targets & {'trade_series', 'trade_comparison'}):
        raise ValueError('trade task/request mismatch')
    comparison = plan.get('comparison') or {}
    if ('trade_comparison' in targets) != (comparison.get('kind') in ('endpoint', 'registered')):
        raise ValueError('comparison task/request mismatch')
    for item in requested:
        if item['target'] == 'policy' and item['quote'] not in (plan.get('policy_question') or ''):
            raise ValueError('policy question omitted a policy request')


def preview_text(units, plan, status):
    lines = ['逐项需求核对（模型分类尚未独立验证，请核对是否遗漏或误解）：']
    for item in units:
        if item['kind'] != 'request':
            label = '背景' if item['kind'] == 'context' else '限制'
            lines.append('模型标为' + label + '：' + json.dumps(item['quote'], ensure_ascii=False))
            continue
        target = item['target']
        if target == 'unsupported':
            action = '暂不支持；需要调整范围，整份计划尚未执行'
        elif status != 'needs_confirmation':
            action = '尚未执行；需处理范围或缺失信息'
        elif target == 'policy':
            action = '政策原文检索与可选回答；资料截止 ' + str(plan.get('policy_as_of'))
        else:
            trade = plan.get('trade') or {}
            origin = {'China': '中国', 'other_origins': '其他原产地整体',
                      'all_origins': '全部原产地'}.get(trade.get('origin'), '待明确')
            action = (origin + '；美元消费进口额；商品 ' + str(trade.get('hs6') or '政策整体')
                      + '；月份 ' + ', '.join(trade.get('months') or []))
            if target == 'trade_comparison':
                comparison = plan.get('comparison') or {}
                if comparison.get('kind') == 'endpoint':
                    action += '；基准 ' + str(comparison.get('reference_month')) + ' → 比较 ' + str(comparison.get('current_month'))
                else:
                    action += '；登记窗口 ' + str(comparison.get('comparison_id'))
        # JSON quoting keeps source newlines/control characters visibly quoted.
        lines.append(item['id'] + '：' + json.dumps(item['quote'], ensure_ascii=False) + ' → ' + action)
    if (isinstance(plan.get('missing'), list) and plan['missing']
            and all(isinstance(item, str) for item in plan['missing'])):
        lines.append('待明确：' + '；'.join(plan['missing']))
    return '\n'.join(lines)


def request_results(units, obligations):
    states = {item['id']: item['status'] for item in obligations}
    return [{'id': item['id'], 'quote': item['quote'], 'target': item['target'],
             'task_id': item['task_id'],
             'execution_status': states.get(item['task_id'], 'not_executed'),
             'semantic_coverage_verified': False}
            for item in units if item['kind'] == 'request']
