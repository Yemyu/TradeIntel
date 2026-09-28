"""Use reviewed local corpora; no provider calls or candidate publication."""
from copy import deepcopy
from pathlib import Path
import unittest

from src.tradeintel_ai.exposure_policy import retrieve_exposure_policy
from src.tradeintel_ai.primary_fact_sheet import build_primary_fact_sheet
from src.tradeintel_ai.solar_policy import build_corpus
from src.tradeintel_ai.solar_fact_sheet import build_fact_sheet
from src.tradeintel_ai.policy_facts_contract import validate_policy_facts
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle
from tests.test_research_brief_v2 import synthetic_trade

ROOT = Path(__file__).resolve().parents[1]


class PolicyFactsContractTests(unittest.TestCase):
    def test_product_details_and_references_are_bound(self):
        for sheet in (self.primary, self.solar):
            for row in sheet['product_rates']:
                d = row['details']
                self.assertTrue(d['registered_name'])
                self.assertEqual(d['exceptions']['status'], 'unknown')
                self.assertEqual(d['conditions']['status'], 'unknown')
                self.assertEqual(d['field_refs']['origin']['policy_id'], sheet['policy_id'])
                self.assertEqual(d['field_refs']['origin']['chunk_id'], row['origin_source_id'])
        mutations = [
            lambda s: s['product_rates'][0]['details'].pop('registered_name'),
            lambda s: s['product_rates'][0]['details']['field_refs']['origin'].update(policy_id='wrong'),
            lambda s: s['product_rates'][0]['details']['field_refs']['origin'].update(document_sha256='wrong'),
            lambda s: s['product_rates'][0]['details']['exceptions'].update(status='none'),
            lambda s: s['registration'].update(csv_text='changed'),
            lambda s: s.update(data_version='wrong-version'),
            lambda s: s.update(effective_date='2026-01-01'),
        ]
        for mutate in mutations:
            sheet = deepcopy(self.primary)
            mutate(sheet)
            with self.assertRaises(ValueError): validate_policy_facts(sheet)

    def test_single_product_projection_and_legacy_compatibility(self):
        from src.tradeintel_ai.policy_product_details import project
        from src.tradeintel_ai.solar_fact_sheet import render_fact_sheet
        original = deepcopy(self.primary)
        trade = synthetic_trade()
        trade['data']['policy_id'] = self.primary['policy_id']
        trade['data']['hts8'] = '81019910'
        trade['data']['series'][0]['product_breakdown'] = [
            {'hts8':'81019910', 'all_origins_value_usd':100, 'china_value_usd':20}]
        bundle = build_evidence_bundle(trade, self.primary)
        current = bundle['policy_facts']
        self.assertEqual([r['hts8'] for r in current['product_rates']], ['81019910'])
        self.assertNotIn('registration', current)
        self.assertNotIn('cbp63577329:p9', {s['id'] for s in current['sources']})
        self.assertEqual(self.primary, original)
        rendered = '\n'.join(render_fact_sheet(current))
        self.assertIn('钨棒', rendered)
        self.assertIn('例外：未知', rendered)
        self.assertNotIn('### 28046100', rendered)
        legacy = deepcopy(self.primary)
        legacy['schema_version'] = 'archived-policy-facts-v1'
        legacy.pop('registration')
        for row in legacy['product_rates']: row.pop('details')
        self.assertIs(validate_policy_facts(legacy), legacy)
        self.assertEqual(project(legacy, ['81019910']), legacy)
        legacy_bundle = build_evidence_bundle(trade, legacy)
        self.assertEqual(legacy_bundle['policy_facts'], legacy)
        self.assertEqual(legacy_bundle['sources'][-len(legacy['sources']):], legacy['sources'])

    @classmethod
    def setUpClass(cls):
        cls.primary = build_primary_fact_sheet(
            retrieve_exposure_policy(ROOT, '全部登记商品', as_of='2026-09-15'), 'v1')
        corpus = build_corpus(ROOT)
        cls.solar = build_fact_sheet({'policy_id': corpus['policy_id'], 'hits': corpus['chunks']}, 'v1')

    def test_both_cases_have_product_bound_common_contract(self):
        for sheet in (self.primary, self.solar):
            self.assertIs(validate_policy_facts(sheet), sheet)
            self.assertEqual(sheet['policy_view'], 'archived_event')
        self.assertEqual(len(self.primary['product_rates']), 5)
        self.assertEqual(len(self.solar['product_rates']), 2)

    def test_rate_origin_scope_and_source_tampering_rejected(self):
        mutations = [
            lambda s: s['product_rates'][0].update(additional_duty_percent=25),
            lambda s: s['product_rates'][0].update(origin_source_id='cbp63577329:p12'),
            lambda s: s['product_rates'].pop(),
            lambda s: s['sources'][0].update(text='changed'),
            lambda s: s.update(policy_view='current'),
            lambda s: s.update(policy_id='us_301_solar2024'),
        ]
        for mutate in mutations:
            sheet = deepcopy(self.primary)
            mutate(sheet)
            with self.assertRaises(ValueError):
                validate_policy_facts(sheet)

    def test_solar_bundle_isolated_from_primary_and_other_versions(self):
        trade = synthetic_trade()
        trade['data']['policy_id'] = self.solar['policy_id']
        for row, code in zip(trade['data']['series'][0]['product_breakdown'], ['85414200','85414300']):
            row['hts8'] = code
        bundle = build_evidence_bundle(trade, self.solar)
        self.assertEqual({p['hts8'] for p in bundle['profiles']}, {'85414200','85414300'})
        with self.assertRaises(ValueError):
            build_evidence_bundle(trade, self.primary)
        trade['data_version'] = 'another-version'
        with self.assertRaises(ValueError):
            build_evidence_bundle(trade, self.solar)
