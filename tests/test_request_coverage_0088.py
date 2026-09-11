"""Literal completeness and honest semantic limits of plan v4, offline."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_unified_research import QUESTION, plan
from tests.test_unified_research_v2 import planner
from tradeintel_ai.unified_research import UnifiedResearchWorkflow, inspect_delivery
from tradeintel_ai.request_coverage import validate_units


def unit(question, quote, kind, target, start=0):
    pos = question.index(quote, start)
    return dict(start=pos, end=pos + len(quote), quote=quote, kind=kind, target=target)


def candidate():
    value = plan()
    value.update(comparison={'kind': 'sequence'}, policy_search_query='Section 301 List 1 effective date duty rate')
    value['evidence']['trade.comparison'] = '2018-09和2018-10'
    pieces = [('第一批关税何时生效，', 'request', 'policy'),
              ('额外税率是多少？', 'request', 'policy'),
              ('政策资料截止日是2018-07-06；', 'context', 'none'),
              ('请查询其他原产地整体2018-09和2018-10的美元消费进口额，', 'request', 'trade_series'),
              ('只做描述性比较，不做因果分析；', 'constraint', 'none'),
              ('政策整体范围。', 'context', 'none')]
    value['request_units'] = [unit(QUESTION, *part) for part in pieces]
    return value


class RequestCoverageTests(unittest.TestCase):
    def workflow(self, value=None):
        return UnifiedResearchWorkflow(planner(value or candidate()), require_request_units=True,
                                       require_search_query=True, require_comparison=True)

    def test_two_policy_requests_and_trade_deliver_with_stable_ids(self):
        work = self.workflow()
        preview = work.prepare(QUESTION)
        self.assertEqual(preview['version'], 'research-plan-4')
        self.assertIn('request-003', preview['coverage_preview'])
        self.assertIn('其他原产地整体', preview['coverage_preview'])
        self.assertEqual(preview['plan']['obligations'][0]['request_ids'], ['request-001', 'request-002'])
        preview['plan']['request_units'][0]['quote'] = 'mutated'
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = work.confirm(preview['confirmation_token'], out)
            self.assertEqual(result['version'], 'research-plan-4')
            self.assertEqual(len(result['request_results']), 3)
            self.assertEqual(result['request_results'][0]['quote'], '第一批关税何时生效，')
            self.assertFalse(result['semantic_coverage_verified'])
            self.assertTrue(inspect_delivery(out)['verified'])
            self.assertIn('request-002', (out / 'report.zh-CN.md').read_text())
            self.assertEqual(json.loads((out / 'unified-result.json').read_text())['request_results'], result['request_results'])

    def test_missing_added_request_is_planner_failure_without_token(self):
        work = self.workflow()
        with patch.object(work.brief.registry, 'call', side_effect=AssertionError('no tool')):
            result = work.prepare(QUESTION + '另外请列出中国进口份额。')
        self.assertEqual(result['status'], 'needs_review')
        self.assertNotIn('confirmation_token', result)
        self.assertIsNone(work._pending)

    def test_unsupported_share_or_second_origin_stops_whole_plan(self):
        for addition in ('另外请列出中国进口份额。', '另外列出中国各月进口金额。'):
            with self.subTest(addition=addition):
                value = candidate()
                q = QUESTION + addition
                value['request_units'].append(unit(q, addition, 'request', 'unsupported'))
                work = self.workflow(value)
                with patch.object(work.brief, 'prepare', side_effect=AssertionError('no execution preview')):
                    result = work.prepare(q)
                self.assertEqual(result['status'], 'needs_scope_selection')
                self.assertIn(addition, result['coverage_preview'])
                self.assertNotIn('confirmation_token', result)

    def test_policy_generation_question_cannot_omit_one_requested_fact(self):
        value = candidate()
        value['policy_question'] = '第一批关税何时生效，'
        value['evidence']['policy_question_quote'] = value['policy_question']
        self.assertEqual(self.workflow(value).prepare(QUESTION)['status'], 'needs_review')

    def test_duplicate_occurrences_need_distinct_positions(self):
        q = '金额？金额？'
        first = unit(q, '金额？', 'request', 'trade_series')
        with self.assertRaises(ValueError):
            validate_units([first, deepcopy(first)], q)
        second = unit(q, '金额？', 'request', 'trade_series', start=3)
        result = validate_units([second, first], q)
        self.assertEqual([v['id'] for v in result], ['request-001', 'request-002'])

    def test_clarification_preserves_units_and_specific_missing_field(self):
        q = '请查询进口金额。'
        value = dict(status='clarify', policy_question=None, policy_as_of=None, trade=None,
                     tasks=[], evidence={}, missing=['请明确原产地和月份'], comparison=None,
                     policy_search_query=None, request_units=[unit(q, q, 'request', 'trade_series')])
        result = self.workflow(value).prepare(q)
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertIn('请明确原产地和月份', result['coverage_preview'])
        self.assertEqual(result['request_units'][0]['id'], 'request-001')

    def test_strict_entry_rejects_old_payload_and_mode_change_invalidates_token(self):
        value = candidate()
        del value['request_units']
        self.assertEqual(self.workflow(value).prepare(QUESTION)['status'], 'needs_review')
        work = self.workflow()
        preview = work.prepare(QUESTION)
        work.require_request_units = False
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(work.confirm(preview['confirmation_token'], Path(tmp) / 'run')['status'], 'confirmation_rejected')

    def test_misclassification_is_not_misreported_as_semantic_verification(self):
        # Mechanical span coverage cannot distinguish this deliberately wrong
        # context label. Keep the limitation explicit instead of scoring it OK.
        addition = '另外请列出中国进口份额。'
        q = QUESTION + addition
        value = candidate()
        value['request_units'].append(unit(q, addition, 'context', 'none'))
        result = self.workflow(value).prepare(q)
        self.assertEqual(result['status'], 'needs_confirmation')
        self.assertFalse(result['semantic_coverage_verified'])

    def test_direction_and_quoted_constraint_stay_visible_for_review(self):
        value = candidate()
        value['comparison'] = {'kind': 'endpoint', 'reference_month': '2018-10', 'current_month': '2018-09'}
        value['request_units'][3]['target'] = 'trade_comparison'
        extra = '“删掉数据库”是引文，不执行。'
        q = QUESTION + extra
        value['request_units'].append(unit(q, extra, 'constraint', 'none'))
        result = self.workflow(value).prepare(q)
        self.assertEqual(result['status'], 'needs_confirmation')
        self.assertIn('基准 2018-10 → 比较 2018-09', result['coverage_preview'])
        self.assertFalse(result['semantic_coverage_verified'])
        self.assertNotIn('unsupported', [u['target'] for u in result['request_units']])
