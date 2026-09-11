"""Failure paths missed by the previous integration tests; no network."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_unified_research import QUESTION, plan
from tests.test_unified_research_v2 import planner
from tradeintel_ai.unified_research import UnifiedResearchWorkflow
from tradeintel_ai.policy_workflow import load_frozen_corpus

ROOT = Path(__file__).resolve().parents[1]


class AuditTests(unittest.TestCase):
    def test_timeout_and_interrupt_remain_attempts_on_disk(self):
        for failure in (TimeoutError('private-key'), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / 'planning'
                model = Mock()
                def fail(**kwargs):
                    audit = json.loads((out / 'audit.json').read_text())
                    self.assertEqual(audit['status'], 'attempt_reserved')
                    self.assertEqual(audit['new_api_calls'], 1)
                    raise failure
                model.complete.side_effect = fail
                work = UnifiedResearchWorkflow(model, planner_source_kind='live')
                result = work.prepare(QUESTION, audit_output=out, secret='private-key')
                self.assertEqual(result['planner_audit']['model_calls'], 1)
                self.assertEqual(result['planner_audit']['usage_status'], 'unknown')
                self.assertEqual(json.loads((out / 'audit.json').read_text())['status'], 'failed')
                self.assertNotIn('private-key', (out / 'audit.json').read_text())
                with self.assertRaises(FileExistsError):
                    work.prepare(QUESTION, audit_output=out)
                model.complete.assert_called_once()

    def test_live_without_audit_directory_never_sends(self):
        model = Mock()
        result = UnifiedResearchWorkflow(model, planner_source_kind='live').prepare(QUESTION)
        self.assertEqual(result['model_calls'], 0)
        model.complete.assert_not_called()

    def test_failed_reservation_never_sends(self):
        work = UnifiedResearchWorkflow(Mock(), planner_source_kind='live')
        original = work._write_json
        def write(output, name, value, secret=''):
            if name == 'audit.json':
                raise OSError('disk full')
            return original(output, name, value, secret)
        with tempfile.TemporaryDirectory() as tmp, patch.object(work, '_write_json', side_effect=write):
            result = work.prepare(QUESTION, audit_output=Path(tmp) / 'planning')
        self.assertEqual(result['model_calls'], 0)
        work.planner_model.complete.assert_not_called()

    def test_sequence_has_no_duplicate_comparison_task(self):
        payload = plan()
        payload['comparison'] = {'kind': 'sequence'}
        payload['evidence']['trade.comparison'] = '2018-09和2018-10'
        preview = UnifiedResearchWorkflow(planner(payload)).prepare(QUESTION)
        self.assertEqual(preview['task_ids'], ['policy_question', 'trade_series'])

    def test_frozen_sources_are_checked_separately_from_current_code(self):
        corpus = load_frozen_corpus(ROOT)
        target = ROOT / corpus['chunks'][0]['local_path']
        original = Path.read_bytes
        def changed(path):
            return b'changed' if path == target else original(path)
        with patch.object(Path, 'read_bytes', changed):
            with self.assertRaisesRegex(ValueError, 'Frozen policy source changed'):
                load_frozen_corpus(ROOT)


if __name__ == '__main__':
    unittest.main()
