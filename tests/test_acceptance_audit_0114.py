from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.prospective_acceptance import (
    AcceptanceGuardError, AcceptanceStopped, FrozenInputChanged,
    ProspectiveCallLedger, digest, freeze_dependencies, validate_structured_review, validate_terminal,
)
from tests import test_prospective_acceptance_guards_0112 as fixtures_module


class Audit0114Tests(unittest.TestCase):
    def test_absent_policy_generation_cannot_pass(self):
        packet = fixtures_module.ProspectiveAcceptanceGuardTests().support_packet()
        del packet['result']['policy']
        self.assertFalse(validate_terminal(preview=packet['preview'], result=packet['result'],
                         delivery=packet['delivery'], review={'approved': True},
                         expected_tasks=['policy'])['approved'])

    def test_later_clarification_cannot_hide_executable_preview(self):
        self.assertFalse(validate_terminal(preview={'status': 'needs_confirmation'},
                         result={'status': 'needs_clarification'}, review={'approved': True},
                         expected_kind='clarification')['approved'])

    def ledger(self, tmp):
        source = Path(tmp) / 'dependency'
        source.write_text('fixture')
        return ProspectiveCallLedger(['Q1', 'Q2'], Path(tmp) / 'run',
                                     frozen_snapshot=freeze_dependencies([source]))

    def test_planning_returns_do_not_complete_questions(self):
        with TemporaryDirectory() as tmp:
            ledger = self.ledger(tmp)
            for qid in ('Q1', 'Q2'):
                call = ledger.reserve(qid, 'planning')
                ledger.complete(call, metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 3}})
            self.assertNotEqual(ledger.state['questions'][0]['status'], 'completed')
            with self.assertRaises(AcceptanceGuardError):
                ledger.finalize()

    def test_saved_response_tampering_stops_next_call(self):
        with TemporaryDirectory() as tmp:
            ledger = self.ledger(tmp)
            call = ledger.reserve('Q1', 'planning')
            row = ledger.complete(call, metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 3}},
                                  raw_response={'text': 'original'})
            (ledger.output / row['raw_response']['path']).write_text('{}')
            with self.assertRaises(FrozenInputChanged):
                ledger.reserve('Q2', 'planning')
            self.assertEqual(ledger.state['status'], 'stopped')

    def test_truncated_return_stops_but_retains_reported_usage(self):
        with TemporaryDirectory() as tmp:
            ledger = self.ledger(tmp)
            call = ledger.reserve('Q1', 'planning')
            ledger.complete(call, metadata={'finish_reason': 'length', 'usage': {'total_tokens': 17}})
            self.assertEqual(ledger.summary()['reported_tokens'], 17)
            self.assertEqual(ledger.summary()['status'], 'stopped')
            with self.assertRaises(AcceptanceStopped):
                ledger.reserve('Q2', 'planning')

    def test_failed_parse_keeps_usage_and_raw(self):
        with TemporaryDirectory() as tmp:
            ledger = self.ledger(tmp)
            call = ledger.reserve('Q1', 'planning')
            row = ledger.complete(call, metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 17}},
                                  response_status='needs_review', raw_response={'text': 'bad json'})
            self.assertEqual(ledger.summary()['reported_tokens'], 17)
            self.assertTrue((ledger.output / row['raw_response']['path']).is_file())

    def test_duplicate_review_does_not_overwrite_original(self):
        with TemporaryDirectory() as tmp:
            ledger = self.ledger(tmp)
            ledger.record_review('Q1', 'planning', {'decision': 'first'})
            with self.assertRaises((FileExistsError, AcceptanceGuardError)):
                ledger.record_review('Q1', 'planning', {'decision': 'replacement'})
            value = json.loads((ledger.output / 'reviews/Q1-planning-submission.json').read_text())
            self.assertEqual(value['decision'], 'first')

    def test_forged_policy_and_wrong_number_witnesses_fail(self):
        fixtures = fixtures_module.ProspectiveAcceptanceGuardTests()
        packet = fixtures.support_packet()
        review = fixtures.passing_review()
        for kind in ('policy', 'number'):
            with self.subTest(kind=kind):
                bad = deepcopy(review)
                if kind == 'policy':
                    bad['items'][0]['witnesses'][0]['citation_id'] = 'invented'
                else:
                    packet = deepcopy(packet)
                    packet['result']['amount'] = 999
                bad['packet_sha256'] = digest(packet)
                with self.assertRaises(AcceptanceGuardError):
                    validate_structured_review(packet, bad, reviewer='fixture', expected_tasks=['policy'])

    def test_plan_review_is_not_answer_review(self):
        packet = {
            'preview': {
                'status': 'needs_confirmation',
                'tasks': ['trade'],
                'confirmation_token': 'fixture-token',
                'executed': False,
            },
            'checklist': [{'id': 'scope', 'kind': 'fact'}],
        }
        review = {
            'packet_sha256': digest(packet),
            'overall': {'status': 'pass', 'reason': '计划范围与原问题一致'},
            'items': [{'id': 'scope', 'status': 'pass', 'reason': '已核对'}],
        }
        accepted = validate_structured_review(
            packet, review, reviewer='fixture', stage='plan', expected_tasks=['trade'])
        self.assertTrue(accepted['approved'])
        self.assertEqual(accepted['stage'], 'plan')
        answer_review = dict(review)
        answer = validate_structured_review(packet, answer_review, reviewer='fixture', expected_tasks=['trade'])
        self.assertFalse(answer['approved'])

    def test_planning_review_cannot_approve_executable_preview(self):
        packet = {
            'preview': {'status': 'research_draft', 'tasks': ['trade'], 'executed': True},
            'checklist': [{'id': 'scope', 'kind': 'fact'}],
        }
        review = {
            'packet_sha256': digest(packet),
            'overall': {'status': 'pass', 'reason': '看过'},
            'items': [{'id': 'scope', 'status': 'pass', 'reason': '看过'}],
        }
        accepted = validate_structured_review(
            packet, review, reviewer='fixture', stage='plan', expected_kind='clarification')
        self.assertFalse(accepted['approved'])
        self.assertIn('preview:not_clarification_or_boundary', accepted['terminal']['hard_failures'])

    def test_reviewed_ledger_requires_controls_before_completion(self):
        with TemporaryDirectory() as tmp:
            ledger = self.ledger(tmp)
            for question_id in ('Q1', 'Q2'):
                call = ledger.reserve(question_id, 'planning')
                ledger.complete(call, metadata={'finish_reason': 'stop',
                                                'usage': {'total_tokens': 3}})
                ledger.mark_question_status(question_id, 'accepted')
            with self.assertRaises(AcceptanceGuardError):
                ledger.finalize_reviewed(required_controls=['control_a'])
            ledger.record_control('control_a', {'status': 'pass'})
            # A control file is insufficient: 0116 blocks closure until real
            # calculations and review-to-execution bindings are implemented.
            with self.assertRaises(AcceptanceGuardError):
                ledger.finalize_reviewed(required_controls=['control_a'])
