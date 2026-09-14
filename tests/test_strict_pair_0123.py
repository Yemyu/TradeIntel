"""Strict offline requirements are checked before factories or calls."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from tradeintel_ai.prospective_runner import default_cases, run_synthetic_batch, paired_policy_messages
from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, ProspectiveCallLedger, freeze_dependencies
from tests import test_evidence_pair_0122


class StrictPair0123Tests(unittest.TestCase):
    def test_missing_requirements_fail_before_factory(self):
        trade, _, policy = default_cases()
        for case in (replace(trade, independent_request=None),
                     replace(trade, run_controls=False),
                     replace(policy, policy_reference=None),
                     replace(trade, allow_host_gap_review=True)):
            with self.subTest(case=case.id), TemporaryDirectory() as tmp:
                factory = Mock()
                with self.assertRaises(AcceptanceGuardError):
                    run_synthetic_batch(Path(tmp) / 'run', cases=[case], model_factory=factory,
                        strict_protocol=True, fact_reviewer=test_evidence_pair_0122.synthetic_fact_review)
                factory.assert_not_called()

    def test_missing_fact_reviewer_blocks_entire_batch(self):
        with TemporaryDirectory() as tmp:
            factory = Mock()
            with self.assertRaisesRegex(AcceptanceGuardError, 'strict_policy_review_required'):
                run_synthetic_batch(Path(tmp) / 'run', model_factory=factory, strict_protocol=True)
            factory.assert_not_called()

    def test_required_facts_cannot_disappear_by_omitting_all_artifacts(self):
        with TemporaryDirectory() as tmp:
            snapshot = freeze_dependencies([Path(__file__)], configuration={
                'required_reviews': {'q': {'facts': True}}})
            ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'run', frozen_snapshot=snapshot)
            with self.assertRaisesRegex(AcceptanceGuardError, 'artifact missing'):
                ledger._fact_bindings('q', baseline=False)

    def test_shared_prompt_changes_only_evidence(self):
        import json
        main = paired_policy_messages('question', '2018-07-06', [{'id': 's', 'text': 'source'}])
        baseline = paired_policy_messages('question', '2018-07-06', [])
        self.assertEqual(main[0], baseline[0])
        left, right = json.loads(main[1]['content']), json.loads(baseline[1]['content'])
        self.assertTrue(left.pop('evidence'))
        self.assertEqual(right.pop('evidence'), [])
        self.assertEqual(left, right)

    def test_strict_four_scenario_batch(self):
        test_evidence_pair_0122.EvidencePair0122Tests(
            'test_four_scenarios_complete_offline_without_accuracy_claim'
        ).test_four_scenarios_complete_offline_without_accuracy_claim(strict=True)
