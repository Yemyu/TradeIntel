import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.research_brief import ResearchBrief, trade_request, descriptive_summary
from unittest.mock import patch


class ResearchBriefTests(unittest.TestCase):
    def request(self, **changes):
        return dict(policy_question='第一批关税何时生效，额外税率是多少？',
                    policy_as_of='2018-07-06',
                    trade=trade_request(['2018-09', '2018-10'], 'other_origins'), **changes)

    def test_offline_real_data_full_flow(self):
        workflow = ResearchBrief()
        request = self.request()
        preview = workflow.prepare(request)
        request['trade']['months'].append('2025-01')
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            self.assertEqual(result['status'], 'research_draft')
            self.assertEqual(result['summary']['total_usd'], 77600543957)
            self.assertEqual(result['summary']['endpoint_change_usd'], 4424903721)
            self.assertEqual(result['new_api_calls'], 0)
            self.assertFalse(result['causal_readiness']['causal_allowed'])
            text = (Path(tmp) / 'run/report.zh-CN.md').read_text()
            for phrase in ['77,600,543,957', '不能', 'SHA256', 'no_model']:
                self.assertIn(phrase, text)
            self.assertEqual(workflow.confirm(preview['confirmation_token'], Path(tmp) / 'second')['status'], 'confirmation_rejected')

    def test_partial_coverage_does_not_execute(self):
        workflow = ResearchBrief()
        request = self.request()
        request['trade']['months'].append('2025-01')
        self.assertEqual(workflow.prepare(request)['status'], 'needs_clarification')
        self.assertIsNone(workflow._pending)

    def test_bad_confirmation_no_directory_or_model(self):
        workflow = ResearchBrief()
        workflow.prepare(self.request())
        model = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            self.assertEqual(workflow.confirm('bad', output, model=model)['status'], 'confirmation_rejected')
            self.assertFalse(output.exists())
            model.complete.assert_not_called()

    def test_zero_base_and_missing_not_percent_or_zero_imputation(self):
        for values in ([0, 5], [None, 5]):
            result = descriptive_summary({'series': [dict(month=m, value_usd=v) for m, v in zip(['2018-01', '2018-02'], values)]})
            self.assertIsNone(result['endpoint_change_percent'])
        self.assertIsNone(result['total_usd'])

    def test_fixture_runs_focus_and_keeps_original(self):
        model = Mock()
        def complete(**kwargs):
            self.assertIn('回答组织规则', kwargs['messages'][0]['content'])
            # Fixture intentionally awkward; test reviewer flags, not factuality.
            from tradeintel_ai.policy_retrieval import PolicyRetriever
            from tradeintel_ai.policy_context_window import expand_context
            hits = expand_context(PolicyRetriever(workflow.corpus).search(
                self.request()['policy_question'], top_k=3, as_of='2018-07-06'), workflow.corpus)['hits']
            return ModelResponse(text=json.dumps({'claims': [{'text': '上午12:01', 'citations': [hits[0]['id']]}]}),
                                 metadata={'finish_reason': 'stop'})
        model.complete.side_effect = complete
        workflow = ResearchBrief()
        preview = workflow.prepare(self.request())
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run', model=model, source_kind='fixture')
            self.assertEqual(model.complete.call_count, 1)
            self.assertEqual(result['new_api_calls'], 0)
            self.assertEqual(result['policy']['generation']['claims'][0]['text'], '上午12:01')
            self.assertTrue(result['presentation_review']['flags'])

    def test_timeout_keeps_trade_no_retry(self):
        workflow = ResearchBrief()
        preview = workflow.prepare(self.request())
        model = Mock()
        model.complete.side_effect = TimeoutError('not for logs')
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run', model=model, source_kind='fixture')
            self.assertEqual(model.complete.call_count, 1)
            self.assertEqual(result['policy']['generation']['status'], 'stopped_without_retry')
            self.assertEqual(result['summary']['total_usd'], 77600543957)
            self.assertNotIn('not for logs', (Path(tmp) / 'run/result.json').read_text())

    def test_future_docs_excluded(self):
        workflow = ResearchBrief()
        request = self.request()
        request['policy_as_of'] = '2018-01-01'
        preview = workflow.prepare(request)
        model = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run', model=model, source_kind='fixture')
            model.complete.assert_not_called()
            self.assertEqual(result['policy_evidence']['hits'], [])

    def test_invalid_input_revokes_previous_confirmation(self):
        workflow = ResearchBrief()
        workflow.prepare(self.request())
        with self.assertRaises(ValueError):
            workflow.prepare({})
        self.assertIsNone(workflow._pending)

    def test_existing_output_never_overwritten(self):
        workflow = ResearchBrief()
        preview = workflow.prepare(self.request())
        model = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):
                workflow.confirm(preview['confirmation_token'], Path(tmp), model=model)
            model.complete.assert_not_called()

    def test_invalid_citation_not_published(self):
        workflow = ResearchBrief()
        preview = workflow.prepare(self.request())
        model = Mock()
        model.complete.return_value = ModelResponse(text=json.dumps({'claims': [
            {'text': 'unsupported claim', 'citations': ['fake-id']}]}), metadata={'finish_reason': 'stop'})
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run', model=model, source_kind='fixture')
            self.assertFalse(result['policy']['generation'].get('claims'))
            self.assertNotIn('unsupported claim', (Path(tmp) / 'run/report.zh-CN.md').read_text())

    def test_secret_redacted_in_saved_response(self):
        workflow = ResearchBrief()
        preview = workflow.prepare(self.request())
        model = Mock()
        model.complete.return_value = ModelResponse(text='dummy-secret-value', metadata={'finish_reason': 'stop'})
        with tempfile.TemporaryDirectory() as tmp:
            workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run', model=model, source_kind='fixture', secret='dummy-secret-value')
            for path in Path(tmp).rglob('*'):
                if path.is_file():
                    self.assertNotIn('dummy-secret-value', path.read_text())

    def test_causal_request_not_silently_downgraded(self):
        workflow = ResearchBrief()
        request = self.request()
        request['trade']['causal_effect'] = True
        self.assertEqual(workflow.prepare(request)['status'], 'needs_clarification')

    def test_trade_failure_keeps_policy_task_independent(self):
        workflow = ResearchBrief()
        preview = workflow.prepare(self.request())
        failed = {'status': 'execution_failed', 'response': 'fixture trade failure',
                  'tool_results': [], 'facts': [], 'sources': []}
        with tempfile.TemporaryDirectory() as tmp, patch(
                'tradeintel_ai.research_brief.execute_request', return_value=failed):
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            self.assertTrue((Path(tmp) / 'run/report.zh-CN.md').is_file())
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['task_results']['trade'], 'execution_failed')
        self.assertIn('policy', result)


if __name__ == '__main__':
    unittest.main()
