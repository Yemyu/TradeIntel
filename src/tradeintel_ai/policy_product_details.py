"""Versioned product details derived from pinned registration and reviewed clauses."""
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path

from .policy_cases import resolve_case

SCHEMA = 'archived-policy-facts-v2'
FIELDS = ('origin', 'effective_date', 'clock_24h', 'timezone', 'entry_events')


def reference(sheet, source_id):
    source = next(s for s in sheet['sources'] if s['id'] == source_id)
    return dict(policy_id=sheet['policy_id'], data_version=sheet['data_version'], chunk_id=source_id,
                text_sha256=source['text_sha256'], document_sha256=source['document_sha256'],
                url=source['url'])


def details(sheet, row, registration):
    scope = sheet['scope_source_id']
    clause = row['origin_source_id']
    source = next(s for s in sheet['sources'] if s['id'] == clause)
    # Preserve the entire reviewed clause: a code-only line can omit a shared
    # restriction. Shared text is not an assertion that every listed code is
    # part of the user's requested analysis.
    result = {'registered_name': registration['product_description'],
              'registered_name_zh': registration.get('product_description_zh') or None,
              'registered_name_zh_status': 'known' if registration.get('product_description_zh') else 'unknown',
              'registered_name_zh_reason': None if registration.get('product_description_zh') else '该版本登记表没有中文名称；不以自动翻译冒充登记内容。',
              'original_scope_clause': source['text'],
              'clause_role': 'shared_original_context_not_requested_product_list',
              'conditions': {'status':'unknown', 'reason':'仅核查登记公告片段；未逐笔核验商品限定、入境及其他适用条件。'},
              'exceptions': {'status':'unknown', 'reason':'未核全章98、排除清单及后续修订；未知不代表没有例外。'},
              **{key:deepcopy(sheet[key]) for key in FIELDS}}
    result['field_refs'] = {key:reference(sheet, row['origin_source_id'] if key == 'origin' else scope)
                            for key in FIELDS}
    result['field_refs']['additional_duty_percent'] = reference(sheet, row['source_id'])
    result['field_refs']['original_scope_clause'] = reference(sheet, clause)
    # Names are registration metadata, not a verbatim legal quotation.
    result['field_refs']['registered_name'] = {
        'policy_id':sheet['policy_id'], 'data_version':sheet['data_version'],
        'chunk_id':'registration:' + row['hts8'], 'kind':'registered_metadata_not_legal_quote',
        'path':sheet['registration']['path'], 'document_sha256':sheet['registration']['sha256'],
        'row_hts8':row['hts8'],
        'text_sha256':hashlib.sha256(json.dumps(registration, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        'url':registration.get('source_url') or source['url']}
    result['field_refs']['registered_name_zh'] = deepcopy(result['field_refs']['registered_name'])
    result['field_refs']['conditions'] = []
    result['field_refs']['exceptions'] = []
    return result


def enrich(sheet, root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    case = resolve_case(sheet['policy_id'], require_enabled=False)
    raw = (root / case.products).read_bytes()
    registrations = list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))
    indexed = {r['canonical_hts8']:r for r in registrations}
    expected = {r['hts8'] for r in sheet['product_rates']}
    if len(indexed) != len(registrations) or set(indexed) != expected or any(
            r['policy_id'] != sheet['policy_id'] or not r.get('product_description') for r in registrations):
        raise ValueError('registration scope mismatch')
    sheet['schema_version'] = SCHEMA
    sheet['registration'] = {'path':case.products, 'sha256':hashlib.sha256(raw).hexdigest(),
                             'csv_text':raw.decode('utf-8'), 'encoding':'utf-8'}
    for row in sheet['product_rates']:
        row['details'] = details(sheet, row, indexed[row['hts8']])
    return sheet


def validate_details(sheet):
    expected_date, expected_zone = (('2024-09-27', '美国东部夏令时间（EDT）')
        if sheet['policy_id'] == 'us_301_solar2024' else ('2025-01-01', '美国东部标准时间（EST）'))
    expected_scope = dict(effective_date=expected_date, timezone=expected_zone,
        clock_24h='00:01', origin='中国原产', entry_events=['消费入境','从仓库提取消费'])
    if any(sheet.get(key) != value for key, value in expected_scope.items()):
        raise ValueError('scope differs from reviewed mapping')
    registration = sheet.get('registration', {})
    text = registration.get('csv_text', '')
    # Registered project files are UTF-8 without BOM; reject unexpected bytes
    # instead of silently reinterpreting their provenance.
    if hashlib.sha256(text.encode()).hexdigest() != registration.get('sha256'):
        raise ValueError('registration hash mismatch')
    case = resolve_case(sheet['policy_id'], require_enabled=False)
    if registration.get('path') != case.products:
        raise ValueError('cross-case registration')
    rows = list(csv.DictReader(io.StringIO(text)))
    indexed = {r['canonical_hts8']:r for r in rows}
    if len(indexed) != len(rows) or set(indexed) != {r['hts8'] for r in sheet['product_rates']}:
        raise ValueError('registration product mismatch')
    for row in sheet['product_rates']:
        record = indexed[row['hts8']]
        if record['policy_id'] != sheet['policy_id'] or not record.get('product_description'):
            raise ValueError('invalid product registration')
        if row.get('details') != details(sheet, row, record):
            raise ValueError('product details or field provenance mismatch')


def project(sheet, codes):
    """Keep legacy bundles byte-equivalent; only v2 introduces projection."""
    result = deepcopy(sheet)
    if sheet.get('schema_version') != SCHEMA:
        return result
    selected = set(codes)
    result['product_rates'] = [r for r in result['product_rates'] if r['hts8'] in selected]
    if {r['hts8'] for r in result['product_rates']} != selected:
        raise ValueError('unknown product projection')
    used = {sheet['scope_source_id']}
    for row in result['product_rates']:
        used.update((row['source_id'], row['origin_source_id']))
    result['sources'] = [{**s, 'role':'shared_original_context_not_requested_product_list'}
                         for s in result['sources'] if s['id'] in used]
    # Full registration text and full facts remain in policy-facts.json only.
    result.pop('registration')
    result['schema_version'] = 'archived-policy-facts-projection-v2'
    result['requested_products'] = sorted(selected)
    return result
