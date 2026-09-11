import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.preflight_research_plan_acceptance import preflight


class ResearchPlanAcceptanceTests(unittest.TestCase):
    def test_frozen_set_has_expected_split(self):
        report = preflight()
        self.assertEqual(report['question_count'], 24)
        self.assertEqual(report['counts'], {'answerable': 12, 'clarification': 6, 'boundary': 6})
        self.assertEqual(report['model_calls'], 0)
        self.assertFalse(report['online_run'])

    def test_ids_are_disjoint_and_complete(self):
        report = preflight()
        all_ids = report['answerable_ids'] + report['clarification_ids'] + report['boundary_ids']
        self.assertEqual(len(all_ids), 24)
        self.assertEqual(len(set(all_ids)), 24)

    def test_hashes_are_present(self):
        self.assertEqual(set(preflight()['sha256']), {'questions', 'reference', 'unified_research'})


if __name__ == '__main__':
    unittest.main()
