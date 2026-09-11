import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from preflight_policy_acceptance import inspect_cases


class PreflightTests(unittest.TestCase):
    def case(self):return {'id':'P1','question':'q','as_of':'2018-07-06','expected':'no_evidence'}
    def test_boundary_violation_is_not_acceptance(self):
        retriever=Mock()
        retriever.search.return_value={'status':'candidate_evidence','hits':[{'id':'x'}]}
        r=inspect_cases([self.case()],retriever)
        self.assertFalse(r['boundary_preflight_passed'])
        self.assertEqual(r['new_api_calls'],0)
        self.assertEqual(r['semantic_acceptance'],'not_run')
    def test_duplicate_cases_rejected(self):
        retriever=Mock()
        retriever.search.return_value={'status':'no_evidence','hits':[]}
        with self.assertRaises(ValueError):inspect_cases([self.case(),self.case()],retriever)
