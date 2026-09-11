import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from tradeintel_ai.policy_focus import FocusedPolicyModel, presentation_flags, FOCUS_RULES


class FocusTests(unittest.TestCase):
    def test_only_system_extended_no_answer_rewrite(self):
        model=Mock(); messages=[{'role':'system','content':'original'},{'role':'user','content':'unchanged evidence'}]
        snapshot=deepcopy(messages)
        result=FocusedPolicyModel(model).complete(messages=messages,tools=[])
        sent=model.complete.call_args.kwargs
        self.assertEqual(messages,snapshot)
        self.assertEqual(sent['messages'][1],messages[1])
        self.assertTrue(sent['messages'][0]['content'].startswith('original'))
        self.assertIs(result,model.complete.return_value)
        self.assertEqual(model.complete.call_count,1)
    def test_no_case_answers_in_rules(self):
        for value in ['2018','25%','9903','7月6日','8月23日']: self.assertNotIn(value,FOCUS_RULES)
    def test_review_does_not_repair_claims(self):
        g={'claims':[{'text':'第一批修订于上午12:01生效','citations':['x']}]};old=deepcopy(g)
        result=presentation_flags('税费是否叠加？',g)
        self.assertEqual(len(result['flags']),3)
        self.assertEqual(g,old)
        self.assertFalse(result['automatic_factuality_verdict'])
    def test_requested_clock_time_not_flagged_as_extra(self):
        r=presentation_flags('精确时间是什么？',{'claims':[{'text':'凌晨00:01','citations':['a']}]})
        self.assertEqual(r['flags'],[])
    def test_missing_system_fails_without_call(self):
        model=Mock()
        with self.assertRaises(ValueError):FocusedPolicyModel(model).complete(messages=[],tools=[])
        model.complete.assert_not_called()
