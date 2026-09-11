"""Explicit descriptive comparison contract. No model, selection or causal fit.

Used by explicit-comparison research plans.
The host must validate intent/provenance and obtain confirmation before reading
the series supplied to calculate(). Registered windows are host-owned metadata.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json

from .repository import RepositoryError
from .tools import ALLOWED_COMPARISONS, _month_key


def registered_comparison_metadata(repository):
    """Load amount-free window metadata and verify its summary fingerprint."""
    path = repository.paths.root / 'data/processed/analysis/registered_comparison_windows.json'
    if not path.exists():
        raise RepositoryError(f'登记窗口元数据不存在：{path}')
    try:
        with path.open(encoding='utf-8') as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryError(f'登记窗口元数据无法读取：{path}') from exc
    if not isinstance(value, dict):
        raise RepositoryError('登记窗口元数据必须是对象')
    source = value.get('source')
    if not isinstance(source, dict):
        raise RepositoryError('登记窗口元数据缺少 source')
    relative = source.get('path')
    expected = source.get('sha256')
    if relative != 'data/processed/analysis/statistical_baseline_summary.json':
        raise RepositoryError('登记窗口元数据来源路径不受支持')
    if (not isinstance(expected, str) or len(expected) != 64
            or any(char not in '0123456789abcdef' for char in expected)):
        raise RepositoryError('登记窗口元数据缺少摘要指纹')
    summary_path = repository.paths.root / relative
    if not summary_path.exists():
        raise RepositoryError('登记窗口元数据来源摘要不存在')
    actual = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    if actual != expected:
        raise RepositoryError('登记窗口元数据与统计摘要版本不一致')
    if not isinstance(value.get('comparisons'), dict):
        raise RepositoryError('登记窗口元数据缺少 comparisons')
    return value


def registered_windows(repository):
    """Load registered windows from amount-free, fingerprinted metadata."""
    metadata = registered_comparison_metadata(repository)
    comparisons = metadata.get('comparisons')
    if not isinstance(comparisons, dict):
        raise ValueError('统计摘要缺少登记比较窗口')
    windows = {}
    for comparison_id in ALLOWED_COMPARISONS:
        item = comparisons.get(comparison_id)
        if not isinstance(item, dict):
            raise ValueError(f'统计摘要缺少登记比较：{comparison_id}')
        windows[comparison_id] = {
            'comparison_id': comparison_id,
            'reference_months': item.get('reference_months'),
            'current_months': item.get('current_months'),
            'months_per_window': item.get('months_per_window'),
            'interpretation': item.get('interpretation'),
            'coverage_comparability_status': item.get('coverage_comparability_status'),
            'coverage_limit': item.get('coverage_limit'),
            'source': {
                'kind': 'derived',
                'path': 'data/processed/analysis/registered_comparison_windows.json',
                'summary_path': 'data/processed/analysis/statistical_baseline_summary.json',
                'summary_sha256': metadata['source']['sha256'],
            },
        }
    return windows


def _months(values):
    if not isinstance(values, list) or not values or len(values) > 48:
        raise ValueError('请明确1至48个请求月份')
    for value in values:
        _month_key(value)
    if len(set(values)) != len(values):
        raise ValueError('月份不能重复')
    return sorted(values)


def resolve(spec, trade, *, registered_windows=None):
    """Resolve exact windows without silently replacing the trade request."""
    if not isinstance(spec, dict):
        raise ValueError('必须明确比较方式，不能默认首末月变化')
    requested = _months(trade['months'])
    kind = spec.get('kind')
    if kind == 'sequence':
        if set(spec) != {'kind'}:
            raise ValueError('月序列不接受隐藏比较窗口')
        return {'kind': kind, 'requested_months': requested, 'causal_effect_estimated': False}
    if kind == 'endpoint':
        if set(spec) != {'kind', 'reference_month', 'current_month'}:
            raise ValueError('请明确基准月和比较月')
        reference, current = spec['reference_month'], spec['current_month']
        _month_key(reference)
        _month_key(current)
        if reference == current or reference not in requested or current not in requested:
            raise ValueError('基准月与比较月必须不同且都在请求月份内')
        return {'kind': kind, 'requested_months': requested,
                'reference_months': [reference], 'current_months': [current],
                'causal_effect_estimated': False}
    if kind == 'registered':
        if set(spec) != {'kind', 'comparison_id'}:
            raise ValueError('登记比较只接受明确的登记ID')
        cid = spec['comparison_id']
        if not isinstance(cid, str) or cid not in ALLOWED_COMPARISONS:
            raise ValueError('未知登记比较')
        if trade['granularity'] != 'policy_aggregate' or trade['hs6'] is not None:
            raise ValueError('登记窗口当前只对应政策整体，不能替代单商品比较')
        if registered_windows is None or cid not in registered_windows:
            raise ValueError('宿主未提供可核验的登记窗口')
        window = registered_windows[cid]
        reference = _months(window['reference_months'])
        current = _months(window['current_months'])
        if set(reference) & set(current) or len(reference) != len(current):
            raise ValueError('登记同期窗口须不重叠且月数相等')
        if sorted(m[5:] for m in reference) != sorted(m[5:] for m in current):
            raise ValueError('登记同期窗口的日历月份不一致')
        if sorted(reference + current) != requested:
            raise ValueError('请求月份与登记窗口不一致，必须重新预览确认')
        return {'kind': kind, 'comparison_id': cid, 'requested_months': requested,
                'reference_months': reference, 'current_months': current,
                'scope_note': ('历史ID中的clean不代表无预期：2018年3月已宣布行动，'
                               '4月有拟议名单；全部登记窗口仅作描述性比较。'),
                'window_source': deepcopy(window.get('source')),
                'window_interpretation': window.get('interpretation'),
                'coverage_comparability_status': window.get('coverage_comparability_status'),
                'coverage_limit': window.get('coverage_limit'),
                'causal_effect_estimated': False}
    raise ValueError('请选择sequence、endpoint或registered；不替换含糊的比较要求')


def calculate(contract, series):
    """Exact arithmetic on a confirmed, host-resolved series; never fill gaps."""
    if not isinstance(series, list) or not series:
        raise ValueError('没有贸易序列')
    values = {}
    for row in series:
        month, value = row['month'], row['value_usd']
        _month_key(month)
        if month in values or (value is not None and (type(value) is not int or value < 0)):
            raise ValueError('重复月份或无效金额')
        values[month] = value
    if sorted(values) != contract['requested_months']:
        raise ValueError('返回月份与确认计划不一致')
    result = {'kind': contract['kind'], 'causal_effect_estimated': False,
              'series_complete': all(value is not None for value in values.values())}
    if contract['kind'] == 'sequence':
        return {**result, 'series': [{'month': m, 'value_usd': values[m]} for m in sorted(values)],
                'status': 'completed' if result['series_complete'] else 'incomplete'}
    reference = [values[m] for m in contract['reference_months']]
    current = [values[m] for m in contract['current_months']]
    if any(value is None for value in reference + current):
        return {**result, 'status': 'incomplete', 'reference_total_usd': None,
                'current_total_usd': None, 'change_usd': None, 'change_percent': None,
                'reference_months': contract['reference_months'],
                'current_months': contract['current_months'], 'rate_status': 'missing_data'}
    baseline, target = sum(reference), sum(current)
    return {**result, 'status': 'completed', 'reference_months': contract['reference_months'],
            'current_months': contract['current_months'], 'reference_total_usd': baseline,
            'current_total_usd': target, 'change_usd': target - baseline,
            'change_percent': str((Decimal(target - baseline) * 100 / Decimal(baseline)).quantize(
                Decimal('0.01'))) if baseline else None,
            'rate_status': 'defined' if baseline else 'undefined_zero_reference'}


def render_comparison(summary):
    """Shared report text for explicit, validated comparisons."""
    comparison = summary['comparison']
    if comparison['kind'] == 'sequence':
        return ['比较方式：逐月序列；没有自动把首末月份相减。']
    lines = ['基准窗口：' + '、'.join(comparison['reference_months']),
             '当前窗口：' + '、'.join(comparison['current_months'])]
    if comparison['kind'] == 'endpoint':
        lines.insert(0, f"明确比较：{comparison['current_months'][0]} 相对 {comparison['reference_months'][0]}")
    else:
        lines.insert(0, '明确比较：登记同期窗口。')
    if comparison['status'] == 'incomplete':
        lines.append('比较所需金额缺失，无法计算差额或增长率；没有补零。')
    else:
        rate = comparison['change_percent']
        lines.append(f"金额变化：{comparison['change_usd']:,} 美元；变化率："
                     + (rate + '%' if rate is not None else '基准为零，增长率未定义') + '。')
    note = summary.get('comparison_contract', {}).get('scope_note')
    if note:
        lines.append(note)
    return lines
