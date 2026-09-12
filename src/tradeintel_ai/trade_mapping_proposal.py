"""0105 offline contract prototype; never an execution plan or a repair.

The proposed wire format classifies requests by domain (trade), leaving the
comparison kind in one field. A separate derived view is used only to reuse
legacy structural checks. Original labels and parameters are never replaced.
No caller in the production workflow imports this experimental module.
"""
from copy import deepcopy
import hashlib
import json

from .quote_gap_audit import audit_quote_gaps
from .research_comparison import resolve
from .unified_research import validate_plan, _TOP_KEYS_V4


def propose_mapping(candidate, question, *, registered_windows=None):
    """Build non-executable review material for the neutral-domain contract.

Even a structurally valid but reversed comparison remains semantic-unreviewed.
This function neither infers user intent nor approves a subsequent query.
"""
    if not isinstance(candidate, dict) or set(candidate) != _TOP_KEYS_V4:
        raise ValueError('neutral prototype requires full envelope')
    original = deepcopy(candidate)
    view = deepcopy(candidate)
    units = view['request_units']
    if not isinstance(units, list) or not units:
        raise ValueError('neutral request units required')
    for unit in units:
        if not isinstance(unit, dict) or set(unit) != {'quote', 'kind', 'target'}:
            raise ValueError('neutral quoted unit fields')
        if unit['target'] not in ('policy', 'trade', 'unsupported', 'none'):
            raise ValueError('legacy trade labels are not neutral; no automatic repair')
        if unit['target'] == 'trade' and unit['kind'] != 'request':
            raise ValueError('trade domain must be a request')
    contract = None
    if candidate['status'] == 'plan' and 'trade' in candidate['tasks']:
        contract = resolve(candidate['comparison'], candidate['trade'],
                           registered_windows=registered_windows)
    target = ('trade_comparison' if contract and contract['kind'] != 'sequence'
              else 'trade_series')
    for unit in units:
        if unit['target'] == 'trade':
            unit['target'] = target
    # The adapter view is explicitly derived, not the original model response.
    # Existing quote/gap restrictions and all base plan validation still apply.
    alignment = audit_quote_gaps(units, question)
    valid = validate_plan(view, question, host_alignment=alignment)
    source_hash = hashlib.sha256(json.dumps(
        {'question': question, 'candidate': original}, sort_keys=True,
        ensure_ascii=False).encode()).hexdigest()
    mapping = []
    for segment in alignment['segments']:
        if segment['source'] != 'model_quote':
            continue
        index = segment['unit_index']
        mapping.append({
            'unit_index': index, 'request_id': segment['id'],
            'quote': original['request_units'][index]['quote'],
            'model_target': original['request_units'][index]['target'],
            'derived_task_id': segment['task_id'],
            'source': 'host_derived_review_view',
            'rule': 'neutral_domain_plus_explicit_comparison_0105',
        })
    unsupported = any(u['target'] == 'unsupported' for u in units)
    return {
        'version': 'neutral-trade-mapping-proposal-0105',
        'question': question, 'original_candidate': original,
        'source_sha256': source_hash, 'comparison_contract': contract,
        'derived_mapping': mapping,
        'derived_alignment': alignment,
        'status': ('needs_scope_selection' if unsupported else
                   'needs_semantic_review' if valid else 'needs_clarification'),
        'structural_validation_passed': bool(valid),
        'semantic_coverage_verified': False, 'executable': False,
        'required_review': [
            '原话是否要求比较而非仅列数；基准月与比较月方向是否正确',
            '国家、商品粒度、月份和金额口径是否由原文支持',
            '是否遗漏或把独立要求藏在背景；额外份额等是否明确停止',
            '原文缺口是否仅为经核对的分隔符',
        ],
    }
