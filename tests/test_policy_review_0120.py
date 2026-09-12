"""Adversarial policy-review checks, entirely offline."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.policy_facts import load_frozen_policy_reference
from tradeintel_ai.prospective_acceptance import AcceptanceGuardError
from tradeintel_ai.prospective_runner import (
    _evaluate_no_evidence_response, _validate_policy_case_reference, default_cases,
    ProspectiveSyntheticRunner,
)
from tests import test_policy_facts_0119


class PolicyReview0120Tests(unittest.TestCase):
    def test_cannot_remove_or_replace_strict_case_facts(self):
        case = default_cases()[2]
        for facts in ((), ({**case.facts[0], 'expected_value': '0%'},)):
            with self.subTest(facts=facts), self.assertRaises(AcceptanceGuardError):
                _validate_policy_case_reference(replace(case, facts=facts))

    def test_cannot_replace_frozen_source_catalog(self):
        case = default_cases()[2]
        reference = deepcopy(case.policy_reference)
        first = next(iter(reference['source_catalog']))
        reference['source_catalog'][first]['text'] = 'invented reference'
        with self.assertRaises(AcceptanceGuardError):
            _validate_policy_case_reference(replace(case, policy_reference=reference))

    def test_reference_excludes_future_sources(self):
        with TemporaryDirectory() as tmp:
            path = test_policy_facts_0119.PolicyFacts0119Tests()._copy_reference_tree(Path(tmp))
            reference = json.loads(path.read_text())
            reference['as_of'] = '2018-06-19'
            path.write_text(json.dumps(reference), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '截止日'):
                load_frozen_policy_reference(tmp)

    def test_malformed_baseline_is_not_validated(self):
        case = default_cases()[2]
        invalid = ('not JSON', '{}', '{"claims":null}',
                   '{"answer":"unchecked factual claim","claims":[]}',
                   '{"claims":[{"text":"","citations":[]}]}',
                   '{"claims":[{"text":"ok","citations":[]},42]}',
                   json.dumps({'claims': [{'text': 'x' * 1501, 'citations': []}]}),
                   json.dumps({'claims': [{'text': 'x', 'citations': []}] * 7}))
        for text in invalid:
            with self.subTest(text=text[:80]):
                result = _evaluate_no_evidence_response(case, ModelResponse(text=text))
                self.assertFalse(result['claim_schema_valid'])
                self.assertNotEqual(result['status'], 'validated')

    def test_valid_baseline_retains_every_claim(self):
        result = _evaluate_no_evidence_response(default_cases()[2], ModelResponse(
            text='{"claims":[{"text":"无法确定","citations":[]}]}'))
        self.assertTrue(result['claim_schema_valid'])
        self.assertEqual(len(result['response']['parsed']['claims']), 1)

    def test_invalid_baseline_is_saved_and_stops_before_fact_review(self):
        case = default_cases()[2]
        reviewer, ledger, model = Mock(), Mock(), Mock()
        raw = '{"claims":[{"text":"valid","citations":[]},42]}'
        model.complete.return_value = ModelResponse(text=raw)
        with TemporaryDirectory() as tmp:
            runner = ProspectiveSyntheticRunner(tmp, cases=[case],
                model_factory=Mock(), fact_reviewer=reviewer)
            with self.assertRaisesRegex(AcceptanceGuardError, 'baseline_claim_schema_invalid'):
                runner._run_controls(ledger, case, model, result={'request': {}})
        reviewer.assert_not_called()
        ledger.record_control.assert_not_called()
        saved = ledger.record_artifact.call_args.args[1]
        self.assertEqual(saved['response']['text'], raw)
        self.assertEqual(saved['response']['parsed']['claims'][1], 42)

    def test_default_required_facts_match_the_two_part_question(self):
        case = default_cases()[2]
        self.assertEqual({fact['id'] for fact in case.facts},
                         {'effective_date', 'additional_rate'})
        self.assertEqual(case.policy_reference['review_status'],
                         'pending_independent_human_review')


if __name__ == '__main__':
    unittest.main()
