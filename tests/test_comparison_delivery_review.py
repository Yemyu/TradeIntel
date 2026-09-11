"""Boundary regressions for comparison delivery, using offline model fixtures."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_unified_research import QUESTION, plan
from tests.test_unified_research_v2 import planner
from tradeintel_ai.unified_research import UnifiedResearchWorkflow


class ComparisonDeliveryReview(unittest.TestCase):
    def test_strict_entry_rejects_model_chosen_legacy(self):
        work = UnifiedResearchWorkflow(planner(plan()), require_comparison=True)
        self.assertEqual(work.prepare(QUESTION)['status'], 'needs_review')
        self.assertIsNone(work._pending)

    def test_host_mode_change_invalidates_confirmation(self):
        work = UnifiedResearchWorkflow(planner(plan()))
        preview = work.prepare(QUESTION)
        work.require_comparison = True
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            self.assertEqual(work.confirm(preview['confirmation_token'], output)['status'],
                             'confirmation_rejected')
            self.assertFalse(output.exists())

    def test_missing_amount_produces_reports_in_both_paths(self):
        for tasks in (['trade'], ['policy', 'trade']):
            with self.subTest(tasks=tasks):
                payload = plan()
                payload['tasks'] = tasks
                if tasks == ['trade']:
                    payload['policy_question'] = payload['policy_as_of'] = None
                    payload['evidence'] = {k: v for k, v in payload['evidence'].items()
                                           if k.startswith('trade.')}
                phrase = '2018-10相对2018-09的变化'
                payload['comparison'] = {'kind': 'endpoint', 'reference_month': '2018-09',
                                         'current_month': '2018-10'}
                payload['evidence']['trade.comparison'] = phrase
                work = UnifiedResearchWorkflow(planner(payload), require_comparison=True)
                preview = work.prepare(QUESTION + phrase)
                self.assertEqual(preview['status'], 'needs_confirmation')
                # Exercise delivery with an incomplete but already validated tool result.
                trade = {'status': 'evidence_ready', 'sources': {}, 'tool_results': [
                    {'tool_name': 'get_trade_series', 'data': {
                        'requested_months': ['2018-09', '2018-10'], 'hs6': None,
                        'series': [{'month': '2018-09', 'value_usd': None},
                                   {'month': '2018-10', 'value_usd': 80}]}},
                    {'tool_name': 'get_causal_readiness', 'data': {'status': 'blocked'}}]}
                target = ('tradeintel_ai.unified_research.execute_request' if tasks == ['trade']
                          else 'tradeintel_ai.research_brief.execute_request')
                with tempfile.TemporaryDirectory() as tmp, patch(target, return_value=trade):
                    output = Path(tmp) / 'run'
                    result = work.confirm(preview['confirmation_token'], output)
                    comparison = result['summary']['comparison']
                    self.assertEqual(comparison['status'], 'incomplete')
                    self.assertIsNone(comparison['change_usd'])
                    statuses = {v['id']: v['status'] for v in result['obligations']}
                    self.assertEqual(statuses['trade_comparison'], 'incomplete')
                    report = (output / 'report.zh-CN.md').read_text()
                    self.assertIn('比较所需金额缺失', report)
                    self.assertNotIn('基准为零', report)
                    saved = json.loads((output / 'unified-result.json').read_text())
                    self.assertEqual(saved['summary']['comparison'], comparison)


if __name__ == '__main__':
    unittest.main()
