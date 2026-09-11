import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from audit_causal_comparison_support import audit, summarize


class ComparisonSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = audit()

    def test_full_candidate_reconciliation(self):
        self.assertEqual(self.result['candidate_count'], 243)
        self.assertEqual(self.result['mixed_naics6_count'], 16)
        self.assertEqual(len({r['hts8'] for r in self.result['candidates']}), 243)

    def test_mixed_classification_not_forced(self):
        for key in ['by_naics6', 'by_naics6_and_hts4']:
            self.assertEqual(sum(g[role]['hts8_count'] for g in self.result[key]
                                 for role in ['treated', 'control']), 227)

    def test_no_hidden_causal_success(self):
        for key in ['matching_run', 'causal_effect_estimated', 'policy_post_outcomes_read']:
            self.assertFalse(self.result[key])

    def test_independent_family_not_child_count(self):
        rows = [{'hts8': code, 'role': 'treated'} for code in ['12345601', '12345602']]
        group = summarize(rows, lambda _: 'group')[0]
        self.assertEqual(group['treated']['hts8_count'], 2)
        self.assertEqual(group['treated']['hs6_family_count'], 1)
        self.assertFalse(group['both_sides_present'])

    def test_cross_classification_support_not_invented(self):
        both = [g['group'] for g in self.result['by_naics6_and_hts4'] if g['both_sides_present']]
        self.assertEqual(both, ['333241/8438', '333414/8416', '333511/8480', '333991/8467', '333997/8423'])


if __name__ == '__main__':
    unittest.main()
