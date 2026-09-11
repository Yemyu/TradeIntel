"""Budget/configuration snapshots and durable delivery markers."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_unified_research import QUESTION, plan
from tests.test_unified_research_v2 import planner, policy_plan
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.unified_research import UnifiedResearchWorkflow


class DeliveryStatus0086Tests(unittest.TestCase):
    def test_completed_run_records_budget_configuration_and_intent(self):
        workflow = UnifiedResearchWorkflow(planner(plan()))
        preview = workflow.prepare(QUESTION)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            result = workflow.confirm(preview['confirmation_token'], output)
            marker = json.loads((output / 'delivery-status.json').read_text())
            intent = json.loads((Path(tmp) / 'run.delivery-intent.json').read_text())

        self.assertEqual(marker['status'], 'complete')
        self.assertEqual(marker['missing_files'], [])
        self.assertEqual(marker['execution_status'], 'research_draft')
        self.assertEqual(marker['budget']['total_max_calls'], 2)
        self.assertFalse(marker['configuration']['planning']['api_key_recorded'])
        self.assertEqual(intent['status'], 'complete')
        self.assertEqual(result['delivery_status']['status'], 'complete')
        self.assertTrue(result['budget_check']['within_limits'])

    def test_fixture_answer_configuration_is_recorded_without_secret(self):
        workflow = UnifiedResearchWorkflow(planner(policy_plan()))
        preview = workflow.prepare(QUESTION)
        answer = Mock()
        def complete(**kwargs):
            context = json.loads(kwargs['messages'][1]['content'])
            return ModelResponse(
                text=json.dumps({'claims': [{
                    'text': '第一批公告正文提供了历史政策信息。',
                    'citations': [context['evidence'][0]['id']],
                }]}),
                metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 7}},
            )
        answer.complete.side_effect = complete
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            result = workflow.confirm(preview['confirmation_token'], output,
                                      model=answer, source_kind='fixture',
                                      secret='fixture-secret')
            saved = (output / 'unified-result.json').read_text()

        self.assertEqual(result['configuration']['policy_generation']['source_kind'], 'fixture')
        self.assertEqual(result['model_calls_total'], 2)
        self.assertNotIn('fixture-secret', saved)
        self.assertEqual(result['delivery_status']['status'], 'complete')

    def test_interrupt_writes_marker_and_does_not_retry(self):
        workflow = UnifiedResearchWorkflow(planner(plan()))
        preview = workflow.prepare(QUESTION)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            with patch('tradeintel_ai.research_brief.execute_request',
                       side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    workflow.confirm(preview['confirmation_token'], output)
            marker = json.loads((output / 'delivery-status.json').read_text())
            intent = json.loads((Path(tmp) / 'run.delivery-intent.json').read_text())

        self.assertEqual(marker['status'], 'interrupted')
        self.assertTrue(marker['interrupted'])
        self.assertIn('result.json', marker['missing_files'])
        self.assertEqual(intent['status'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
