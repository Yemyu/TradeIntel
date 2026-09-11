"""Candidate comparison arithmetic; offline, not model accuracy tests."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock

from tradeintel_ai.research_comparison import resolve, calculate
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.research_brief import ResearchBrief
from tradeintel_ai.unified_research import UnifiedResearchWorkflow
from tests.test_unified_research import QUESTION, plan


class ComparisonTests(unittest.TestCase):
    def trade(self, months=None):
        return {'months': months or ['2018-09', '2018-10'],
                'granularity': 'policy_aggregate', 'hs6': None}

    def series(self, a=100, b=80):
        return [{'month': '2018-10', 'value_usd': b},
                {'month': '2018-09', 'value_usd': a}]

    def endpoint(self, **kwargs):
        return resolve({'kind': 'endpoint', 'reference_month': '2018-09',
                        'current_month': '2018-10', **kwargs}, self.trade())

    def test_sequence_does_not_invent_comparison(self):
        result = calculate(resolve({'kind': 'sequence'}, self.trade()), self.series())
        self.assertNotIn('change_usd', result)
        self.assertEqual(result['series'][0]['month'], '2018-09')

    def test_direction_is_not_chronological_sort(self):
        self.assertEqual(calculate(self.endpoint(), self.series())['change_percent'], '-20.00')
        reverse = self.endpoint(reference_month='2018-10', current_month='2018-09')
        self.assertEqual(calculate(reverse, self.series())['change_percent'], '25.00')

    def test_missing_does_not_become_zero(self):
        result = calculate(self.endpoint(), self.series(b=None))
        self.assertEqual(result['status'], 'incomplete')
        self.assertIsNone(result['change_usd'])

    def test_zero_reference_has_no_growth_rate(self):
        result = calculate(self.endpoint(), self.series(a=0))
        self.assertEqual(result['change_usd'], 80)
        self.assertIsNone(result['change_percent'])

    def test_large_integer_difference_is_exact(self):
        result = calculate(self.endpoint(), self.series(a=10**18, b=10**18+1))
        self.assertEqual(result['change_usd'], 1)

    def test_ambiguous_or_outside_comparison_is_rejected(self):
        for spec in ({'kind': 'compare'}, {'kind': 'endpoint'},
                     {'kind': 'sequence', 'reference_month': '2018-09'}):
            with self.assertRaises(ValueError):
                resolve(spec, self.trade())
        with self.assertRaises(ValueError):
            self.endpoint(current_month='2019-10')

    def test_duplicate_float_or_extra_rows_rejected(self):
        for rows in (self.series()+self.series(), self.series(a=1.1), self.series(a=True),
                     self.series()+[{'month': '2018-11', 'value_usd': 1}]):
            with self.assertRaises(ValueError):
                calculate(self.endpoint(), rows)

    def test_registered_windows_cannot_replace_scope(self):
        cid = 'immediate_post_same_months'
        spec = {'kind': 'registered', 'comparison_id': cid}
        windows = {cid: {'reference_months': ['2017-08'], 'current_months': ['2018-08']}}
        trade = self.trade(['2017-08', '2018-08'])
        contract = resolve(spec, trade, registered_windows=windows)
        self.assertFalse(contract['causal_effect_estimated'])
        for bad in (self.trade(), {**trade, 'granularity': 'hs6', 'hs6': '123456'}):
            with self.assertRaises(ValueError):
                resolve(spec, bad, registered_windows=windows)
        with self.assertRaises(ValueError):
            resolve(spec, trade)
        windows[cid]['current_months'] = ['2018-09']
        with self.assertRaises(ValueError):
            resolve(spec, trade, registered_windows=windows)

    def test_ready_data_is_not_automatically_complete(self):
        state = UnifiedResearchWorkflow._obligation_status
        self.assertEqual(state('trade', {'trade': {'status': 'evidence_ready'},
                                        'summary': {'complete': False}}), 'incomplete')
        self.assertEqual(state('policy', {'policy': {'generation': {'status': 'not_requested'}}}),
                         'not_executed')

    def test_real_registered_windows_are_host_loaded_and_calculated(self):
        trade = self.trade(['2017-08', '2017-09', '2017-10', '2017-11', '2017-12',
                            '2018-08', '2018-09', '2018-10', '2018-11', '2018-12'])
        windows = {
            'immediate_post_same_months': {
                'reference_months': ['2017-08', '2017-09', '2017-10', '2017-11', '2017-12'],
                'current_months': ['2018-08', '2018-09', '2018-10', '2018-11', '2018-12'],
            }
        }
        contract = resolve({'kind': 'registered',
                            'comparison_id': 'immediate_post_same_months'},
                           trade, registered_windows=windows)
        values = [{'month': month, 'value_usd': 1} for month in trade['months']]
        result = calculate(contract, values)
        self.assertEqual(result['reference_total_usd'], 5)
        self.assertEqual(result['current_total_usd'], 5)
        self.assertEqual(result['change_percent'], '0.00')

    def test_v2_plan_reaches_report_with_explicit_endpoint(self):
        payload = plan()
        payload['comparison'] = {'kind': 'endpoint', 'reference_month': '2018-09',
                                'current_month': '2018-10'}
        payload['evidence']['trade.comparison'] = '2018-09和2018-10'
        model = Mock()
        model.complete.return_value = ModelResponse(
            text=json.dumps(payload, ensure_ascii=False),
            metadata={'finish_reason': 'stop'})
        workflow = UnifiedResearchWorkflow(model)
        preview = workflow.prepare(QUESTION)
        self.assertEqual(preview['status'], 'needs_confirmation')
        self.assertEqual(preview['version'], 'research-plan-2')
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            comparison = result['summary']['comparison']
            self.assertEqual(comparison['reference_months'], ['2018-09'])
            self.assertEqual(comparison['current_months'], ['2018-10'])
            self.assertEqual(comparison['change_usd'], 4424903721)
            self.assertEqual({item['id']: item['status'] for item in result['obligations']},
                             {'policy_question': 'not_executed', 'trade_series': 'completed',
                              'trade_comparison': 'completed'})
            report = (Path(tmp) / 'run/report.zh-CN.md').read_text()
            self.assertIn('明确比较：2018-10 相对 2018-09', report)

    def test_sequence_v2_does_not_render_endpoint_change(self):
        payload = plan()
        payload['comparison'] = {'kind': 'sequence'}
        payload['evidence']['trade.comparison'] = '2018-09和2018-10'
        model = Mock()
        model.complete.return_value = ModelResponse(
            text=json.dumps(payload, ensure_ascii=False),
            metadata={'finish_reason': 'stop'})
        workflow = UnifiedResearchWorkflow(model)
        preview = workflow.prepare(QUESTION)
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            self.assertIsNone(result['summary']['endpoint_change_usd'])
            self.assertIn('没有自动把首末月份相减',
                          (Path(tmp) / 'run/report.zh-CN.md').read_text())

    def test_registered_v2_uses_exact_local_windows(self):
        months = ['2017-08', '2017-09', '2017-10', '2017-11', '2017-12',
                  '2018-08', '2018-09', '2018-10', '2018-11', '2018-12']
        payload = plan()
        payload['trade']['months'] = months
        payload['comparison'] = {'kind': 'registered',
                                 'comparison_id': 'immediate_post_same_months'}
        payload['evidence']['trade.months'] = '2017-08到2017-12以及2018-08到2018-12'
        payload['evidence']['trade.comparison'] = '2017-08到2017-12以及2018-08到2018-12'
        question = QUESTION + '窗口为2017-08到2017-12以及2018-08到2018-12。'
        model = Mock()
        model.complete.return_value = ModelResponse(
            text=json.dumps(payload, ensure_ascii=False),
            metadata={'finish_reason': 'stop'})
        workflow = UnifiedResearchWorkflow(model)
        preview = workflow.prepare(question)
        self.assertEqual(preview['status'], 'needs_confirmation')
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            comparison = result['summary']['comparison']
            self.assertEqual(comparison['kind'], 'registered')
            self.assertEqual(comparison['reference_months'], months[:5])
            self.assertEqual(comparison['current_months'], months[5:])
            self.assertIn('登记同期窗口',
                          (Path(tmp) / 'run/report.zh-CN.md').read_text())


if __name__ == '__main__':
    unittest.main()
