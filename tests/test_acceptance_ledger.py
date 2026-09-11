import unittest
from src.tradeintel_ai.acceptance_ledger import AcceptanceLedger


class AcceptanceLedgerTests(unittest.TestCase):
    def test_duplicate_and_after_stop_are_rejected(self):
        ledger = AcceptanceLedger(['R01', 'R02'], max_planning=2, max_answers=1)
        ledger.record('R01', terminal_status='needs_confirmation',
                      expected_status='plan', answer_attempted=True)
        with self.assertRaises(ValueError):
            ledger.record('R01', terminal_status='again', expected_status='plan')
        ledger.stop('provider_error')
        with self.assertRaises(RuntimeError):
            ledger.record('R02', terminal_status='needs_review',
                          expected_status='needs_review')

    def test_budgets_and_summary_are_explicit(self):
        ledger = AcceptanceLedger(['R01'], max_planning=1, max_answers=0)
        ledger.record('R01', terminal_status='needs_review',
                      expected_status='needs_review')
        summary = ledger.summary()
        self.assertEqual(summary['total_model_calls'], 1)
        self.assertEqual(summary['status'], 'collected')
        self.assertEqual(summary['remaining_questions'], 0)

    def test_unknown_id_and_answer_budget(self):
        ledger = AcceptanceLedger(['R01'], max_planning=1, max_answers=0)
        with self.assertRaises(ValueError):
            ledger.record('R02', terminal_status='x', expected_status='x')
        with self.assertRaises(ValueError):
            ledger.record('R01', terminal_status='x', expected_status='x',
                          answer_attempted=True)


if __name__ == '__main__':
    unittest.main()
