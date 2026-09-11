import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import audit_frozen_causal_design as audit


class FrozenCausalAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Make the no-optimizer promise executable, not just a comment.
        with patch.object(audit.v3, 'milp', side_effect=AssertionError('Forbidden optimizer call')):
            cls.result = audit.audit()

    def test_archived_shapes_and_nonempty_edges(self):
        self.assertTrue(self.result['matches_archived_matrix_dimensions'])
        self.assertEqual(self.result['matrix']['treated_without_edges'], [])
        self.assertEqual(self.result['matrix']['matrix_variable_count'], self.result['matrix']['solver_cost_variable_count'])

    def test_independent_formula_checks(self):
        self.assertTrue(self.result['matrix']['formula_check_passed'])
        self.assertLess(self.result['maximum_smd_difference_from_archive'], 1e-9)

    def test_pooled_sd_weights_degrees_of_freedom(self):
        # Within-group sums of squares are 2 and 32; total degrees of freedom 3.
        self.assertAlmostEqual(audit.pooled_sd([0, 2], [0, 4, 8]), (34 / 3) ** .5)

    def test_no_fitting_or_input_mutation(self):
        self.assertEqual(self.result['optimization_calls'], 0)
        self.assertEqual(self.result['effect_estimation_calls'], 0)
        self.assertFalse(self.result['old_results_modified'])
        import hashlib
        for path, digest in self.result['input_sha256'].items():
            self.assertEqual(hashlib.sha256((audit.ROOT / path).read_bytes()).hexdigest(), digest)

    def test_eligible_pre_rows_complete(self):
        p = self.result['prepanel']
        self.assertEqual(p['expected_rows'], 32277)
        self.assertEqual(p['present_rows'], p['expected_rows'])
        for key in ('missing_keys', 'duplicate_keys', 'blank_value_keys'):
            self.assertEqual(p[key], [])

    def test_missing_blank_duplicate_are_not_hidden(self):
        fields = ['hs6_2017', 'year', 'month', 'china_import_value_consumption_usd', 'all_origin_import_value_consumption_usd']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.csv'
            with path.open('w', newline='') as handle:
                w = csv.writer(handle); w.writerow(fields)
                w.writerow(['123456', 2016, 1, '', 5]); w.writerow(['123456', 2016, 1, 0, 5])
                # Invalid post amounts must not be read or parsed by the audit.
                w.writerow(['123456', 2018, 6, 'not a number', 'not a number'])
            r = audit.prepanel_audit(path, {'123456'})
            self.assertEqual(len(r['missing_keys']), 28)
            self.assertEqual(len(r['blank_value_keys']), 1)
            self.assertEqual(len(r['duplicate_keys']), 1)


if __name__ == '__main__':
    unittest.main()
