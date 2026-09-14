import unittest
from src.tradeintel_ai.policy_scope_review import review_policy_scope, render_scope_review


class PolicyScopeReviewTests(unittest.TestCase):
    def evidence(self):
        return {'policy_id':'us_301_solar2024','hits':[
            {'id':'scope','text':'Applies to products of China.', 'citation_url':'https://example.test/scope'},
            {'id':'fr202421217:general_conditions','text':'General exceptions and other duties.',
             'citation_url':'https://example.test/general'}]}

    def test_missing_origin_and_uncited_general_are_visible(self):
        evidence = self.evidence()
        result = review_policy_scope([{'text':'额外50%。','citations':['scope']}], evidence)
        self.assertEqual(len(result['warnings']), 2)
        self.assertFalse(result['semantic_approval'])
        text = '\n'.join(render_scope_review(result, evidence))
        self.assertIn('General exceptions and other duties.', text)
        self.assertIn('AI解释未检测到明确原产范围', text)

    def test_mention_and_citation_are_not_semantic_approval(self):
        result = review_policy_scope([{'text':'中国原产也不受限制。',
            'citations':['scope','fr202421217:general_conditions']}], self.evidence())
        self.assertTrue(result['origin_mention_detected'])
        self.assertEqual(result['status'], 'manual_review_required')
        self.assertFalse(result['semantic_approval'])

    def test_missing_required_original_is_not_silently_skipped(self):
        evidence = self.evidence(); evidence['hits'].pop()
        result = review_policy_scope([], evidence)
        self.assertFalse(result['general_source_present'])
        self.assertTrue(any('证据不完整' in warning for warning in result['warnings']))
