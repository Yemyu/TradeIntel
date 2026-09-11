"""Failure, confirmation and disclosure regressions; no external model calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_unified_research import QUESTION, plan
from tests.test_unified_research_v2 import policy_plan, planner
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.unified_research import UnifiedResearchWorkflow
from tradeintel_ai.unified_research import validate_plan


class ReliabilityTests(unittest.TestCase):
    def test_final_obligations_do_not_restore_redacted_question(self):
        candidate = policy_plan()
        work = UnifiedResearchWorkflow(planner(candidate))
        preview = work.prepare(QUESTION)
        secret = candidate['policy_question']
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            result = work.confirm(preview['confirmation_token'], output, secret=secret)
            self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))
            self.assertNotIn(secret, (output / 'obligations.json').read_text())

    def test_default_fields_do_not_need_invented_quotes(self):
        candidate = plan()
        for field in ('trade.policy_id', 'trade.operation', 'trade.causal_effect'):
            del candidate['evidence'][field]
        self.assertTrue(validate_plan(candidate, QUESTION))
        work = UnifiedResearchWorkflow(planner(candidate))
        preview = work.prepare(QUESTION)
        self.assertEqual(preview['provenance']['trade.causal_effect']['kind'], 'app_default')
        self.assertEqual(preview['provenance']['trade.metric']['kind'], 'user_quote')
        candidate['trade']['causal_effect'] = True
        with self.assertRaises(ValueError):
            validate_plan(candidate, QUESTION)

    def test_model_cannot_self_certify_field_provenance(self):
        candidate = plan()
        candidate['provenance'] = {'trade.origin': {'kind': 'app_default'}}
        with self.assertRaises(ValueError):
            validate_plan(candidate, QUESTION)

    def test_main_entry_delegates_natural_language_mode_without_api(self):
        from scripts.run_research_brief import main
        with patch('scripts.run_unified_research.main', return_value=0) as delegate:
            self.assertEqual(main(['--natural-language', '--question', 'fixture']), 0)
            self.assertIn('fixture', delegate.call_args.args[0])

    def work(self, policy_only=False):
        candidate = policy_plan() if policy_only else plan()
        work = UnifiedResearchWorkflow(planner(candidate))
        return work, work.prepare(QUESTION)

    def test_mutating_task_preview_cannot_change_execution(self):
        work, preview = self.work(True)
        preview['tasks'][0] = 'trade'
        with tempfile.TemporaryDirectory() as tmp:
            result = work.confirm(preview['confirmation_token'], Path(tmp)/'run')
        self.assertEqual(result['tasks'], ['policy'])
        self.assertEqual(result['trade']['status'], 'not_requested')

    def test_unreadable_fingerprint_consumes_both_tokens(self):
        work, preview = self.work()
        with patch.object(work, '_fingerprints', side_effect=OSError('fixture')):
            result = work.confirm(preview['confirmation_token'], '/unused')
        self.assertEqual(result['status'], 'confirmation_rejected')
        self.assertIsNone(work._pending)
        self.assertIsNone(work.brief._pending)

    def test_preflight_fingerprint_failure_clears_inner_pending(self):
        work, _ = self.work()
        with patch.object(work, '_fingerprints', side_effect=OSError('fixture')):
            self.assertEqual(work.prepare(QUESTION)['status'], 'needs_review')
        self.assertIsNone(work.brief._pending)

    def test_old_revision_is_rejected_without_planning(self):
        work, preview = self.work()
        work.planner_model.complete.reset_mock()
        result = work.prepare(QUESTION, conversation_revision=preview['conversation_revision'])
        self.assertEqual(result['model_calls'], 0)
        work.planner_model.complete.assert_not_called()
        self.assertIsNone(work._pending)

    def test_policy_timeout_is_partial_and_trade_is_persisted(self):
        work, preview = self.work()
        model = Mock()
        model.complete.side_effect = TimeoutError('secret-fixture')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'run'
            result = work.confirm(preview['confirmation_token'], output, model=model, source_kind='fixture')
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['summary']['total_usd'], 77600543957)
            self.assertTrue((output/'trade-result.json').exists())
            events = [json.loads(line) for line in (output/'execution-audit.jsonl').read_text().splitlines()]
            self.assertEqual([event['event'] for event in events], [
                'confirmed', 'trade_started', 'trade_finished', 'policy_started',
                'policy_finished', 'execution_completed'])
            self.assertEqual(events[-1]['status'], 'partial')
            self.assertIn('77,600,543,957', (output/'report.zh-CN.md').read_text())
        self.assertEqual(result['policy']['audit']['diagnostic']['category'], 'timeout')
        self.assertEqual(result['total_model_calls'], 2)
        self.assertEqual(result['new_api_calls'], 0)
        self.assertEqual({item['id']: item['status'] for item in result['obligations']},
                         {'policy_question': 'failed', 'trade_series': 'completed'})
        model.complete.assert_called_once()

    def test_policy_only_failure_is_not_a_draft(self):
        work, preview = self.work(True)
        model = Mock()
        model.complete.side_effect = TimeoutError()
        with tempfile.TemporaryDirectory() as tmp:
            result = work.confirm(preview['confirmation_token'], Path(tmp)/'run',
                                  model=model, source_kind='fixture')
        self.assertEqual(result['status'], 'policy_failed')
        model.complete.assert_called_once()

    def test_policy_report_and_return_are_redacted_and_escaped(self):
        work, preview = self.work(True)
        model = Mock()
        def answer(**kwargs):
            context = json.loads(kwargs['messages'][1]['content'])
            return ModelResponse(text=json.dumps({'claims': [{
                'text': '<script>fake-secret</script>',
                'citations': [context['evidence'][0]['id']],
            }]}), metadata={'finish_reason': 'stop'})
        model.complete.side_effect = answer
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'run'
            result = work.confirm(preview['confirmation_token'], output, model=model,
                                  source_kind='fixture', secret='fake-secret')
            self.assertNotIn('fake-secret', json.dumps(result))
            for path in output.rglob('*.json'):
                self.assertNotIn('fake-secret', path.read_text())
            report = (output/'report.zh-CN.md').read_text()
            self.assertNotIn('<script>', report)
            self.assertNotIn('fake-secret', report)
            self.assertIn('SHA256', report)
        model.complete.assert_called_once()

    def test_retrieval_exception_preserves_trade_report(self):
        work, preview = self.work()
        with tempfile.TemporaryDirectory() as tmp, patch(
                'tradeintel_ai.research_brief.PolicyRetriever.search', side_effect=ValueError('fixture')):
            result = work.confirm(preview['confirmation_token'], Path(tmp)/'run')
            self.assertTrue((Path(tmp)/'run/report.zh-CN.md').exists())
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['task_results']['policy'], 'retrieval_failed')
        self.assertEqual(result['summary']['total_usd'], 77600543957)

    def test_journal_redacts_secret(self):
        from tradeintel_ai.execution_journal import ExecutionJournal
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.jsonl'
            journal = ExecutionJournal(path, secret='fixture-key')
            journal.append('confirmed', detail={'message': 'fixture-key'})
            text = path.read_text()
        self.assertNotIn('fixture-key', text)
        self.assertIn('[REDACTED]', text)

    def test_obligations_are_host_owned_and_saved_separately(self):
        work, preview = self.work(True)
        self.assertEqual(preview['obligations'][0]['status'], 'pending')
        preview['obligations'][0]['status'] = 'completed'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            result = work.confirm(preview['confirmation_token'], output)
            saved = json.loads((output / 'obligations.json').read_text())
        self.assertEqual(result['obligations'][0]['status'], 'not_executed')
        self.assertEqual(saved, result['obligations'])
