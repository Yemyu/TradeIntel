import unittest

from tradeintel_ai.provider_executor import output_budget
from tests import test_provider_executor_hardening as hardening


class OutputBudgetTests(unittest.TestCase):
    def test_actual_replaces_overestimate(self):
        result = output_budget('中文' * 500, {'completion_tokens': 818})
        self.assertGreater(result['estimate']['tokens'], 2000)
        self.assertTrue(result['within_gate'])
        self.assertEqual(result['method'], 'provider_completion_tokens')

    def test_actual_boundary(self):
        self.assertTrue(output_budget('ok', {'completion_tokens': 2000})['within_gate'])
        self.assertFalse(output_budget('ok', {'completion_tokens': 2001})['within_gate'])

    def test_missing_or_malformed_uses_estimate(self):
        for usage in (None, [], {}, {'completion_tokens': True}, {'completion_tokens': -1},
                      {'completion_tokens': 0}, {'completion_tokens': '818'},
                      {'completion_tokens': 818.0}):
            with self.subTest(usage=usage):
                result = output_budget('中文' * 500, usage)
                self.assertEqual(result['method'], 'fallback_estimate')
                self.assertFalse(result['within_gate'])

    def test_byte_guard_cannot_be_bypassed_by_usage(self):
        self.assertFalse(output_budget('x' * 65537, {'completion_tokens': 1})['within_gate'])


class OutputBudgetIntegrationTests(hardening.ExecutorHardeningTests):
    def test_realistic_usage_passes_budget_not_semantic_review(self):
        result = self.run_case('measured', lambda **kw: ('中文' * 500, {'completion_tokens': 818}))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['manifest']['validation_status'], 'free_form_manual_review_required')
        self.assertEqual(result['manifest']['output_budget']['tokens'], 818)
