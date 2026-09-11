import unittest
from scripts.score_intent_holdout import aggregate


class HoldoutScoringTests(unittest.TestCase):
    def rows(self):
        return [{'repeat':n,'category':'clarify' if i<4 else 'single','recorded':True,'exact_match':True,
                 'parse_outcome':'model_clarification' if i<4 else 'validated_proposal',
                 'review':{'semantic_correct':True,'quotes_supported':True,'unsafe_scope_change':False}}
                for n in (1,2) for i in range(24)]

    def test_rounds_not_pooled_and_pending_cannot_pass(self):
        rows=self.rows();rows[0]['review']=None
        r=aggregate(rows,True)
        self.assertFalse(r['1']['gate_passed']);self.assertTrue(r['2']['gate_passed'])

    def test_bad_parse_and_unsafe_scope_fail_gate(self):
        for modify in (lambda r:r.update(parse_outcome='parse_failure'),lambda r:r['review'].update(unsafe_scope_change=True)):
            rows=self.rows();modify(rows[0]);self.assertFalse(aggregate(rows,True)['1']['gate_passed'])

    def test_22_of_24_threshold_and_complete_collection(self):
        rows=self.rows()
        for i in (5,6):rows[i]['review']['semantic_correct']=False
        self.assertTrue(aggregate(rows,True)['1']['gate_passed'])
        rows[7]['review']['semantic_correct']=False
        self.assertFalse(aggregate(rows,True)['1']['gate_passed'])
        self.assertFalse(aggregate(self.rows(),False)['1']['gate_passed'])
