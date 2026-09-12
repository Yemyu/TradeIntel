"""Integration tests for the opt-in host-gap review gate."""
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_unified_research import plan
from tests.test_unified_research_v2 import planner
from tradeintel_ai.quote_gap_audit import digest_audit
from tradeintel_ai.unified_research import UnifiedResearchWorkflow


QUESTION = ('第一批关税何时生效，额外税率是多少？政策资料截止日是2018-07-06；'
            '请查询其他原产地整体2018-09和2018-10的美元消费进口额，只做描述性比较，不做因果分析；'
            '政策整体范围。')


def gap_plan():
    value = plan()
    value.update(comparison={'kind': 'sequence'},
                 policy_search_query='Section 301 List 1 effective date additional duty rate')
    value['evidence']['trade.comparison'] = '2018-09和2018-10'
    # Deliberately omit only the four ordinary separators. The host must not
    # turn this into a successful strict plan without an explicit review.
    value['request_units'] = [
        {'quote': '第一批关税何时生效，额外税率是多少？', 'kind': 'request', 'target': 'policy'},
        {'quote': '政策资料截止日是2018-07-06', 'kind': 'constraint', 'target': 'none'},
        {'quote': '请查询其他原产地整体2018-09和2018-10的美元消费进口额',
         'kind': 'request', 'target': 'trade_series'},
        {'quote': '只做描述性比较，不做因果分析', 'kind': 'constraint', 'target': 'none'},
        {'quote': '政策整体范围', 'kind': 'context', 'target': 'none'},
    ]
    return value


class HostGapWorkflowTests(unittest.TestCase):
    def test_strict_default_still_rejects_and_does_not_issue_token(self):
        work = UnifiedResearchWorkflow(planner(gap_plan()), require_request_units=True,
                                       derive_request_offsets=True, require_comparison=True,
                                       require_search_query=True)
        result = work.prepare(QUESTION)
        self.assertEqual(result['status'], 'needs_review')
        self.assertNotIn('confirmation_token', result)
        self.assertIsNone(work._pending)

    def test_opt_in_gap_mode_requires_a_separate_review_before_confirmation(self):
        work = UnifiedResearchWorkflow(planner(gap_plan()), require_request_units=True,
                                       derive_request_offsets=True, require_comparison=True,
                                       require_search_query=True, allow_host_gap_review=True)
        result = work.prepare(QUESTION)
        self.assertEqual(result['status'], 'needs_gap_review')
        self.assertNotIn('confirmation_token', result)
        self.assertIn('gap_review_token', result)
        self.assertEqual(result['gap_audit']['status'], 'review_required')
        self.assertFalse(result['gap_audit']['executable'])
        self.assertFalse(result['gap_audit']['semantic_coverage_verified'])
        self.assertEqual([g['quote'] for g in result['gap_audit']['segments']
                          if g['source'] == 'host_gap' and g['quote'].strip()], ['；', '，', '；', '。'])
        self.assertEqual(''.join(s['quote'] for s in result['gap_audit']['segments']), QUESTION)
        self.assertEqual(work.confirm(result['gap_review_token'], Path('/unused'))['status'],
                         'confirmation_rejected')

    def test_reviewer_decision_issues_new_token_and_writes_gap_artifact(self):
        work = UnifiedResearchWorkflow(planner(gap_plan()), require_request_units=True,
                                       derive_request_offsets=True, require_comparison=True,
                                       require_search_query=True, allow_host_gap_review=True)
        preview = work.prepare(QUESTION)
        audit = preview['gap_audit']
        gaps = [g for g in audit['segments'] if g['source'] == 'host_gap' and g['quote'].strip()]
        submission = {
            'audit_sha256': digest_audit(audit), 'reviewer': 'offline-reviewer',
            'overall': {'status': 'pass', 'reason': '逐项确认均为句间普通分隔符，不替代语义审查。'},
            'gaps': [{'start': g['start'], 'end': g['end'], 'quote': g['quote'],
                      'status': 'accepted_separator', 'reason': '该字符位于两个已核对片段之间。'}
                     for g in gaps],
        }
        approved = work.approve_gap_review(preview['gap_review_token'], submission)
        self.assertEqual(approved['status'], 'needs_confirmation')
        self.assertIn('confirmation_token', approved)
        self.assertNotEqual(approved['confirmation_token'], preview.get('confirmation_token'))
        self.assertTrue(approved['plan']['gap_review_approved'])
        self.assertFalse(approved['plan']['semantic_coverage_verified'])
        with tempfile.TemporaryDirectory() as tmp:
            result = work.confirm(approved['confirmation_token'], Path(tmp) / 'run')
            self.assertEqual(result['status'], 'research_draft')
            self.assertTrue((Path(tmp) / 'run' / 'gap-review.json').is_file())
            saved = json.loads((Path(tmp) / 'run' / 'gap-review.json').read_text())
            self.assertTrue(saved['approved'])
            self.assertFalse(result['semantic_coverage_verified'])

    def test_failed_gap_review_invalidates_plan_without_execution(self):
        work = UnifiedResearchWorkflow(planner(gap_plan()), require_request_units=True,
                                       derive_request_offsets=True, require_comparison=True,
                                       require_search_query=True, allow_host_gap_review=True)
        preview = work.prepare(QUESTION)
        gaps = [g for g in preview['gap_audit']['segments']
                if g['source'] == 'host_gap' and g['quote'].strip()]
        submission = {
            'audit_sha256': digest_audit(preview['gap_audit']), 'reviewer': 'offline-reviewer',
            'overall': {'status': 'fail', 'reason': '最后一个分隔符需要重新确认。'},
            'gaps': [{'start': g['start'], 'end': g['end'], 'quote': g['quote'],
                      'status': 'accepted_separator' if i < len(gaps) - 1 else 'rejected',
                      'reason': '前面是普通分隔符。' if i < len(gaps) - 1 else '拒绝自动补存。'}
                     for i, g in enumerate(gaps)],
        }
        result = work.approve_gap_review(preview['gap_review_token'], submission)
        self.assertEqual(result['status'], 'gap_review_rejected')
        self.assertNotIn('confirmation_token', result)
        self.assertIsNone(work._pending)

    def test_complete_quotes_do_not_create_a_gap_gate(self):
        value = gap_plan()
        value['request_units'] = [
            {'quote': '第一批关税何时生效，额外税率是多少？', 'kind': 'request', 'target': 'policy'},
            {'quote': '政策资料截止日是2018-07-06；', 'kind': 'constraint', 'target': 'none'},
            {'quote': '请查询其他原产地整体2018-09和2018-10的美元消费进口额，',
             'kind': 'request', 'target': 'trade_series'},
            {'quote': '只做描述性比较，不做因果分析；', 'kind': 'constraint', 'target': 'none'},
            {'quote': '政策整体范围。', 'kind': 'context', 'target': 'none'},
        ]
        work = UnifiedResearchWorkflow(planner(value), require_request_units=True,
                                       derive_request_offsets=True, require_comparison=True,
                                       require_search_query=True, allow_host_gap_review=True)
        result = work.prepare(QUESTION)
        self.assertEqual(result['status'], 'needs_confirmation')
        self.assertNotIn('gap_review_token', result)
        self.assertIn('confirmation_token', result)


if __name__ == '__main__':
    unittest.main()
