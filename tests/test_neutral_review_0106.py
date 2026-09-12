"""Review integration: synthetic responses, real local trade pipeline, no API."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_trade_mapping_proposal_0105 import candidate, QUESTION
from tests.test_unified_research_v2 import planner
from tests.test_development_smoke_0090 import config
from tests.test_host_gap_review_0103 import approve
from tradeintel_ai.development_smoke import workflow, run_batch, CASES
from tradeintel_ai.answer_checklist import template, load_checklists
from tradeintel_ai.quote_gap_audit import validate_gap_review


class NeutralReviewTests(unittest.TestCase):
    def work(self, p):
        return workflow(planner(p), 'fixture', True, True, True)

    def test_new_prompt_has_one_allowed_target_list(self):
        w = self.work(candidate())
        w.prepare(QUESTION)
        prompt = w.planner_model.complete.call_args.kwargs['messages'][0]['content']
        self.assertIn('target只能是policy/trade/unsupported/none', prompt)
        self.assertNotIn('target只能是policy/trade_series/trade_comparison', prompt)

    def test_new_batch_cannot_disable_checklist_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            with self.assertRaisesRegex(ValueError, 'independent checklist'):
                run_batch(config(), out, reviewer=lambda p: True, reviewer_id='fixture',
                          source_kind='fixture', neutral_trade_mapping=True)
            self.assertFalse(out.exists())

    def test_gap_record_binds_original_targets_and_comparison_direction(self):
        p = candidate()
        p['request_units'][0]['quote'] = QUESTION[:-1]
        w = self.work(p)
        preview = w.prepare(QUESTION)
        self.assertEqual(preview['status'], 'needs_gap_review')
        audit = preview['gap_audit']
        self.assertEqual(audit['neutral_source']['request_units'], p['request_units'])
        self.assertEqual(audit['neutral_source']['comparison'], p['comparison'])
        submission = approve(audit)
        for change in ('label', 'direction'):
            altered = deepcopy(audit)
            if change == 'label':
                altered['neutral_source']['request_units'][0]['target'] = 'trade_comparison'
            else:
                altered['neutral_source']['comparison'].update(reference_month='2018-10', current_month='2018-09')
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_gap_review(altered, submission)
        result = w.approve_gap_review(preview['gap_review_token'], submission)
        self.assertEqual(result['status'], 'needs_confirmation')

    def test_trade_batch_review_blocks_negative_or_changed_sources(self):
        # Isolate the existing third case to reach its real review and execution
        # boundaries without fabricating policy answers. This is not a live run.
        frozen = load_checklists(CASES)
        case = deepcopy(CASES[2])
        case['question'] = QUESTION
        for mode in ('accepted', 'reverse', 'sequence', 'wrong_product', 'missing_review', 'changed_file'):
            p = candidate()
            p['request_units'][0]['quote'] = QUESTION[:-1]
            if mode == 'reverse':
                p['comparison'].update(reference_month='2018-10', current_month='2018-09')
            if mode == 'sequence': p['comparison'] = {'kind': 'sequence'}
            if mode == 'wrong_product':
                # Ambiguous literal evidence is structurally expressible; the
                # reviewer must still reject a scope unsupported by the request.
                p['evidence']['trade.granularity'] = '其他原产地整体'
            stages = []
            def review(packet):
                stages.append(packet['stage'])
                r = template(packet)
                r['overall'] = {'status': 'pass', 'reason': 'Synthetic fixture review'}
                for row, check in zip(r['items'], packet['checklist']):
                    row.update(status='covered' if packet['stage'] == 'plan' else 'supported',
                               reason='Synthetic fixture witness')
                    if packet['stage'] == 'answer': row['checks'] = check['checks']
                if packet['stage'] == 'plan':
                    r['gap_review'] = approve(packet['artifact']['gap_audit'])
                    if mode in ('reverse', 'sequence', 'wrong_product'):
                        r['items'][0]['status'] = 'wrong_scope'
                    if mode == 'missing_review': r['items'] = []
                    if mode == 'changed_file':
                        Path(packet['output'], 'planning', 'raw-response.json').write_text('{}')
                return r
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp, \
                 patch('tradeintel_ai.development_smoke.CASES', (case,)), \
                 patch('tradeintel_ai.development_smoke.load_checklists', return_value=frozen):
                out = Path(tmp) / 'run'
                result = run_batch(config(), out, reviewer=review, reviewer_id='fixture',
                    source_kind='fixture', model_factory=lambda stage: planner(p),
                    checklist_review=True, host_gap_review=True, neutral_trade_mapping=True)
                self.assertEqual(len(result['calls']), 1)
                self.assertEqual(result['new_api_calls'], 0)
                self.assertEqual((out / 'D89-3/delivery').exists(), mode == 'accepted')
                self.assertEqual(stages, ['plan', 'answer'] if mode == 'accepted' else ['plan'])
                self.assertEqual(result['status'], 'development_review_complete' if mode == 'accepted' else 'stopped')

    def test_clarification_retains_neutral_request_without_comparison(self):
        p = dict(status='clarify', policy_question=None, policy_as_of=None, trade=None,
                 tasks=[], evidence={}, missing=['请明确贸易月份'], comparison=None,
                 policy_search_query=None,
                 request_units=[dict(quote='查询美元消费进口额', kind='request', target='trade')])
        w = self.work(p)
        preview = w.prepare('查询美元消费进口额。')
        self.assertEqual(preview['status'], 'needs_clarification')
        self.assertEqual(preview['model_request_units'], p['request_units'])
        self.assertIsNone(w._pending)
        self.assertNotIn('confirmation_token', preview)
        self.assertIsNone(preview['planner_audit']['request_unit_mapping']['derived_target'])

    def test_extra_share_is_preserved_and_missing_text_rejected(self):
        p = candidate()
        extra = '另算中国进口份额。'
        p['request_units'].append(dict(quote=extra, kind='request', target='unsupported'))
        w = self.work(p)
        preview = w.prepare(QUESTION + extra)
        self.assertEqual(preview['status'], 'needs_scope_selection')
        self.assertEqual(preview['model_request_units'], p['request_units'])
        self.assertIsNone(w._pending)
        p['request_units'].pop()
        w = self.work(p)
        self.assertEqual(w.prepare(QUESTION + extra)['status'], 'needs_review')
        self.assertIsNone(w._pending)
