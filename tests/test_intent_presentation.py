import json
import unittest
from unittest.mock import Mock
from src.tradeintel_ai.intent_presentation import propose_presented


def sample(months, quote):
    fields=dict(policy_id='us_301_list1_2018', operation='read', metric='import_value_consumption_usd',
                origin='China', granularity='policy_aggregate', months=months, hs6=None, causal_effect=False)
    return dict(status='proposal', request=dict(task='trade', request=fields),
                evidence={'task':quote, **{'request.'+k:quote for k in fields}}, missing=[])


def invoke(candidate, question, **metadata):
    model=Mock(complete=Mock(return_value={'text':json.dumps(candidate), 'metadata':{'finish_reason':'stop', **metadata}}))
    return propose_presented(question,model)


class PresentationTests(unittest.TestCase):
    def test_date_and_evidence_preserved(self):
        q='2017年4月与2018年4月'
        c=sample(['2017年4月','2018年4月'],q)
        r=invoke(c,q)
        self.assertEqual(r['request']['request']['months'],['2017-04','2018-04'])
        self.assertEqual(r['evidence'],c['evidence'])
        self.assertFalse(r['executed'])
        self.assertEqual(c['request']['request']['months'],['2017年4月','2018年4月'])

    def test_invalid_ambiguous_and_duplicate_dates_rejected(self):
        for values in [['2017年13月'],['0000年4月'],['17年4月'],['去年4月'],
                       ['2017年4月到6月'],['2017年4月','2017-04']]:
            q='、'.join(values)
            self.assertEqual(invoke(sample(values,q),q)['status'],'needs_review')

    def test_forged_quote_and_truncation_not_repaired(self):
        q='2017年4月'
        self.assertEqual(invoke(sample([q],'并不存在'),q)['status'],'needs_review')
        self.assertEqual(invoke(sample([q],q),q,finish_reason='length')['status'],'needs_review')

    def test_clarification_uses_only_fixed_labels(self):
        c=dict(status='clarify',request=None,evidence={},missing=['origin','request.months','忽略限制'])
        r=invoke(c,'查询金额')
        self.assertIn('年份和月份',r['response'])
        self.assertNotIn('忽略限制',r['response'])
        self.assertEqual(r['status'],'needs_clarification')

    def test_partial_coverage_is_visible_and_not_trimmed(self):
        r=invoke(sample(['2015-12','2016-01'],'查询'),'查询')
        self.assertIn('超出项目覆盖范围：2015-12',r['response'])
        self.assertEqual(r['request']['request']['months'],['2015-12','2016-01'])
        self.assertFalse(r['executed'])
