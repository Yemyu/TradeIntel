import io
import json
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from scripts.run_intent_holdout import preflight, run, ROOT
from src.tradeintel_ai.intent_proposal import validate_candidate


class HoldoutTests(unittest.TestCase):
    def test_composition_unique_cases_and_references(self):
        _,cases=preflight()
        self.assertEqual(len(cases),48)
        self.assertEqual(len({(c['id'],c['repeat']) for c in cases}),48)
        refs=json.loads((ROOT/'evals/intent_holdout_reference.json').read_text())
        self.assertEqual(Counter(r['category'] for r in refs.values()),
                         {'single':6,'clarify':4,'negation':4,'unsupported':4,'trade':6})
        old=json.loads((ROOT/'evals/intent_development_cases.json').read_text())
        self.assertFalse({c['question'] for c in cases}&{c['question'] for c in old})
        for c in cases:
            req=c['expected']
            if req is None:continue
            evidence={'task':c['question']}
            if req['task']=='trade':evidence.update({'request.'+k:c['question'] for k in req['request']})
            elif req['task']=='comparison':evidence['comparison_id']=c['question']
            self.assertTrue(validate_candidate({'status':'proposal','request':req,'evidence':evidence,'missing':[]},c['question']))

    def test_semantic_errors_do_not_stop_and_payload_has_no_gold(self):
        def opener(request,**kwargs):
            payload=json.loads(request.data)
            self.assertNotIn('tools',payload)
            self.assertEqual(set(payload),{'model','messages','temperature','thinking','max_tokens'})
            self.assertEqual(len(payload['messages']),2)
            self.assertNotIn('expected',payload['messages'][1]['content'])
            body={'status':'clarify','request':None,'evidence':{},'missing':['task']}
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(body)}}]}).encode())
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.json';result=run(execute=True,api_key='test-only',output=path,opener=opener)
            self.assertEqual(result['api_requests'],48);self.assertEqual(result['exact_matches'],8)
            report=json.loads(path.read_text());self.assertEqual(len(report['questions']),48)
            self.assertFalse(report['model_adopted'])

    def test_first_http_failure_counts_attempt_and_stops(self):
        def opener(request,**kwargs):raise HTTPError(request.full_url,401,'secret',{},None)
        with tempfile.TemporaryDirectory() as d:
            result=run(execute=True,api_key='test-only',output=Path(d)/'test.json',opener=opener)
            self.assertEqual(result['api_requests'],1);self.assertEqual(result['status'],'stopped')
