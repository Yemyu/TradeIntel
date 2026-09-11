import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_comparison_families import summarize


class ComparisonFamilyTests(unittest.TestCase):
    def test_ambiguous_not_assigned(self):
        self.assertEqual(summarize([{'hs6':'850421','naics6':['1','2'],'role':'treated'}]), {})

    def test_proposed_controls_stay_separate(self):
        rows = [{'hs6':'850421','naics6':['335311'],'role':role}
                for role in ['treated','proposal_control','nonproposal_control']]
        self.assertEqual(summarize(rows)['335311:8504'],
                         {'treated':1,'proposal_control':1,'nonproposal_control':1})

    def test_different_headings_not_pooled(self):
        rows = [{'hs6':code,'naics6':['333997'],'role':'treated'} for code in ['842310','842410']]
        self.assertEqual(len(summarize(rows)), 2)
