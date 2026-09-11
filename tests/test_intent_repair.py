import io
import json
from pathlib import Path
import tempfile
import unittest
from scripts.run_intent_repair import run, ROOT


class RepairTests(unittest.TestCase):
    def test_pilot_failure_stops_at_three(self):
        def opener(request,**kwargs):
            payload=json.loads(request.data)
            self.assertEqual(payload['thinking'],{'type':'disabled'})
            self.assertEqual(payload['max_tokens'],2048)
            self.assertNotIn('tools',payload)
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}).encode())
        with tempfile.TemporaryDirectory() as d:
            r=run(execute=True,api_key='test-secret',output=Path(d)/'run.json',opener=opener)
            self.assertEqual(r['api_requests'],3)
            self.assertEqual(r['status'],'stopped')

    def test_correct_mock_completes_without_duplicate_pilot_calls(self):
        cases=json.loads((ROOT/'evals/intent_development_cases.json').read_text())
        seen=[]
        def opener(request,**kwargs):
            payload=json.loads(request.data);question=payload['messages'][1]['content'];seen.append(question)
            case=next(c for c in cases if c['question']==question);req=case['expected']
            evidence={}
            if req:
                evidence={'task':question}
                if req['task']=='trade': evidence.update({'request.'+k:question for k in req['request']})
                if req['task']=='comparison': evidence['comparison_id']=question
            body={'status':'proposal' if req else 'clarify','request':req,'evidence':evidence,'missing':[] if req else ['scope']}
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(body)}}]}).encode())
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'run.json';r=run(execute=True,api_key='test-secret',output=path,opener=opener)
            self.assertEqual(r['exact_matches'],12);self.assertEqual(len(set(seen)),12)
            raw=json.loads(path.read_text());self.assertFalse(raw['model_adopted'])
            self.assertNotIn('test-secret',path.with_suffix('.jsonl').read_text())
