import unittest
from src.tradeintel_ai.business_workflow import report_delivery


class ReportDeliveryTests(unittest.TestCase):
    def test_clean_checks_never_mean_approved(self):
        result = report_delivery({'data_version':'version'})
        self.assertEqual(result['status'], 'manual_review_required')
        self.assertFalse(result['approved'])

    def test_each_incomplete_boundary_is_visible(self):
        for field, value in [('data_version', None),
                             ('policy_conditions_status','needs_evidence'),
                             ('scope_review_status','needs_scope_review'),
                             ('comparison_status','comparability_unreviewed')]:
            result = report_delivery({'data_version':'version', field:value})
            self.assertEqual(result['status'], 'needs_completion')
            self.assertEqual(len(result['reasons']),1)
            self.assertFalse(result['approved'])
