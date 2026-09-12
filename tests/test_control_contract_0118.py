"""Executable counterexamples for the paired evaluation design; no API calls."""
from copy import deepcopy
import unittest
from tradeintel_ai.prospective_acceptance import (
    AcceptanceGuardError, compare_trade_scope, validate_policy_pair,
)
from tests.test_trade_mapping_proposal_0105 import candidate


class ControlContractTests(unittest.TestCase):
    def request(self):
        plan = candidate()
        return {key: plan[key] for key in ('trade', 'comparison')}

    def test_wrong_origin_and_reversed_comparison_are_rejected_without_repair(self):
        expected = self.request()
        actual = deepcopy(expected)
        actual['trade']['origin'] = 'China'
        actual['comparison']['reference_month'], actual['comparison']['current_month'] = (
            actual['comparison']['current_month'], actual['comparison']['reference_month'])
        before = deepcopy(actual)
        result = compare_trade_scope(expected, actual)
        self.assertFalse(result['scope_equal'])
        self.assertEqual(result['differences'], ['trade.origin', 'comparison'])
        self.assertEqual(actual, before)

    def test_month_set_order_is_irrelevant_but_omissions_and_duplicates_are_not(self):
        expected = self.request()
        actual = deepcopy(expected)
        actual['trade']['months'].reverse()
        self.assertTrue(compare_trade_scope(expected, actual)['scope_equal'])
        actual['trade']['months'].pop()
        self.assertFalse(compare_trade_scope(expected, actual)['scope_equal'])
        actual['trade']['months'] *= 2
        with self.assertRaises(AcceptanceGuardError):
            compare_trade_scope(expected, actual)

    def config(self):
        return dict(question='synthetic policy question', as_of='2018-07-06',
                    base_url='https://example.invalid/v1', model='fixture-model',
                    temperature=0.0, max_tokens=768, thinking={'type': 'disabled'},
                    stream=False, timeout_seconds=60, response_schema_sha256='fixture-schema')

    def test_pair_requires_same_model_question_and_generation_configuration(self):
        expected = self.config()
        self.assertTrue(validate_policy_pair(expected, deepcopy(expected))['configuration_equal'])
        for key, value in [('model', 'different'), ('question', 'reworded'),
                           ('max_tokens', 512), ('temperature', 1.0),
                           ('response_schema_sha256', 'different')]:
            with self.subTest(key=key), self.assertRaises(AcceptanceGuardError):
                validate_policy_pair(expected, {**expected, key: value})

    def test_incomplete_settings_or_credentials_cannot_be_silently_compared(self):
        expected = self.config()
        for key in expected:
            incomplete = deepcopy(expected)
            del incomplete[key]
            with self.subTest(key=key), self.assertRaises(AcceptanceGuardError):
                validate_policy_pair(incomplete, incomplete)
        with self.assertRaises(AcceptanceGuardError):
            validate_policy_pair({**expected, 'api_key': 'fixture'}, expected)
