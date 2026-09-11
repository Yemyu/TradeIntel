import unittest
from unittest.mock import patch

from scripts.check_business_delivery import ARCHIVE, check_delivery
from src.tradeintel_ai.analysis_planner_v2 import AnalysisPlannerV2


@unittest.skipUnless(ARCHIVE.exists(), 'Local archived response required for integration test')
class BusinessDeliveryTests(unittest.TestCase):
    def test_real_local_report_no_network(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('No network allowed')):
            audit, report = check_delivery()
        self.assertTrue(audit['passed'])
        self.assertEqual(len(audit['checks']), 12)
        self.assertEqual(audit['new_api_calls'], 0)
        self.assertFalse(audit['coverage_review_tested'])
        self.assertIn('未调用 API', report)
        self.assertIn('当前能力边界', report)

    def test_failed_execution_not_passed(self):
        with patch.object(AnalysisPlannerV2, 'confirm', return_value={'status': 'incomplete', 'results': []}):
            audit, report = check_delivery()
        self.assertFalse(audit['passed'])
        self.assertFalse(audit['checks']['complete_report'])
        self.assertEqual(report, '')

    def test_wrong_plan_does_not_execute(self):
        with patch.object(AnalysisPlannerV2, 'propose', return_value={
            'status': 'needs_review', 'executed': False, 'steps': []
        }), patch.object(AnalysisPlannerV2, 'confirm') as confirm:
            audit, report = check_delivery()
        confirm.assert_not_called()
        self.assertFalse(audit['passed'])
        self.assertEqual(report, '')
