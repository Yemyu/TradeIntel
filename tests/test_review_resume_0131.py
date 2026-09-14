from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.prospective_acceptance import (
    AcceptanceGuardError, AcceptanceStopped, ProspectiveCallLedger, freeze_dependencies,
)
from tradeintel_ai.prospective_runner import ProspectiveSyntheticRunner
from tests.test_prospective_runner_0114 import StaticModel, trade_case
from tests.test_trade_mapping_proposal_0105 import candidate
from tradeintel_ai.unified_research import inspect_delivery


class ReviewResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'batch'
        self.snapshot = freeze_dependencies([Path(__file__)], configuration={'test': True})
        self.ledger = ProspectiveCallLedger(['q'], self.path, frozen_snapshot=self.snapshot)

    def complete_call(self):
        reservation = self.ledger.reserve('q', 'planning')
        self.ledger.complete(reservation, metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 5}},
                             raw_response={'text': 'saved response'})

    def test_reopen_boundary_preserves_call_and_blocks_duplicate(self):
        self.complete_call()
        checkpoint = {'question_id': 'q', 'stage': 'plan_review', 'preview': {'status': 'needs_confirmation'}}
        self.ledger.pause_for_review(checkpoint)
        with self.assertRaises(AcceptanceStopped):
            self.ledger.reserve('q', 'policy_with_evidence')
        restored = ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=self.snapshot)
        self.assertEqual(restored.continue_review(), checkpoint)
        self.assertEqual(len(restored.state['calls']), 1)
        with self.assertRaises(AcceptanceStopped):
            restored.reserve('q', 'planning')
        with self.assertRaises(AcceptanceGuardError):
            ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=self.snapshot)

    def test_active_call_and_unmarked_crash_cannot_resume(self):
        self.ledger.reserve('q', 'planning')
        with self.assertRaises(AcceptanceStopped):
            self.ledger.pause_for_review({'question_id': 'q', 'stage': 'plan_review'})
        with self.assertRaises(AcceptanceGuardError):
            ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=self.snapshot)

    def test_changed_response_or_snapshot_rejected(self):
        self.complete_call()
        self.ledger.pause_for_review({'question_id': 'q', 'stage': 'plan_review'})
        changed = deepcopy(self.snapshot)
        changed['snapshot_sha256'] = 'changed'
        with self.assertRaises(AcceptanceGuardError):
            ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=changed)
        (self.path / 'responses/q-planning.json').write_text('{}')
        with self.assertRaises(AcceptanceGuardError):
            ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=self.snapshot)

    def test_unknown_reservation_even_with_waiting_label_rejected(self):
        self.ledger.reserve('q', 'planning')
        self.ledger.state.update(status='waiting_review', resume_supported=True)
        self.ledger._save()
        with self.assertRaisesRegex(AcceptanceGuardError, 'incomplete call'):
            ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=self.snapshot)

    def test_stale_opened_instance_cannot_continue_twice(self):
        self.complete_call()
        self.ledger.pause_for_review({'question_id': 'q', 'stage': 'plan_review'})
        a = ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=self.snapshot)
        b = ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=self.snapshot)
        a.continue_review()
        with self.assertRaises(AcceptanceGuardError):
            b.continue_review()

    def test_registered_trade_workflow_restores_without_another_planner_call(self):
        case = trade_case()
        model = StaticModel(candidate())
        runner = ProspectiveSyntheticRunner(self.path / 'unused', model_factory=lambda *_: model)
        workflow = runner._build_workflow(model, case)
        preview = workflow.prepare(case.question)
        self.assertEqual(preview['status'], 'needs_confirmation')
        state = workflow.export_review_state()
        self.ledger.pause_for_review({'question_id': 'q', 'stage': 'plan_review',
                                     'workflow': state, 'preview': preview})
        restored_ledger = ProspectiveCallLedger.resume_review(self.path, frozen_snapshot=self.snapshot)
        checkpoint = restored_ledger.continue_review()
        restored = runner._build_workflow(model, case)
        restored.restore_review_state(checkpoint['workflow'])
        result = restored.confirm(checkpoint['preview']['confirmation_token'],
                                  Path(self.tmp.name) / 'delivery', source_kind='fixture')
        self.assertEqual(result['status'], 'trade_draft')
        self.assertTrue(inspect_delivery(Path(self.tmp.name) / 'delivery')['verified'])
        self.assertEqual(len(model.calls), 1)

    def test_workflow_configuration_change_and_overwrite_rejected(self):
        case = trade_case()
        model = StaticModel(candidate())
        runner = ProspectiveSyntheticRunner(self.path / 'unused', model_factory=lambda *_: model)
        workflow = runner._build_workflow(model, case)
        workflow.prepare(case.question)
        state = workflow.export_review_state()
        with self.assertRaises(ValueError):
            workflow.restore_review_state(state)
        restored = runner._build_workflow(model, case)
        changed = deepcopy(state)
        changed['planner_configuration']['model'] = 'changed-model'
        with self.assertRaises(ValueError):
            restored.restore_review_state(changed)
        self.assertIsNone(restored._pending)


if __name__ == '__main__':
    unittest.main()
