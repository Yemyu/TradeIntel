"""Offline report binding and known-credential disclosure guards."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.prospective_runner import (
    default_cases, run_synthetic_batch, fixture_review, LedgerBoundModel,
)
from tradeintel_ai.prospective_acceptance import (
    AcceptanceGuardError, ProspectiveCallLedger, freeze_dependencies,
)
from tradeintel_ai.unified_research import UnifiedResearchWorkflow
from tests.test_prospective_runner_0114 import StaticModel
from tests.test_trade_mapping_proposal_0105 import candidate


class ReportPrivacy0125Tests(unittest.TestCase):
    def test_actual_report_is_present_and_bound_in_review(self):
        seen = []
        def reviewer(packet):
            if 'result' in packet:
                seen.append(packet['report_document'])
            return fixture_review(packet)
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = run_synthetic_batch(out, cases=[default_cases()[0]], strict_protocol=True,
                model_factory=lambda *_: StaticModel(candidate()), reviewer=reviewer)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]['text'], (out / default_cases()[0].id / 'delivery/report.zh-CN.md').read_text())

    def test_missing_report_acknowledgement_cannot_pass(self):
        def reviewer(packet):
            submission = fixture_review(packet)
            submission.pop('report_sha256', None)
            return submission
        with TemporaryDirectory() as tmp:
            result = run_synthetic_batch(Path(tmp) / 'run', cases=[default_cases()[0]],
                strict_protocol=True, model_factory=lambda *_: StaticModel(candidate()), reviewer=reviewer)
            self.assertEqual(result['status'], 'stopped')

    def test_returned_result_cannot_differ_from_saved_report_data(self):
        original = UnifiedResearchWorkflow.confirm
        def altered(workflow, *args, **kwargs):
            result = original(workflow, *args, **kwargs)
            result['summary']['total_usd'] += 1
            return result
        reviewed_answers = []
        def reviewer(packet):
            if 'result' in packet:
                reviewed_answers.append(packet)
            return fixture_review(packet)
        with TemporaryDirectory() as tmp, patch.object(UnifiedResearchWorkflow, 'confirm', altered):
            result = run_synthetic_batch(Path(tmp) / 'run', cases=[default_cases()[0]],
                strict_protocol=True, model_factory=lambda *_: StaticModel(candidate()), reviewer=reviewer)
            self.assertEqual(result['status'], 'stopped')
            self.assertEqual(reviewed_answers, [])

    def test_custom_workflow_cannot_impersonate_strict_delivery(self):
        factory = Mock()
        with TemporaryDirectory() as tmp, self.assertRaisesRegex(AcceptanceGuardError, 'registered_workflow'):
            run_synthetic_batch(Path(tmp) / 'run', cases=[default_cases()[0]], strict_protocol=True,
                model_factory=factory, workflow_factory=Mock())
        factory.assert_not_called()

    def test_known_credential_in_input_or_output_is_never_recorded(self):
        secret = 'offline-only-credential-0125'
        for in_input in (True, False):
            with self.subTest(in_input=in_input), TemporaryDirectory() as tmp:
                root = Path(tmp) / 'run'
                ledger = ProspectiveCallLedger(['q'], root,
                    frozen_snapshot=freeze_dependencies([Path(__file__)]))
                model = StaticModel(callback=lambda *_: ModelResponse(text=secret,
                    metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 5}}))
                model.config = SimpleNamespace(api_key=secret)
                bound = LedgerBoundModel(model, ledger, 'q', 'planning', {})
                with self.assertRaisesRegex(AcceptanceGuardError, 'credential_in_model_'):
                    bound.complete(messages=[{'role': 'user', 'content': secret if in_input else 'public question'}], tools=[])
                self.assertEqual(len(model.calls), 0 if in_input else 1)
                for path in root.rglob('*.json'):
                    self.assertNotIn(secret, path.read_text())
