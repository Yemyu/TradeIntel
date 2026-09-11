import json
import unittest
from unittest.mock import Mock
from src.tradeintel_ai.intent_catalog import propose_catalog, CATALOG
from src.tradeintel_ai.structured_workflow import execute_request


class CatalogTests(unittest.TestCase):
    def test_prompt_replacement_keeps_original_question_and_validator(self):
        question='看看匹配是否能支持因果解释'
        response={'text':json.dumps({'status':'proposal','request':{'task':'readiness'},
                   'evidence':{'task':question},'missing':[]}), 'metadata':{'finish_reason':'stop'}}
        model=Mock(complete=Mock(return_value=response))
        result=propose_catalog(question,model)
        self.assertEqual(result['version'],'intent-catalog-1')
        self.assertFalse(result['executed']);self.assertFalse(result['intent_verified'])
        kwargs=model.complete.call_args.kwargs
        self.assertEqual(kwargs['messages'][0]['content'],CATALOG)
        self.assertEqual(kwargs['messages'][1]['content'],question)
        self.assertEqual(kwargs['tools'],[])
        self.assertEqual(execute_request(result['request'])['status'],'evidence_ready')

    def test_forged_quote_still_rejected(self):
        model=Mock(complete=Mock(return_value={'text':json.dumps({'status':'proposal','request':{'task':'quality'},
             'evidence':{'task':'not in original'},'missing':[]}), 'metadata':{'finish_reason':'stop'}}))
        self.assertEqual(propose_catalog('查质量',model)['parse_outcome'],'parse_failure')
