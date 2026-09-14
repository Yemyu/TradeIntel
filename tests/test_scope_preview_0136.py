from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradeintel_ai.prospective_runner import default_cases, ProspectiveSyntheticRunner, fixture_review
from tradeintel_ai.prospective_acceptance import validate_structured_review
from tests.test_prospective_runner_0114 import StaticModel
from tests.test_trade_mapping_proposal_0105 import candidate


class ScopePreviewTests(unittest.TestCase):
    def test_post_validation_failure_preserves_proposal_without_approving_it(self):
        case = default_cases()[0]
        for assessment in ({'status': 'outside_declared_capability'}, RuntimeError('test-only')):
            with self.subTest(assessment=type(assessment).__name__), TemporaryDirectory() as tmp:
                model = StaticModel(candidate())
                runner = ProspectiveSyntheticRunner(Path(tmp) / 'batch', cases=[case], model_factory=lambda *_: model)
                workflow = runner._build_workflow(model, case)
                kwargs = {'side_effect': assessment} if isinstance(assessment, Exception) else {'return_value': assessment}
                with patch('tradeintel_ai.unified_research.assess_trade_request', **kwargs):
                    preview = workflow.prepare(case.question)
                self.assertEqual(preview['tasks'], ['trade'])
                self.assertFalse(preview['executed'])
                self.assertIsNone(workflow._pending)
                packet = {'preview': preview, 'checklist': [{'id': 'scope', 'kind': 'fact'}]}
                record = validate_structured_review(packet, fixture_review(packet), reviewer='test-only',
                    expected_kind='support', expected_tasks=['trade'], stage='plan')
                self.assertFalse(record['approved'])
                self.assertNotIn('tasks:missing', record['terminal']['hard_failures'])

    def test_malformed_second_response_does_not_inherit_previous_tasks(self):
        model = StaticModel(candidate())
        with TemporaryDirectory() as tmp:
            runner = ProspectiveSyntheticRunner(Path(tmp) / 'batch', model_factory=lambda *_: model)
            workflow = runner._build_workflow(model, default_cases()[0])
            self.assertEqual(workflow.prepare(default_cases()[0].question)['tasks'], ['trade'])
            model.payload = {'invalid': 'response'}
            preview = workflow.prepare(default_cases()[0].question)
            self.assertNotIn('tasks', preview)
            self.assertFalse(preview['executed'])
            self.assertIsNone(workflow._pending)

    def test_clarification_unsupported_retains_validated_empty_tasks(self):
        case = default_cases()[1]
        payload = {'status': 'clarify', 'policy_question': None, 'policy_as_of': None,
                   'trade': None, 'comparison': None, 'policy_search_query': None,
                   'tasks': [], 'evidence': {}, 'missing': ['商品', '月份', '金额口径'],
                   'request_units': [{'quote': case.question, 'kind': 'request', 'target': 'unsupported'}]}
        model = StaticModel(payload)
        with TemporaryDirectory() as tmp:
            runner = ProspectiveSyntheticRunner(Path(tmp) / 'batch', cases=[case], model_factory=lambda *_: model)
            workflow = runner._build_workflow(model, case)
            preview = workflow.prepare(case.question)
            self.assertEqual(preview['status'], 'needs_scope_selection')
            self.assertEqual(preview['tasks'], [])
            self.assertFalse(preview['executed'])
            self.assertIsNone(workflow._pending)
            packet = {'preview': preview, 'expected_kind': 'clarification', 'expected_tasks': [],
                      'checklist': [{'id': 'scope', 'kind': 'fact'}]}
            review = fixture_review(packet)
            result = validate_structured_review(packet, review, reviewer='test-only',
                expected_kind='clarification', expected_tasks=[], stage='plan')
            self.assertTrue(result['approved'])
            self.assertEqual(len(model.calls), 1)


if __name__ == '__main__':
    unittest.main()
