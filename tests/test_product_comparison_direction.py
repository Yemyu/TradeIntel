import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.comparison_direction import check_endpoint_direction, ComparisonDirectionError
from tradeintel_ai.unified_research import build_product_workflow


def proposal(quote, reference='2018-10', current='2018-09'):
    question = '第一批关税政策整体范围，其他原产地整体的美元消费进口额：' + quote + '；只做描述性分析。'
    payload = {
        'status': 'plan', 'policy_question': None, 'policy_as_of': None,
        'policy_search_query': None, 'tasks': ['trade'], 'missing': [],
        'trade': {'policy_id': 'us_301_list1_2018', 'operation': 'read',
                  'metric': 'import_value_consumption_usd', 'origin': 'other_origins',
                  'granularity': 'policy_aggregate', 'months': ['2018-09', '2018-10'],
                  'hs6': None, 'causal_effect': False},
        'comparison': {'kind': 'endpoint', 'reference_month': reference, 'current_month': current},
        'evidence': {'trade.comparison': quote, 'trade.months': quote,
                     'trade.granularity': '整体范围', 'trade.hs6': '整体范围',
                     'trade.origin': '其他原产地整体', 'trade.metric': '美元消费进口额'},
        'request_units': [{'quote': question, 'kind': 'request', 'target': 'trade'}],
    }
    return payload, question


class ProductDirectionTests(unittest.TestCase):
    def preview(self, payload, question):
        model = Mock()
        model.complete.return_value = ModelResponse(text=json.dumps(payload, ensure_ascii=False),
                                                    metadata={'finish_reason': 'stop'})
        workflow = build_product_workflow(model)
        result = workflow.prepare(question)
        model.complete.assert_called_once()
        return workflow, result

    def test_supported_directions_reach_confirmation_without_mutating_input(self):
        for ref, cur in [('2018-10', '2018-09'), ('2018-09', '2018-10')]:
            for quote in [f'以{ref}为基准，比较{cur}', f'{cur}相对于{ref}', f'{cur}比{ref}', f'比较{cur}相对于{ref}']:
                with self.subTest(quote=quote):
                    payload, question = proposal(quote, ref, cur)
                    original = copy.deepcopy(payload)
                    _, result = self.preview(payload, question)
                    self.assertEqual(result['status'], 'needs_confirmation')
                    self.assertFalse(result['executed'])
                    self.assertEqual(payload, original)

    def test_reversed_proposal_stopped_even_with_literal_evidence(self):
        payload, question = proposal('以2018-10为基准，比较2018-09', '2018-09', '2018-10')
        workflow, result = self.preview(payload, question)
        self.assertEqual(result['status'], 'needs_review')
        self.assertIn('与原话不一致', result['response'])
        self.assertIsNone(workflow._pending)
        self.assertFalse(result['executed'])
        self.assertNotIn('confirmation_token', result)

    def test_fabricated_month_quote_stays_blocked(self):
        payload, question = proposal('以2018-10为基准，比较2018-09', '2018-09', '2018-10')
        payload['evidence']['trade.months'] = '2018-09，2018-10'
        _, result = self.preview(payload, question)
        self.assertIn('不是你的连续原话', result['response'])
        self.assertFalse(result['executed'])

    def test_ambiguous_or_negated_or_conflicting_language_stops(self):
        for quote in ['比较2018-09和2018-10', '2018-09至2018-10']:
            payload, question = proposal(quote)
            with self.assertRaises(ComparisonDirectionError):
                check_endpoint_direction(payload, question)
        payload, question = proposal('以2018-10为基准，比较2018-09')
        for suffix in ['不要这样比较', '；2018-10相对于2018-09', '这只是示例', '不以该月为基准']:
            with self.assertRaises(ComparisonDirectionError):
                check_endpoint_direction(payload, question + suffix)

    def test_sequence_is_unchanged(self):
        payload, question = proposal('2018-09和2018-10逐月列数')
        payload['comparison'] = {'kind': 'sequence'}
        _, result = self.preview(payload, question)
        self.assertEqual(result['status'], 'needs_confirmation')

    def test_correct_reverse_plan_produces_negative_change_after_confirmation(self):
        payload, question = proposal('以2018-10为基准，比较2018-09')
        workflow, preview = self.preview(payload, question)
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / 'delivery'
            workflow.confirm(preview['confirmation_token'], output)
            report = (output / 'report.zh-CN.md').read_text()
            self.assertIn('-4,424,903,721', report)
            self.assertIn('-10.79%', report)
