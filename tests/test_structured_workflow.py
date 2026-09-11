from copy import deepcopy
import unittest

from src.tradeintel_ai.evidence_v21 import EvidenceRegistryV21
from src.tradeintel_ai.structured_workflow import execute_request


def trade(**changes):
    fields = dict(policy_id='us_301_list1_2018', operation='read',
                  metric='import_value_consumption_usd', origin='China',
                  granularity='policy_aggregate', months=['2016-04', '2018-09'],
                  hs6=None, causal_effect=False)
    fields.update(changes)
    return {'task': 'trade', 'request': fields}


class BrokenRegistry(EvidenceRegistryV21):
    def __init__(self, mutation):
        super().__init__()
        self.mutation = mutation

    def call(self, name, args):
        result = deepcopy(super().call(name, args))
        if name == 'get_trade_series':
            self.mutation(result)
        return result


class StructuredWorkflowTests(unittest.TestCase):
    def test_exact_discrete_trade_and_honest_attribution(self):
        req = trade(); original = deepcopy(req)
        r = execute_request(req)
        self.assertEqual(r['status'], 'evidence_ready')
        self.assertEqual(req, original)
        self.assertEqual(r['host_selected_tools'], ['get_trade_series', 'get_causal_readiness'])
        self.assertEqual(r['model_selected_tools'], [])
        self.assertFalse(r['intent_verified'])
        self.assertFalse(r['task_success_verified'])
        self.assertEqual(r['model_calls'], 0)
        self.assertIn('所列请求月份合计', r['response'])
        self.assertNotIn('本次查询完整窗口合计', r['response'])

    def test_counts_fetches_both_sources(self):
        r = execute_request({'task': 'counts'})
        self.assertEqual(r['status'], 'evidence_ready')
        self.assertEqual(r['host_selected_tools'], ['get_policy_event', 'get_causal_readiness'])
        for label in ('政策清单商品数量', '合格处理商品分母', '至少有两个对照的处理商品数', '三个计数为何不能混用'):
            self.assertIn(label, r['response'])

    def test_readiness_does_not_overfetch(self):
        r = execute_request({'task': 'readiness'})
        self.assertEqual(r['status'], 'evidence_ready')
        self.assertEqual(r['host_selected_tools'], ['get_causal_readiness'])

    def test_refusals_are_visible_without_trade_calls(self):
        for change, text in (({'origin': 'Germany'}, '单独国家'),
                             ({'granularity': 'company'}, '企业'),
                             ({'operation': 'delete'}, '只读'),
                             ({'metric': 'GDP'}, 'GDP'),
                             ({'causal_effect': True}, '因果')):
            with self.subTest(change=change):
                r = execute_request(trade(**change))
                self.assertEqual(r['status'], 'refused')
                self.assertIn(text, r['response'])
                self.assertEqual(r['tool_results'], [])
                self.assertTrue(r['sources'])

    def test_all_outside_has_no_fake_observed_zero(self):
        r = execute_request(trade(months=['2012-03', '2024-11']))
        self.assertEqual(r['status'], 'refused')
        self.assertIn('没有查询金额', r['response'])
        self.assertNotIn('已返回其余', r['response'])
        self.assertNotIn('：0 美元', r['response'])

    def test_partial_missing_retains_null(self):
        r = execute_request(trade(months=['2012-03', '2018-09']))
        self.assertEqual(r['status'], 'evidence_ready')
        self.assertIn('已取得月份：2018-09', r['response'])
        self.assertIsNone(next(f['value'] for f in r['facts'] if f['label']=='2012-03 / China 进口额'))

    def test_unknown_fields_and_tasks_not_silently_ignored(self):
        for req in ({}, '帮我查询', {'task': 'readiness', 'sql': 'DELETE'},
                    {'task': 'unknown'}, trade(extra='ignore this'),
                    {'task': 'comparison', 'comparison_id': []}):
            self.assertEqual(execute_request(req)['status'], 'needs_clarification')

    def test_wrong_returned_scope_fails_closed(self):
        for mutation in (lambda r: r['data'].update(origin='all_origins'),
                         lambda r: r['data'].update(requested_months=['2016-04']),
                         lambda r: r['data']['series'].append(deepcopy(r['data']['series'][0])),
                         lambda r: r.update(tool_name='get_policy_event')):
            r = execute_request(trade(), BrokenRegistry(mutation))
            self.assertEqual(r['status'], 'execution_failed')
            self.assertNotIn(' / China 进口额', r['response'])

    def test_failed_or_malformed_tool_has_visible_error(self):
        for mutation in (lambda r: r.update(status='error'), lambda r: r.pop('data')):
            r = execute_request(trade(), BrokenRegistry(mutation))
            self.assertEqual(r['status'], 'execution_failed')
            self.assertTrue(r['response'])

    def test_bad_totals_or_amount_types_fail_closed(self):
        for mutation in (lambda r: r['data'].update(total_usd=1),
                         lambda r: r['data']['series'][0].update(value_usd=True),
                         lambda r: r['data'].update(missing_months=['2016-04'])):
            self.assertEqual(execute_request(trade(), BrokenRegistry(mutation))['status'], 'execution_failed')

    def test_registered_comparison_and_other_tasks(self):
        r = execute_request({'task': 'comparison', 'comparison_id': 'immediate_post_same_months'})
        self.assertEqual(r['status'], 'evidence_ready')
        self.assertNotIn('get_trade_series', r['host_selected_tools'])
        for task in ('quality', 'policy'):
            self.assertEqual(execute_request({'task': task})['status'], 'evidence_ready')


if __name__ == '__main__':
    unittest.main()
