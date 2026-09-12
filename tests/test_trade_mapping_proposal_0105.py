"""Offline synthetic contract checks, not model accuracy measurements."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_unified_research import plan, QUESTION as COMBINED_QUESTION
from tests.test_unified_research_v2 import trade_plan, planner
from tradeintel_ai.trade_mapping_proposal import propose_mapping
from tradeintel_ai.research_brief import ResearchBrief, render_brief
from tradeintel_ai.unified_research import UnifiedResearchWorkflow, inspect_delivery
from tradeintel_ai.development_smoke import snapshot


QUESTION = ('查询其他原产地整体2018-09和2018-10的美元消费进口额；'
            '比较2018-10相对于2018-09；只做描述性比较，不做因果分析；第一批关税，政策整体范围。')


def candidate():
    p = trade_plan()
    p.update(policy_search_query=None,
             comparison={'kind': 'endpoint', 'reference_month': '2018-09', 'current_month': '2018-10'},
             request_units=[{'quote': QUESTION, 'kind': 'request', 'target': 'trade'}])
    p['evidence']['trade.comparison'] = '2018-10相对于2018-09'
    return p


class NeutralProposalTests(unittest.TestCase):
    def test_endpoint_is_non_executable_and_preserves_source(self):
        p = candidate()
        before = deepcopy(p)
        result = propose_mapping(p, QUESTION)
        self.assertEqual(p, before)
        self.assertEqual(result['original_candidate'], before)
        self.assertEqual(result['derived_mapping'][0]['model_target'], 'trade')
        self.assertEqual(result['derived_mapping'][0]['derived_task_id'], 'trade_comparison')
        self.assertEqual(result['status'], 'needs_semantic_review')
        self.assertFalse(result['semantic_coverage_verified'])
        self.assertFalse(result['executable'])
        self.assertNotIn('confirmation_token', result)

    def test_sequence_does_not_create_comparison(self):
        p = candidate()
        p['comparison'] = {'kind': 'sequence'}
        p['evidence']['trade.comparison'] = '2018-09和2018-10'
        q = QUESTION.replace('比较2018-10相对于2018-09；', '')
        p['request_units'][0]['quote'] = q
        result = propose_mapping(p, q)
        self.assertEqual(result['derived_mapping'][0]['derived_task_id'], 'trade_series')
        self.assertEqual(result['comparison_contract']['kind'], 'sequence')

    def test_legacy_mismatch_is_not_repaired(self):
        for target in ('trade_series', 'trade_comparison'):
            p = candidate()
            p['request_units'][0]['target'] = target
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'no automatic repair'):
                propose_mapping(p, QUESTION)

    def test_bad_windows_and_hidden_sequence_fields_rejected(self):
        for spec in (
            {'kind': 'endpoint', 'reference_month': '2018-08', 'current_month': '2018-10'},
            {'kind': 'endpoint', 'reference_month': '2018-09', 'current_month': '2018-09'},
            {'kind': 'sequence', 'current_month': '2018-10'}, None,
        ):
            p = candidate()
            p['comparison'] = spec
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                propose_mapping(p, QUESTION)

    def test_reversed_or_misunderstood_intent_is_not_semantic_success(self):
        # These are structurally expressible. They must NOT be advertised as
        # automatically detected/approved semantic outcomes by this prototype.
        for spec in (
            {'kind': 'endpoint', 'reference_month': '2018-10', 'current_month': '2018-09'},
            {'kind': 'sequence'},
        ):
            p = candidate()
            p['comparison'] = spec
            result = propose_mapping(p, QUESTION)
            self.assertTrue(result['structural_validation_passed'])
            self.assertEqual(result['status'], 'needs_semantic_review')
            self.assertFalse(result['executable'])
            self.assertFalse(result['semantic_coverage_verified'])

    def test_unsupported_request_stops_whole_proposal(self):
        p = candidate()
        p['request_units'].append({'quote': '另算进口份额。', 'kind': 'request', 'target': 'unsupported'})
        result = propose_mapping(p, QUESTION + '另算进口份额。')
        self.assertEqual(result['status'], 'needs_scope_selection')
        self.assertFalse(result['executable'])

    def test_omitted_second_request_and_nonseparator_gaps_rejected(self):
        with self.assertRaises(ValueError):
            propose_mapping(candidate(), QUESTION + '另算进口份额。')

    def test_hidden_request_is_not_certified_by_character_coverage(self):
        p = candidate()
        p['request_units'].append({'quote': '另算进口份额。', 'kind': 'context', 'target': 'none'})
        result = propose_mapping(p, QUESTION + '另算进口份额。')
        self.assertFalse(result['semantic_coverage_verified'])
        self.assertFalse(result['executable'])

    def test_gap_is_retained_not_approved(self):
        p = candidate()
        p['request_units'][0]['quote'] = QUESTION[:-1]
        result = propose_mapping(p, QUESTION)
        gap = result['derived_alignment']['segments'][-1]
        self.assertEqual(gap['quote'], '。')
        self.assertEqual(gap['semantic_disposition'], 'unreviewed')
        self.assertFalse(result['executable'])

    def test_neutral_workflow_accepts_only_explicit_host_mode(self):
        legacy = UnifiedResearchWorkflow(planner(candidate()), require_request_units=True,
                                         derive_request_offsets=True)
        rejected = legacy.prepare(QUESTION)
        self.assertEqual(rejected['status'], 'needs_review')
        work = UnifiedResearchWorkflow(planner(candidate()), require_request_units=True,
                                       derive_request_offsets=True, neutral_trade_mapping=True)
        result = work.prepare(QUESTION)
        self.assertEqual(result['status'], 'needs_confirmation')
        self.assertEqual(result['plan']['model_request_units'][0]['target'], 'trade')
        self.assertEqual(result['plan']['request_units'][0]['target'], 'trade_comparison')
        self.assertEqual(result['plan']['request_unit_mapping'][0]['derived_target'], 'trade_comparison')
        self.assertFalse(result['plan']['request_unit_mapping'][0]['semantic_coverage_verified'])
        with tempfile.TemporaryDirectory() as tmp:
            delivered = work.confirm(result['confirmation_token'], Path(tmp) / 'delivery')
            self.assertEqual(delivered['entry_kind'], 'natural_language_plan')
            self.assertIn('范围由模型根据自然语言提出',
                          (Path(tmp) / 'delivery/report.zh-CN.md').read_text())

    def test_neutral_mode_rejects_old_trade_labels_instead_of_repairing(self):
        p = candidate()
        p['request_units'][0]['target'] = 'trade_series'
        result = UnifiedResearchWorkflow(planner(p), require_request_units=True,
                                         derive_request_offsets=True,
                                         neutral_trade_mapping=True).prepare(QUESTION)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['diagnostic']['category'], 'adapter_or_response_error')


class EntrySourceTests(unittest.TestCase):
    def test_development_smoke_manifest_marks_neutral_contract(self):
        from tests.test_development_smoke_0090 import config as smoke_config
        manifest = snapshot(smoke_config(), 'fixture', checklist_review=True,
                            host_gap_review=True, neutral_trade_mapping=True)
        self.assertEqual(manifest['version'], 'development-smoke-0108')
        self.assertEqual(manifest['integrity_revision'], '0108')
        self.assertTrue(manifest['neutral_trade_mapping'])
        self.assertTrue(manifest['host_gap_review'])
        default = snapshot(smoke_config(), 'fixture', checklist_review=True,
                           host_gap_review=True)
        self.assertNotEqual(manifest['fingerprints']['contract'],
                            default['fingerprints']['contract'])

    def test_natural_language_combined_delivery_source_and_hashes(self):
        work = UnifiedResearchWorkflow(planner(plan()))
        preview = work.prepare(COMBINED_QUESTION)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = work.confirm(preview['confirmation_token'], out)
            self.assertEqual(result['entry_kind'], 'natural_language_plan')
            text = (out / 'report.zh-CN.md').read_text()
            self.assertIn('范围由模型根据自然语言提出', text)
            self.assertNotIn('本入口没有让大模型自动理解', text)
            self.assertEqual(json.loads((out / 'result.json').read_text())['entry_kind'], 'natural_language_plan')
            self.assertEqual(inspect_delivery(out)['status'], 'complete')
            self.assertTrue(inspect_delivery(out)['verified'])

    def test_explicit_options_and_unlabelled_history(self):
        request = {k: v for k, v in plan().items() if k in ('policy_question', 'policy_as_of', 'trade')}
        work = ResearchBrief()
        preview = work.prepare(request)
        with tempfile.TemporaryDirectory() as tmp:
            result = work.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            self.assertEqual(result['entry_kind'], 'explicit_options')
            self.assertIn('范围来自明确选项', render_brief(result))
            del result['entry_kind']
            self.assertIn('未标记入口来源', render_brief(result))

    def test_invalid_entry_source_does_not_consume_confirmation(self):
        work = ResearchBrief()
        request = {k: v for k, v in plan().items() if k in ('policy_question', 'policy_as_of', 'trade')}
        preview = work.prepare(request)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            with self.assertRaises(ValueError):
                work.confirm(preview['confirmation_token'], out, entry_kind='user_guessed')
            self.assertFalse(out.exists())
            self.assertIsNotNone(work._pending)
