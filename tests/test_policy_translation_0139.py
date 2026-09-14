import json
import unittest
from tradeintel_ai.prospective_runner import paired_policy_messages


class PolicyTranslationTests(unittest.TestCase):
    def test_shared_rule_is_evidence_independent_and_has_no_case_answer(self):
        a = paired_policy_messages('测试问题', '2000-01-01', [{'id': 'source', 'text': 'example'}])
        b = paired_policy_messages('测试问题', '2000-01-01', [])
        self.assertEqual(a[0], b[0])
        for rule in ('24小时制', '原文时区', '额外税率不是总税率', '原产地'):
            self.assertIn(rule, a[0]['content'])
        for answer in ('2018', '25%', 'July 6', '00:01'):
            self.assertNotIn(answer, a[0]['content'])
        left, right = json.loads(a[1]['content']), json.loads(b[1]['content'])
        left.pop('evidence'); right.pop('evidence')
        self.assertEqual(left, right)
