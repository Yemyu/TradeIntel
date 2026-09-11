import unittest
from unittest.mock import patch
import numpy as np
from scripts.check_prepolicy_trajectory import evaluate, fit, predict


class TrajectoryTests(unittest.TestCase):
    def test_weight_constraints(self):
        X=np.arange(240,dtype=float).reshape(12,20)/240
        w=fit(X,X.mean(axis=1))
        self.assertAlmostEqual(sum(w),1)
        self.assertLessEqual(max(w),.1000001)
        self.assertTrue(np.allclose(predict(X,w),X.mean(axis=1),atol=1e-5))

    def test_validation_targets_do_not_enter_fits(self):
        X=np.zeros((29,20)); y=np.zeros(29); y[24:]=100
        with patch('scripts.check_prepolicy_trajectory.fit',side_effect=lambda x,t:np.ones(x.shape[1])/x.shape[1]) as f:
            r=evaluate(X,y)
        self.assertEqual(f.call_count,2)
        for call in f.call_args_list:
            self.assertEqual(len(call.args[1]),24)
            self.assertTrue(np.all(call.args[1]==0))
        self.assertFalse(r['proceed_to_research_design'])

    def test_invalid_training_data_rejected(self):
        with self.assertRaises(ValueError):fit(np.full((24,20),np.nan),np.zeros(24))
