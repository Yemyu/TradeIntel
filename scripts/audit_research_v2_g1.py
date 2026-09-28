"""Offline counterexamples for the September 15 G1 review; no provider calls.

The default now runs regression checks for the repaired defects. The original
probes remain below as historical diagnosis code, not current acceptance.
Run from the repository root with .venv/bin/python scripts/audit_research_v2_g1.py.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle, render_observations
from src.tradeintel_ai.interpretation_review_store import packet, submit, reviewed_draft
from src.tradeintel_ai.research_brief_v2 import review
from src.tradeintel_ai.response_contract import canonical_response
from src.tradeintel_ai.web_app import DemoCoordinator
from tests.test_natural_v2 import FakeModel, FakeRepo, PROPOSAL, QUESTION
from tests.test_research_brief_v2 import synthetic_sheet, synthetic_trade


def block_network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise RuntimeError('network forbidden during G1 audit')


def run():
    results = {}
    coordinator = DemoCoordinator()
    with patch('src.tradeintel_ai.natural_v2.pin_repository', return_value=FakeRepo()), \
         patch('src.tradeintel_ai.web_app.load_config', side_effect=AssertionError('credentials forbidden')):
        preview = coordinator._natural_v2.preview(
            QUESTION, FakeModel(json.dumps(PROPOSAL)), repository=FakeRepo())
        try:
            coordinator.natural_confirm(preview['confirmation_token'], repository=FakeRepo(), output_root=Path('.'))
        except ValueError as exc:
            results['natural_confirm_to_execution'] = {'defect_reproduced': True, 'error': str(exc)}
        else:
            results['natural_confirm_to_execution'] = {'defect_reproduced': False}

    trade = synthetic_trade()
    trade['data']['series'][0]['product_breakdown'][0]['china_share_percent'] = 1.0
    bundle = build_evidence_bundle(trade, synthetic_sheet())
    results['share_not_recomputed'] = {
        'defect_reproduced': bundle['profiles'][0]['china_share_of_product_percent'] != 70.0,
        'amounts': {'china': 700, 'world': 1000}, 'expected_percent': 70.0,
        'actual_percent': bundle['profiles'][0]['china_share_of_product_percent'],
    }

    trade = synthetic_trade()
    trade['data']['hts8'] = '11111111'
    trade['data']['series'][0]['product_breakdown'] = [
        {'hts8': '11111111', 'all_origins_value_usd': 0,
         'china_value_usd': 0, 'china_share_percent': None}]
    bundle = build_evidence_bundle(trade, synthetic_sheet())
    try:
        render_observations(bundle)
    except TypeError as exc:
        results['zero_denominator_render'] = {'defect_reproduced': True, 'error': str(exc)}
    else:
        results['zero_denominator_render'] = {'defect_reproduced': False}
    results['single_product_false_ranking'] = {
        'defect_reproduced': any(o['type'].endswith('leader') for o in bundle['observations']),
        'observation_types': [o['type'] for o in bundle['observations']],
    }

    answer = {'schema_version': 'research-brief-v2', 'findings': [
        {'observation_id': 'observation.rank_contrast',
         'explanation': '金额和来源占比回答不同的问题。', 'limitation_ids': ['limitation.1']}],
        'followups': []}
    duplicate = copy.deepcopy(answer)
    duplicate['findings'] *= 2
    bundle = build_evidence_bundle(synthetic_trade(), synthetic_sheet())
    results['duplicate_findings_accepted'] = {
        'defect_reproduced': review(duplicate, bundle)['status'] == 'manual_review_required'}

    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory) / 'synthetic-review'
        folder.mkdir()
        raw = json.dumps(answer, ensure_ascii=False)
        files = {
            'status.json': {'status': 'interpretation_needs_review', 'data_version': 'v1'},
            'trade-evidence.json': synthetic_trade(), 'policy-facts.json': synthetic_sheet(),
            'interpretation-response.json': {'text': raw},
            'interpretation-canonical.json': canonical_response(raw, stage='interpretation'),
            'evidence-bundle.json': bundle,
        }
        for name, value in files.items():
            (folder / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        (folder / 'source-packet.zh-CN.md').write_text('Synthetic source packet', encoding='utf-8')
        p = packet(folder)
        submit(folder, {'fingerprint': p['fingerprint'], 'reviewer': 'synthetic audit',
                        'facts_checked': True, 'decisions': [
                            {'index': 0, 'verdict': 'accept', 'reason': 'Synthetic audit only'}]})
        exported = reviewed_draft(folder)
        results['export_lacks_numbers_and_sources'] = {
            'defect_reproduced': '700' not in exported and 'https://example.test/data' not in exported,
            'has_700_dollar_amount': '700' in exported,
            'has_trade_source_link': 'https://example.test/data' in exported,
        }
        changed = copy.deepcopy(bundle)
        changed['policy_id'] = 'different-policy'
        changed['data_version'] = 'different-version'
        (folder / 'evidence-bundle.json').write_text(json.dumps(changed), encoding='utf-8')
        try:
            changed_packet = packet(folder)
        except ValueError:
            results['cross_case_bundle_not_validated'] = {'defect_reproduced': False}
        else:
            results['cross_case_bundle_not_validated'] = {
                'defect_reproduced': True, 'packet_status': changed_packet['status'],
                'note': 'Existing approval becomes stale, but incoherent bundle remains reviewable.'}
    return {'scope': 'offline synthetic counterexamples, not model evaluation',
            'provider_calls': 0, 'g1': 'not_passed', 'findings': results}


if __name__ == '__main__':
    sys.addaudithook(block_network)
    import unittest
    suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_g1_repairs')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'provider_calls':0, 'regression_tests':result.testsRun,
                      'regression_passed':result.wasSuccessful(),
                      'g1':'not_yet_passed_remaining_requirements'}, ensure_ascii=False))
    sys.exit(not result.wasSuccessful())
