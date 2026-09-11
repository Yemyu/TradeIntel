import json
import unittest
from unittest.mock import Mock,patch
from src.tradeintel_ai.intent_guarded import propose_guarded, capability_feedback, GUARDED_PROMPT


def model(request,question):
    evidence={'task':question,**{'request.'+k:question for k in request['request']}}
    text=json.dumps({'status':'proposal','request':request,'evidence':evidence,'missing':[]})
    return Mock(complete=Mock(return_value={'text':'```json\n'+text+'\n```','metadata':{'finish_reason':'stop'}}))


class GuardedTests(unittest.TestCase):
    def request(self,**changes):
        return {'task':'trade','request':dict(policy_id='us_301_list1_2018',operation='read',metric='import_value_consumption_usd',
            origin='China',granularity='policy_aggregate',months=['2017-08'],hs6=None,causal_effect=False,**changes)}

    def test_explicit_delete_and_company_refused_without_amount_query(self):
        for field,value in (('operation','delete'),('granularity','company'),('metric','import_quantity')):
            req=self.request();req['request'][field]=value;m=model(req,'明确的请求')
            with patch('src.tradeintel_ai.evidence_v21.trade_v21',side_effect=AssertionError('no amounts')):
                parsed=propose_guarded('明确的请求',m);result=capability_feedback(parsed)
            self.assertEqual(result['status'],'interpreted_refusal')
            self.assertIn(value,result['response']);self.assertFalse(result['executed'])
            self.assertEqual(m.complete.call_args.kwargs['messages'][0]['content'],GUARDED_PROMPT)
            self.assertTrue(result['capability_sources'])

    def test_supported_request_still_needs_confirmation(self):
        req=self.request();parsed=propose_guarded('明确的请求',model(req,'明确的请求'))
        result=capability_feedback(parsed)
        self.assertEqual(result['status'],'needs_confirmation');self.assertFalse(result['intent_verified'])
        self.assertIn('whole_json_fence_removed',result['format_transformations'])

    def test_invented_quote_still_fails(self):
        result=propose_guarded('实际请求',model(self.request(),'实际...请求'))
        self.assertEqual(result['parse_outcome'],'parse_failure')
        self.assertNotIn('capability_assessment',capability_feedback(result))
