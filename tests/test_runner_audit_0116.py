"""Counterexamples for the 0115 acceptance claims; all providers are fixtures."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, ProspectiveCallLedger, freeze_dependencies
from tradeintel_ai.prospective_runner import ProspectiveSyntheticRunner, run_synthetic_batch, fixture_review
from tests.test_prospective_runner_0114 import StaticModel, trade_case
from tests.test_trade_mapping_proposal_0105 import candidate


class RunnerAudit0116Tests(unittest.TestCase):
    def test_status_labels_without_reviews_cannot_finalize(self):
        with TemporaryDirectory() as tmp:
            ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'batch',
                frozen_snapshot=freeze_dependencies([Path(__file__)]))
            ledger.mark_question_status('q', 'accepted')
            with self.assertRaises(AcceptanceGuardError):
                ledger.finalize_reviewed()

    def test_placeholder_controls_cannot_be_reported_as_pass(self):
        with TemporaryDirectory() as tmp:
            ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'batch',
                frozen_snapshot=freeze_dependencies([Path(__file__)]))
            runner = ProspectiveSyntheticRunner(Path(tmp) / 'unused',
                model_factory=lambda *_: StaticModel())
            with self.assertRaisesRegex(AcceptanceGuardError, 'controls_not_implemented'):
                runner._run_controls(ledger, trade_case(), StaticModel({'invented': 'anything'}))
            self.assertEqual(ledger.state['controls'], {})

    def test_forged_validated_control_shape_is_rejected(self):
        with TemporaryDirectory() as tmp:
            ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'batch',
                frozen_snapshot=freeze_dependencies([Path(__file__)]))
            with self.assertRaisesRegex(AcceptanceGuardError, 'validated control kind is unknown'):
                ledger.record_control('control_a:q', {'status': 'validated'})

    def test_model_factory_cannot_receive_reference_answers(self):
        seen = []
        def factory(stage, public_case):
            seen.append(hasattr(public_case, 'reference'))
            return StaticModel(candidate())
        with TemporaryDirectory() as tmp:
            run_synthetic_batch(Path(tmp) / 'batch', cases=[trade_case()], model_factory=factory)
        self.assertEqual(seen, [False])

    def test_delivery_changed_during_review_is_rejected(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'batch'
            def reviewer(packet):
                if 'result' in packet:
                    report = out / trade_case().id / 'delivery/report.zh-CN.md'
                    report.write_text('changed during review')
                return fixture_review(packet)
            summary = run_synthetic_batch(out, cases=[trade_case()],
                model_factory=lambda *_: StaticModel(candidate()), reviewer=reviewer)
            self.assertEqual(summary['stop_reason'], 'delivery_changed_during_review')

    def test_case_contents_are_in_snapshot(self):
        runner = ProspectiveSyntheticRunner('/unused', cases=[trade_case()], model_factory=lambda *_: None)
        frozen = runner._snapshot()
        self.assertEqual(frozen['configuration']['cases'][0]['question'], trade_case().question)


if __name__ == '__main__':
    unittest.main()
