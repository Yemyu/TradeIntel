import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
import threading

from src.tradeintel_ai.agent import ModelResponse
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle
from src.tradeintel_ai.research_brief_v2 import review, task_coverage
from src.tradeintel_ai.response_contract import parse_json_response
from src.tradeintel_ai.interpretation_review_store import packet, submit, reviewed_draft
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig
from src.tradeintel_ai.web_app import create_server

ROOT = Path(__file__).resolve().parents[1]


def synthetic_sheet():
    return {
        'policy_id': 'fixture-policy', 'data_version': 'v1',
        'sources': [{'id': 'policy:p1', 'url': 'https://example.test/policy'}],
        'product_rates': [{'hts8': '11111111', 'source_id': 'policy:p1'},
                          {'hts8': '22222222', 'source_id': 'policy:p1'}],
        'limitations': ['政策条款是存档视图。'],
    }


def synthetic_trade():
    return {'status': 'ok', 'data_version': 'v1',
            'data': {'policy_id': 'fixture-policy', 'coverage_complete': True,
                     'measure': 'import_value_consumption_usd', 'origin': 'China',
                     'hts8': None, 'requested_months': ['2026-07'],
                     'series': [{'month': '2026-07', 'product_breakdown': [
                         {'hts8': '11111111', 'all_origins_value_usd': 1000, 'china_value_usd': 700, 'china_share_percent': 70.0},
                         {'hts8': '22222222', 'all_origins_value_usd': 9000, 'china_value_usd': 900, 'china_share_percent': 10.0},
                     ]}]},
            'limitations': ['没有企业实际税单。'],
            'evidence': {'sources': [{'id': 'trade:t1', 'url': 'https://example.test/data'}]}}


class ResearchBriefV2Tests(unittest.TestCase):
    def test_whole_task_coverage_is_not_single_finding_acceptance(self):
        bundle = build_evidence_bundle(synthetic_trade(), synthetic_sheet())
        findings = [{'observation_id': 'observation.' + kind}
                    for kind in ['amount_leader', 'share_leader', 'rank_contrast']]
        partial = task_coverage(findings[2:], bundle)
        self.assertEqual(partial['missing_observation_types'], ['amount_leader', 'share_leader'])
        complete = task_coverage(findings, bundle)
        self.assertTrue(complete['structural_coverage_complete'])
        self.assertFalse(complete['task_completed'])
        # A human rejecting one explanation removes its coverage again.
        self.assertEqual(task_coverage(findings[1:], bundle)['missing_observation_types'], ['amount_leader'])
        for focus, finding in [('china_amount', findings[0]), ('china_share', findings[1])]:
            scoped = build_evidence_bundle(synthetic_trade(), synthetic_sheet(), focus=focus)
            self.assertTrue(task_coverage([finding], scoped)['structural_coverage_complete'])
            self.assertFalse(task_coverage([], scoped)['structural_coverage_complete'])

    def test_single_product_has_profile_not_ranking_requirement(self):
        trade = synthetic_trade()
        trade['data']['hts8'] = '11111111'
        trade['data']['series'][0]['product_breakdown'] = trade['data']['series'][0]['product_breakdown'][:1]
        bundle = build_evidence_bundle(trade, synthetic_sheet())
        coverage = task_coverage([{'observation_id': 'observation.single_product_profile'}], bundle)
        self.assertTrue(coverage['structural_coverage_complete'])
        self.assertFalse(coverage['task_completed'])

    def test_identical_rankings_do_not_require_nonexistent_contrast(self):
        trade = synthetic_trade()
        trade['data']['series'][0]['product_breakdown'][1]['china_value_usd'] = 100
        bundle = build_evidence_bundle(trade, synthetic_sheet())
        coverage = task_coverage([{'observation_id': 'observation.amount_leader'},
                                  {'observation_id': 'observation.share_leader'}], bundle)
        self.assertTrue(coverage['structural_coverage_complete'])
        self.assertNotIn('rank_contrast', coverage['required_observation_types'])

    def test_response_contract_is_shared_and_lossless(self):
        value = {'schema_version': 'x', 'findings': []}
        self.assertEqual(parse_json_response('```json\n' + json.dumps(value) + '\n```'), value)
        with self.assertRaises(ValueError): parse_json_response('{"a":1,"a":2}')
        with self.assertRaises(ValueError): parse_json_response('```json\n{"a":1}\n``` trailing')

    def test_bundle_contains_distinct_amount_and_share_observations(self):
        bundle = build_evidence_bundle(synthetic_trade(), synthetic_sheet())
        self.assertEqual({o['type'] for o in bundle['observations']}, {'amount_leader', 'share_leader', 'rank_contrast'})
        self.assertEqual(next(o for o in bundle['observations'] if o['type'] == 'amount_leader')['value'], ['22222222'])
        self.assertEqual(next(o for o in bundle['observations'] if o['type'] == 'share_leader')['value'], ['11111111'])
        self.assertEqual(bundle['profiles'][1]['product_share_of_scope_world_percent'], 90.0)
        ratios = {metric['metric_type']: metric for metric in bundle['metrics']
                  if metric['unit'] == 'percent'}
        self.assertEqual(ratios['china_share_of_product_percent']['numerator_id'],
                         'metric.2026-07.22222222.china_import_usd')
        self.assertEqual(ratios['product_share_of_scope_world_percent']['numerator_id'],
                         'metric.2026-07.22222222.world_import_usd')
        self.assertEqual(ratios['product_share_of_scope_china_percent']['numerator_id'],
                         'metric.2026-07.22222222.china_import_usd')
        self.assertTrue(all(metric['source_refs'] for metric in bundle['metrics']))

    def test_v2_review_references_observations_and_keeps_human_gate(self):
        bundle = build_evidence_bundle(synthetic_trade(), synthetic_sheet())
        answer = {'schema_version': 'research-brief-v2',
                  'findings': [{'observation_id': 'observation.rank_contrast',
                                'explanation': '两个排序回答的是不同的关注角度，不能直接互换。',
                                'limitation_ids': ['limitation.1']}], 'followups': []}
        result = review(answer, bundle)
        self.assertEqual(result['status'], 'manual_review_required')
        self.assertFalse(result['approved'])
        answer['findings'][0]['explanation'] = '该政策必然导致损失。'
        self.assertEqual(review(answer, bundle)['status'], 'needs_revision')

    def test_primary_structured_v2_saves_bundle_canonical_and_review_packet(self):
        response = {'schema_version': 'research-brief-v2',
                    'findings': [{'observation_id': 'observation.rank_contrast',
                                  'explanation': '金额排序与来源占比排序关注的是不同问题。',
                                  'limitation_ids': ['limitation.1']}], 'followups': []}
        def model_response(self, **kwargs):
            return ModelResponse(text=json.dumps(response, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as folder:
            server = create_server(root=ROOT, port=0, output_root=Path(folder) / 'runs')
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            payload = {'policy_id': 'us_301_review2025_tungsten_solar', 'month': '2026-07',
                       'product': 'all', 'task': 'monthly_exposure'}
            try:
                with patch('src.tradeintel_ai.web_app.load_config', return_value=OpenAICompatibleConfig('https://example.invalid', 'fixture', 'fixture')), \
                     patch('src.tradeintel_ai.model_adapter.OpenAICompatibleModel.complete', model_response):
                    result = json.load(urlopen(Request(base + '/api/research-structured',
                        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Origin': base})))
                self.assertEqual(result['status'], 'interpretation_needs_review')
                run = Path(folder) / 'runs' / result['run_id']
                self.assertTrue((run / 'evidence-bundle.json').is_file())
                self.assertTrue((run / 'interpretation-canonical.json').is_file())
                review_packet = packet(run)
                self.assertEqual(review_packet['contract'], 'research-brief-v2')
                self.assertEqual(len(review_packet['notes']), 1, repr(review_packet))
                accepted = submit(run, {'fingerprint': review_packet['fingerprint'], 'reviewer': 'fixture',
                    'facts_checked': True, 'decisions': [{'index': 0, 'verdict': 'accept', 'reason': 'fixture only'}]})
                self.assertEqual(accepted['status'], 'recorded')
                self.assertEqual(packet(run)['accepted_task_coverage']['status'], 'incomplete')
                self.assertIn('采纳部分素材不等于整题完成', reviewed_draft(run))
                self.assertIn('金额排序与来源占比排序', reviewed_draft(run))
                canonical_path = run / 'interpretation-canonical.json'
                canonical = json.loads(canonical_path.read_text())
                canonical['parsed']['findings'][0]['explanation'] = 'tampered'
                canonical_path.write_text(json.dumps(canonical, ensure_ascii=False))
                with self.assertRaises(ValueError): packet(run)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)
