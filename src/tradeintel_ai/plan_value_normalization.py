"""Bounded representation conversion; not training or semantic verification.

Kept separate from frozen experiment implementations. Never executes requests.
"""
from dataclasses import replace
import json
import re

from .analysis_planner_v4 import ALIASES
from .intent_format import normalize_response
from .intent_proposal import _pairs, _constant


FIELD_ALIASES = {field: dict(values) for field, values in ALIASES.items()}
FIELD_ALIASES['operation']['只读查'] = 'read'
FIELD_ALIASES['origin'].update({
    '除中国外其他原产地合计': 'other_origins',
    '日本': 'Japan', '德国': 'Germany',
})
FIELD_ALIASES['granularity']['整体范围'] = 'policy_aggregate'


def literal_months(quote):
    """Accept only a complete explicit Chinese month list, not prose/ranges.

An omitted year can inherit within an ascending list only. December to January
without a second explicit year is intentionally left unresolved.
"""
    if not isinstance(quote, str) or not re.fullmatch(
        r'[0-9]{4}年[0-9]{1,2}月(?:[与和、](?:[0-9]{4}年)?[0-9]{1,2}月)*', quote
    ):
        return {}
    mapping = {}
    year = previous_month = None
    for part in re.split('[与和、]', quote):
        match = re.fullmatch(r'(?:([0-9]{4})年)?([0-9]{1,2})月', part)
        explicit_year, month = match.groups()
        month = int(month)
        if explicit_year is not None:
            year = int(explicit_year)
        elif previous_month is not None and month < previous_month:
            return {}
        if not year or not 1 <= month <= 12:
            return {}
        iso = f'{year:04d}-{month:02d}'
        mapping[f'{year}年{month}月'] = iso
        mapping[f'{year:04d}年{month:02d}月'] = iso
        previous_month = month
    return mapping


def normalize_plan_values(raw, question):
    response, changes = normalize_response(raw)
    if response.tool_calls or response.metadata.get('finish_reason') != 'stop' or len(response.text) > 24000:
        return response, changes
    try:
        obj = json.loads(response.text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        return response, changes
    if not isinstance(obj, dict) or not isinstance(obj.get('steps'), list):
        return response, changes
    converted = False
    for index, step in enumerate(obj['steps']):
        if not isinstance(step, dict):
            continue
        request, evidence = step.get('request'), step.get('evidence')
        if not isinstance(request, dict) or request.get('task') != 'trade' or not isinstance(evidence, dict):
            continue
        fields = request.get('request')
        if not isinstance(fields, dict):
            continue
        for field, aliases in FIELD_ALIASES.items():
            value, quote = fields.get(field), evidence.get('request.' + field)
            if not (isinstance(value, str) and value in aliases and isinstance(quote, str)
                    and value in quote and quote in question):
                continue
            if field == 'granularity' and value == '整体范围' and not (
                fields.get('policy_id') == 'us_301_list1_2018'
                and 'hs6' in fields and fields['hs6'] is None
            ):
                continue
            fields[field] = aliases[value]
            changes.append(f'step_{index+1}_literal_{field}')
            converted = True
        quote = evidence.get('request.months')
        months = fields.get('months')
        if isinstance(quote, str) and quote and quote in question and isinstance(months, list):
            mapping = literal_months(quote)
            updated = [mapping.get(value, value) if isinstance(value, str) else value for value in months]
            if updated != months:
                fields['months'] = updated
                changes.append(f'step_{index+1}_literal_months')
                converted = True
    if converted:
        response = replace(response, text=json.dumps(obj, ensure_ascii=False))
    return response, changes


class NormalizedPlanningModel:
    """Opt-in adapter for a planning model, not for the coverage reviewer."""
    def __init__(self, model):
        self.model = model
        self.transformations = []

    def complete(self, *, messages, tools):
        self.transformations = []
        raw = self.model.complete(messages=messages, tools=tools)
        response, self.transformations = normalize_plan_values(raw, messages[1]['content'])
        return response
