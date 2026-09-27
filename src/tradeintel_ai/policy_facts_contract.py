"""Structural contract for reviewed archived announcements, not legal advice."""
import hashlib

SCHEMA = 'archived-policy-facts-v1'
PRODUCTS = {
    'us_301_review2025_tungsten_solar': {'28046100': 50, '38180000': 50,
                                      '81019400': 25, '81019910': 25, '81019980': 25},
    'us_301_solar2024': {'85414200': 50, '85414300': 50},
}


def validate_policy_facts(sheet):
    """Check internal scope and provenance; extraction verifies original clauses."""
    if sheet.get('schema_version') not in (SCHEMA, 'archived-policy-facts-v2') or sheet.get('policy_view') != 'archived_event':
        raise ValueError('unsupported policy facts contract')
    expected = PRODUCTS.get(sheet.get('policy_id'))
    if not expected or not sheet.get('data_version'):
        raise ValueError('unregistered policy facts or missing version')
    if sheet.get('model_generated') is not False or sheet.get('legal_approval') is not False:
        raise ValueError('policy facts must not assert model or legal approval')
    for field in ('effective_date', 'clock_24h', 'timezone', 'origin', 'entry_events', 'limitations'):
        if not sheet.get(field):
            raise ValueError('missing policy scope field: ' + field)
    sources = sheet.get('sources', [])
    refs = {s['id']: s for s in sources}
    if len(refs) != len(sources):
        raise ValueError('duplicate policy source')
    for source in sources:
        if not source.get('url') or not source.get('document_sha256'):
            raise ValueError('missing policy provenance')
        if hashlib.sha256(source['text'].encode()).hexdigest() != source.get('text_sha256'):
            raise ValueError('policy source text hash mismatch')
    if sheet.get('scope_source_id') not in refs:
        raise ValueError('missing policy effective source')
    expected_scope = ('fr202421217:scope_and_effective' if sheet['policy_id'] == 'us_301_solar2024'
                      else 'cbp63577329:p8')
    if sheet['scope_source_id'] != expected_scope:
        raise ValueError('wrong effective scope source')
    if 'additional_duty_percent' in sheet and (
            len(set(expected.values())) != 1 or sheet['additional_duty_percent'] != next(iter(expected.values()))):
        raise ValueError('global rate conflicts with product rates')
    rows = sheet.get('product_rates', [])
    if len(rows) != len(expected) or {r['hts8'] for r in rows} != set(expected):
        raise ValueError('incomplete or duplicate policy product scope')
    for row in rows:
        if type(row.get('additional_duty_percent')) is not int or row['additional_duty_percent'] != expected[row['hts8']]:
            raise ValueError('archived product rate mismatch')
        if row.get('source_id') not in refs or row.get('origin_source_id') not in refs:
            raise ValueError('unbound product rate or origin source')
        if sheet['policy_id'] == 'us_301_solar2024':
            expected_rate_source, expected_origin_source = 'fr202421217:rate', 'fr202421217:scope_and_effective'
        else:
            expected_rate_source = 'cbp63577329:p9' if row['hts8'] in {'28046100','38180000'} else 'cbp63577329:p12'
            expected_origin_source = expected_rate_source
        if (row['source_id'], row['origin_source_id']) != (expected_rate_source, expected_origin_source):
            raise ValueError('product mapped to wrong reviewed clause')
    if sheet['schema_version'] == 'archived-policy-facts-v2':
        from .policy_product_details import validate_details
        validate_details(sheet)
    return sheet
