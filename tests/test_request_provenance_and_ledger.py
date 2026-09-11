"""Request/source coverage, retrieval bridge and model-call ledger checks."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.policy_retrieval import PolicyRetriever, validate_search_query
from tradeintel_ai.policy_workflow import load_frozen_corpus
from tradeintel_ai.unified_research import UnifiedResearchWorkflow
from tests.test_unified_research import QUESTION, plan
from tests.test_unified_research_v2 import planner


ROOT = Path(__file__).resolve().parents[1]


class RequestProvenanceAndLedgerTests(unittest.TestCase):
    def v3_plan(self):
        payload = plan()
        payload['comparison'] = {'kind': 'endpoint', 'reference_month': '2018-09',
                                'current_month': '2018-10'}
        payload['evidence']['trade.comparison'] = '2018-09和2018-10的美元消费进口额'
        payload['policy_search_query'] = (
            'initial Section 301 List 1 effective date additional duty rate')
        return payload

    def test_search_bridge_is_recorded_but_original_question_stays_primary(self):
        corpus = load_frozen_corpus(ROOT)
        result = PolicyRetriever(corpus).search(
            '第一批关税何时生效，额外税率是多少？',
            as_of='2018-07-06',
            search_query='initial Section 301 List 1 effective date additional duty rate')
        self.assertEqual(result['question'], '第一批关税何时生效，额外税率是多少？')
        self.assertEqual(result['search_query'],
                         'initial Section 301 List 1 effective date additional duty rate')
        self.assertTrue(result['hits'])

    def test_search_bridge_is_short_english_and_rejects_other_values(self):
        self.assertEqual(validate_search_query('Section 301 effective date'),
                         'Section 301 effective date')
        for bad in ('', '中文检索', 'x' * 241, 'line\nfeed'):
            with self.assertRaises(ValueError):
                validate_search_query(bad)

    def test_strict_entry_rejects_legacy_policy_plan_without_bridge(self):
        payload = plan()
        payload['comparison'] = {'kind': 'sequence'}
        payload['evidence']['trade.comparison'] = '2018-09和2018-10的美元消费进口额'
        workflow = UnifiedResearchWorkflow(
            planner(payload), require_comparison=True, require_search_query=True)
        result = workflow.prepare(QUESTION)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['diagnostic']['category'], 'adapter_or_response_error')

    def test_v3_plan_has_stable_task_ids_and_secret_free_ledger(self):
        payload = self.v3_plan()
        workflow = UnifiedResearchWorkflow(planner(payload))
        preview = workflow.prepare(QUESTION)
        self.assertEqual(preview['status'], 'needs_confirmation')
        self.assertEqual(preview['version'], 'research-plan-3')
        self.assertEqual(preview['task_ids'],
                         ['policy_question', 'trade_series', 'trade_comparison'])

        answer_model = Mock()

        def answer(**kwargs):
            context = json.loads(kwargs['messages'][1]['content'])
            return ModelResponse(text=json.dumps({'claims': [{
                'text': '第一批公告正文提供了历史政策信息。',
                'citations': [context['evidence'][0]['id']],
            }]}), metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 9}})

        answer_model.complete.side_effect = answer
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            result = workflow.confirm(preview['confirmation_token'], output,
                                      model=answer_model, source_kind='fixture',
                                      secret='fixture-secret')
            ledger = json.loads((output / 'model-call-ledger.json').read_text())
            saved_plan = json.loads((output / 'research-plan.json').read_text())
            attempt = json.loads((output / 'policy-attempt' / 'attempt.json').read_text())
            self.assertEqual(saved_plan['task_ids'], preview['task_ids'])
            self.assertEqual([entry['stage'] for entry in ledger],
                             ['planning', 'policy_generation'])
            self.assertEqual(result['model_calls_total'], 2)
            self.assertEqual(result['new_api_calls_total'], 0)
            self.assertEqual(ledger[1]['attempt_id'], attempt['attempt_id'])
            self.assertNotIn('raw_response', json.dumps(ledger))
            self.assertNotIn('fixture-secret', (output / 'unified-result.json').read_text())
            self.assertIn('检索桥接表达', (output / 'report.zh-CN.md').read_text())


if __name__ == '__main__':
    unittest.main()
