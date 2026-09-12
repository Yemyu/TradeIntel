"""Reproductions from the 0117 audit; never invoke a remote provider."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, ProspectiveCallLedger, freeze_dependencies, digest, validate_structured_review
from tradeintel_ai.prospective_runner import _evaluate_no_evidence_response, _direct_trade_recompute
from tradeintel_ai.unified_research import build_product_workflow
from tests.test_prospective_runner_0114 import policy_case, trade_case, StaticModel
from tests.test_trade_mapping_proposal_0105 import candidate


class ReauditTests(unittest.TestCase):
    def test_valid_review_without_model_call_cannot_complete(self):
        packet = {'preview': {'status': 'needs_clarification', 'tasks': []},
                  'expected_kind': 'clarification', 'expected_tasks': [],
                  'checklist': [{'id': 'scope', 'kind': 'fact'}]}
        submission = {'packet_sha256': digest(packet),
                      'overall': {'status': 'pass', 'reason': 'fixture'},
                      'items': [{'id': 'scope', 'status': 'pass', 'reason': 'fixture'}]}
        validation = validate_structured_review(packet, submission, reviewer='fixture',
            expected_kind='clarification', expected_tasks=[], stage='plan')
        with TemporaryDirectory() as tmp:
            ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'batch',
                frozen_snapshot=freeze_dependencies([Path(__file__)]))
            ledger.record_review('q', 'planning', submission, packet=packet, validation=validation)
            with self.assertRaisesRegex(AcceptanceGuardError, 'actual planning response'):
                ledger.approve_question('q', expected_kind='clarification')

    def test_empty_review_cannot_be_certified_by_caller_flag(self):
        with TemporaryDirectory() as tmp:
            ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'batch',
                frozen_snapshot=freeze_dependencies([Path(__file__)]))
            with self.assertRaises(AcceptanceGuardError):
                ledger.record_review('q', 'planning', {}, packet={}, validation={'approved': True})
            self.assertEqual(ledger.state['reviews'], {})

    def test_negated_facts_are_not_scored_as_correct(self):
        case = replace(policy_case()[0], control_facts=('2018-07-06', '25%'))
        result = _evaluate_no_evidence_response(case, ModelResponse(
            text='并非2018-07-06生效，税率不是25%', metadata={}))
        self.assertEqual(result['literal_match_fraction'], 1.0)
        self.assertIsNone(result['fact_recall'])
        self.assertEqual(result['answer_quality'], 'unreviewed')

    def test_wrong_change_is_caught_even_when_monthly_amounts_match(self):
        workflow = build_product_workflow(StaticModel(candidate()))
        preview = workflow.prepare(trade_case().question)
        with TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'delivery', source_kind='fixture')
            self.assertTrue(_direct_trade_recompute(result)['checks']['passed'])
            wrong = deepcopy(result)
            wrong['summary']['comparison']['change_usd'] = 0
            checks = _direct_trade_recompute(wrong)['checks']
            self.assertTrue(checks['series_equal'])
            self.assertFalse(checks['passed'])
            del wrong['request']['trade']['months']
            with self.assertRaises(AcceptanceGuardError):
                _direct_trade_recompute(wrong)


if __name__ == '__main__':
    unittest.main()
