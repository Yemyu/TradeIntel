import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from diagnose_joint_support import joint_residual, balanced_mean


class JointSupportTests(unittest.TestCase):
    def test_marginal_pass_can_fail_joint_support(self):
        controls = np.array([[0.,0.],[1.,1.]])
        self.assertGreater(joint_residual(controls, [0.,1.]), .1)

    def test_mixture_not_single_neighbor_can_fit(self):
        self.assertLess(joint_residual([[0.,0.],[1.,1.]], [.5,.5]), 1e-7)

    def test_zero_spread_mismatch(self):
        self.assertAlmostEqual(joint_residual([[1.,0.],[1.,1.]], [2.,.5]), 1.)

    def test_mean_balance_needs_concentration(self):
        result = balanced_mean([[0.],[1.]], [[.9],[.9]], tolerance=0.)
        self.assertTrue(result['feasible'])
        self.assertAlmostEqual(result['minimum_maximum_weight'], .9)

    def test_mean_outside_hull_is_infeasible(self):
        self.assertFalse(balanced_mean([[0.],[1.]], [[2.],[2.]], tolerance=0.)['feasible'])
