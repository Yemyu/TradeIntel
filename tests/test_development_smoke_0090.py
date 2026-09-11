"""Budget and review boundaries: fixtures only, no HTTP requests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.development_smoke import (CASES, CallLedger, SmokeStopped,
                                            preflight, run_batch, validate_config)


def config():
    return OpenAICompatibleConfig(base_url='https://open.bigmodel.cn/api/paas/v4', model='glm-4.7')


def response(tokens=None, finish='stop'):
    return ModelResponse(text='{}', metadata={'finish_reason': finish,
                         'usage': {} if tokens is None else {'total_tokens': tokens}})


class SmokeTests(unittest.TestCase):
    def ledger(self, path, check=lambda: True, source='fixture'):
        return CallLedger(path, {'source_kind': source}, check)

    def test_preflight_needs_no_key_and_never_calls_provider(self):
        with patch('tradeintel_ai.model_adapter.OpenAICompatibleModel.complete', side_effect=AssertionError('network')):
            result = preflight(config())
        self.assertEqual(result['new_api_calls'], 0)
        self.assertFalse(result['local_key_present'])
        self.assertEqual(len(result['manifest']['cases']), 4)
        self.assertNotIn('api_key', json.dumps(result))

    def test_wrong_model_or_endpoint_rejected(self):
        for field, value in [('model', 'glm-4.5-air'), ('base_url', 'https://example.test'),
                             ('timeout_seconds', 120), ('temperature', 1)]:
            args = vars(config()).copy()
            args[field] = value
            with self.assertRaises(ValueError):
                validate_config(OpenAICompatibleConfig(**args))

    def test_timeout_reserved_on_disk_before_provider_and_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.ledger(Path(tmp), source='live')
            def timeout(**kwargs):
                saved = json.loads(ledger.path.read_text())
                self.assertEqual(saved['new_api_calls'], 1)
                self.assertEqual(saved['calls'][0]['status'], 'attempt_reserved')
                raise TimeoutError('secret must not be saved')
            with self.assertRaises(TimeoutError):
                ledger.call('D89-1', 'planning', timeout)
            with self.assertRaises(SmokeStopped):
                ledger.call('D89-1', 'planning', lambda: response())
            self.assertNotIn('secret must', ledger.path.read_text())

    def test_tokens_stop_and_unknown_is_not_zero_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.ledger(Path(tmp))
            ledger.call('D89-1', 'planning', lambda: response())
            self.assertFalse(ledger.state['usage_complete'])
            self.assertEqual(ledger.state['unknown_usage_attempts'], 1)
            ledger.call('D89-1', 'policy_generation', lambda: response(30000))
            with self.assertRaises(SmokeStopped):
                ledger.call('D89-2', 'planning', lambda: response())

    def test_six_allowed_slots_and_no_repeat_or_extra_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.ledger(Path(tmp))
            for case in CASES:
                ledger.call(case['id'], 'planning', lambda: response(10))
                if case['policy']:
                    ledger.call(case['id'], 'policy_generation', lambda: response(10))
            self.assertEqual(len(ledger.state['calls']), 6)
            self.assertEqual(ledger.state['new_api_calls'], 0)
            with self.assertRaises(SmokeStopped):
                ledger.call('D89-4', 'policy_generation', lambda: response())
            with self.assertRaises(SmokeStopped):
                ledger.call('D89-1', 'planning', lambda: response())

    def test_source_change_stops_before_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.ledger(Path(tmp), check=lambda: False)
            model = Mock()
            with self.assertRaises(SmokeStopped):
                ledger.call('D89-1', 'planning', model)
            model.assert_not_called()

    def test_truncation_keeps_redacted_raw_response_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = CallLedger(Path(tmp), {'source_kind': 'fixture'}, lambda: True, secret='private-key')
            with self.assertRaises(SmokeStopped):
                ledger.call('D89-1', 'planning', lambda: ModelResponse(text='private-key partial',
                            metadata={'finish_reason': 'length'}))
            raw = (Path(tmp) / 'D89-1-planning-response.json').read_text()
            self.assertIn('partial', raw)
            self.assertNotIn('private-key', raw)
            self.assertEqual(ledger.state['status'], 'stopped')

    def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            keep = Path(tmp) / 'keep'
            keep.write_text('original')
            with self.assertRaises(FileExistsError):
                run_batch(config(), tmp, reviewer=lambda p: True, reviewer_id='fixture',
                          source_kind='fixture', model_factory=lambda s: Mock())
            self.assertEqual(keep.read_text(), 'original')

    def test_real_workflow_invalid_json_stops_preserves_four_case_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Mock()
            model.complete.return_value = response(10)
            reviewer = Mock(return_value=True)
            result = run_batch(config(), Path(tmp) / 'run', reviewer=reviewer, reviewer_id='fixture',
                               source_kind='fixture', model_factory=lambda s: model)
            self.assertEqual(result['status'], 'stopped')
            self.assertEqual(len(result['calls']), 1)
            self.assertEqual(result['new_api_calls'], 0)
            self.assertEqual([c['status'] for c in result['cases']], ['stopped'] + ['not_run'] * 3)
            self.assertEqual(result['denominator'], 4)
            reviewer.assert_not_called()

    def test_missing_live_key_rejects_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            with self.assertRaises(ValueError):
                run_batch(config(), out, reviewer=lambda p: True, reviewer_id='test')
            self.assertFalse(out.exists())

    def test_actual_valid_plan_requires_review_before_execution(self):
        from tests.test_unified_research_v2 import policy_plan
        candidate = policy_plan()
        candidate.update(comparison=None, policy_search_query='Section 301 List 1 effective date duty rate',
                         request_units=[
                             {'quote': '第一批关税何时生效，', 'kind': 'request', 'target': 'policy'},
                             {'quote': '额外税率是多少？', 'kind': 'request', 'target': 'policy'},
                             {'quote': '政策资料截止日是2018-07-06。', 'kind': 'constraint', 'target': 'none'}])
        with tempfile.TemporaryDirectory() as tmp:
            model = Mock()
            model.complete.return_value = ModelResponse(text=json.dumps(candidate, ensure_ascii=False),
                                                       metadata={'finish_reason': 'stop'})
            def reject(packet):
                self.assertEqual(packet['artifact']['status'], 'needs_confirmation')
                self.assertEqual(packet['stage'], 'plan')
                self.assertIn('25%', packet['case']['reference'])
                return False
            result = run_batch(config(), Path(tmp) / 'run', reviewer=reject, reviewer_id='offline-review',
                               source_kind='fixture', model_factory=lambda s: model)
            self.assertEqual(result['stop_reason'], 'review_not_approved')
            self.assertEqual(result['cases'][0]['reviews'][0]['approved'], False)
            self.assertEqual(len(result['calls']), 1)
            self.assertFalse((Path(tmp) / 'run/D89-1/delivery').exists())

    def test_four_case_orchestration_with_stubbed_business_results_not_accuracy(self):
        # Separate from the real-workflow tests: verify only orchestration/accounting.
        class StubWorkflow:
            def __init__(self, model, source):
                self.model = model
            def prepare(self, question, audit_output, secret):
                audit_output.mkdir(parents=True)
                self.case = next(c for c in CASES if c['question'] == question)
                self.model.complete(messages=[], tools=[])
                return {'status': 'needs_scope_selection' if self.case['id'] == 'D89-4' else 'needs_confirmation',
                        'tasks': self.case['tasks'], 'confirmation_token': 'fixture'}
            def confirm(self, token, output, model, source_kind, secret):
                if model is not None:
                    model.complete(messages=[], tools=[])
                return {'status': 'policy_draft' if model else 'trade_draft',
                        'policy': {'generation': {'status': 'draft_requires_semantic_review'}}}
            def cancel(self):
                pass
        with tempfile.TemporaryDirectory() as tmp:
            def factory(stage):
                model = Mock()
                model.complete.return_value = response(10)
                return model
            with patch('tradeintel_ai.development_smoke.snapshot', return_value={'source_kind': 'fixture'}), \
                 patch('tradeintel_ai.development_smoke.workflow', side_effect=StubWorkflow), \
                 patch('tradeintel_ai.development_smoke.inspect_delivery', return_value={'verified': True}):
                result = run_batch(config(), Path(tmp) / 'run', reviewer=lambda p: True,
                                   reviewer_id='synthetic-test-only', source_kind='fixture', model_factory=factory)
            self.assertEqual(result['status'], 'development_review_complete')
            self.assertEqual(len(result['calls']), 6)
            self.assertEqual(result['reported_tokens'], 60)
            self.assertEqual(result['new_api_calls'], 0)
            self.assertEqual([len(c['reviews']) for c in result['cases']], [2, 2, 2, 1])
            self.assertFalse(result['semantic_coverage_verified'])


if __name__ == '__main__':
    unittest.main()
