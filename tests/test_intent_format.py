import json
import unittest
from src.tradeintel_ai.intent_format import normalize_response
from src.tradeintel_ai.intent_catalog import propose_catalog
from scripts.check_intent_development import RecordedModel


def raw(text):return {'text':text,'metadata':{'finish_reason':'stop'}}


class FormatTests(unittest.TestCase):
    def test_whole_fence_only(self):
        text=json.dumps({'status':'clarify','request':None,'evidence':{},'missing':['scope']})
        response,changes=normalize_response(raw('```json\n'+text+'\n```'))
        self.assertEqual(json.loads(response.text),json.loads(text));self.assertTrue(changes)
        for bad in ('说明\n```json\n'+text+'\n```','```json\n'+text+'\n```\n解释',text+' '+text):
            r,c=normalize_response(raw(bad));self.assertEqual(r.text,bad);self.assertEqual(c,[])

    def test_alias_preserves_quote_and_conflict_stays_invalid(self):
        obj={'status':'proposal','request':{'task':'comparison','comparison_id':'immediate_post_same_months'},
             'evidence':{'task':'比较','request.comparison_id':'immediate_post_same_months'},'missing':[]}
        r,c=normalize_response(raw(json.dumps(obj)))
        normalized=json.loads(r.text)
        self.assertEqual(normalized['request'],obj['request'])
        self.assertEqual(normalized['evidence']['comparison_id'],obj['evidence']['request.comparison_id'])
        obj['evidence']['comparison_id']='conflict';r,c=normalize_response(raw(json.dumps(obj)))
        self.assertEqual(c,[])

    def test_fabricated_quote_not_repaired(self):
        obj={'status':'proposal','request':{'task':'counts'},'evidence':{'task':'请...解释'},'missing':[]}
        r,_=normalize_response(raw('```json\n'+json.dumps(obj)+'\n```'))
        result=propose_catalog('请解释商品数量',RecordedModel(r))
        self.assertEqual(result['parse_outcome'],'parse_failure')

    def test_duplicate_json_keys_remain_rejected(self):
        text='```json\n{"status":"clarify","status":"proposal"}\n```'
        r,c=normalize_response(raw(text));self.assertEqual(c,[]);self.assertEqual(r.text,text)
