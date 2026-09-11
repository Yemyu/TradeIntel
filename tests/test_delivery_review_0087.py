"""Failure injection at the final artifact boundary; zero network requests."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.test_unified_research import QUESTION, plan
from tests.test_unified_research_v2 import planner
from tradeintel_ai.unified_research import UnifiedResearchWorkflow, inspect_delivery
from tradeintel_ai import unified_research as module


class DeliveryReview(unittest.TestCase):
    def work(self):
        workflow = UnifiedResearchWorkflow(planner(plan()))
        return workflow, workflow.prepare(QUESTION)['confirmation_token']

    def test_existing_delivery_and_intent_are_never_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            first, token = self.work()
            first.confirm(token, output)
            before = {p: p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}
            second, token = self.work()
            with self.assertRaises(FileExistsError):
                second.confirm(token, output)
            self.assertEqual(before, {p: p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()})
            self.assertIsNone(second.brief._pending)

    def test_orphan_intent_blocks_new_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            intent = Path(tmp) / 'run.delivery-intent.json'
            intent.write_text('{"status":"reserved","run_id":"previous"}')
            before = intent.read_bytes()
            work, token = self.work()
            with patch.object(work.brief, 'confirm') as execute:
                with self.assertRaises(FileExistsError):
                    work.confirm(token, output)
                execute.assert_not_called()
            self.assertEqual(intent.read_bytes(), before)
            self.assertFalse(output.exists())

    def test_report_finalization_failure_cannot_commit_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            work, token = self.work()
            original = module._atomic_text
            def fail(path, text):
                if Path(path).name == 'report.zh-CN.md':
                    raise OSError('fixture disk error')
                return original(path, text)
            with patch.object(module, '_atomic_text', side_effect=fail):
                with self.assertRaises(OSError):
                    work.confirm(token, output)
            self.assertEqual(inspect_delivery(output)['status'], 'failed')
            self.assertNotIn('交付状态：complete', (output / 'report.zh-CN.md').read_text())

    def test_final_marker_failure_never_verifies_embedded_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            work, token = self.work()
            original = module._atomic_text
            def fail(path, text):
                if Path(path).name == 'delivery-status.json':
                    raise OSError('fixture disk error')
                return original(path, text)
            with patch.object(module, '_atomic_text', side_effect=fail):
                with self.assertRaises(OSError):
                    work.confirm(token, output)
            self.assertFalse(inspect_delivery(output)['verified'])

    def test_changed_report_is_detected_and_inspect_needs_no_key(self):
        from scripts.run_unified_research import main
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            work, token = self.work()
            work.confirm(token, output)
            self.assertTrue(inspect_delivery(output)['verified'])
            with patch('scripts.run_unified_research.getpass.getpass', side_effect=AssertionError('no key')):
                self.assertEqual(main(['--inspect', str(output)]), 0)
            (output / 'report.zh-CN.md').write_text('changed')
            self.assertEqual(inspect_delivery(output)['status'], 'changed')

    def test_config_redaction_survives_final_ledger_merge(self):
        model = planner(plan())
        model.config = SimpleNamespace(model='private-value', base_url='https://u:p@example.test/api',
                                       temperature=0, timeout_seconds=10)
        work = UnifiedResearchWorkflow(model)
        preview = work.prepare(QUESTION)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            result = work.confirm(preview['confirmation_token'], output, secret='private-value')
            self.assertNotIn('private-value', json.dumps(result))
            for p in Path(tmp).rglob('*'):
                if p.is_file():
                    self.assertNotIn('private-value', p.read_text())

    def test_caught_policy_interrupt_preserves_partial_delivery(self):
        work, token = self.work()
        model = Mock()
        model.complete.side_effect = KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            result = work.confirm(token, output, model=model, source_kind='fixture')
            self.assertEqual(result['status'], 'partial')
            state = inspect_delivery(output)
            self.assertTrue(state['verified'])
            self.assertTrue(state['interrupted'])
            model.complete.assert_called_once()
