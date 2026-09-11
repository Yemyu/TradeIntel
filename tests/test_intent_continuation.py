import io
import json
from pathlib import Path
import tempfile
import unittest
from scripts.run_intent_continuation import run, ROOT, preflight, safe_error
from urllib.error import URLError, HTTPError
from http.client import IncompleteRead


class ContinuationTests(unittest.TestCase):
    def test_error_classification_never_uses_exception_text(self):
        for exc,category in [(URLError(TimeoutError('test-secret')),'timeout'),
                             (IncompleteRead(b'test-secret',12),'incomplete_read'),
                             (HTTPError('test-secret',429,'test-secret',{},None),'http')]:
            result=safe_error(exc)
            self.assertEqual(result['category'],category)
            self.assertNotIn('test-secret',json.dumps(result))

    def test_scope_excludes_every_prior_attempt(self):
        _,cases=preflight()
        self.assertEqual(len(cases),23)
        self.assertNotIn('D10',{c['id'] for c in cases})
        self.assertEqual(cases[0]['id'],'D11')

    def test_transport_stops_and_claim_blocks_repeat(self):
        def opener(*args,**kwargs):
            raise ConnectionResetError('test-secret')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'run.json'
            result=run(execute=True,api_key='test-secret',output=path,opener=opener,claim_dir=Path(d)/'claims')
            self.assertEqual(result['api_requests'],1)
            self.assertEqual(result['status'],'stopped')
            self.assertNotIn('test-secret',path.with_suffix('.jsonl').read_text())
            self.assertIn('connection_reset',path.with_suffix('.jsonl').read_text())
            with self.assertRaises(ValueError):
                run(execute=True,api_key='test-secret',output=Path(d)/'second.json',opener=opener,claim_dir=Path(d)/'claims')

    def test_correct_mock_completes_without_duplicate_pilot_calls(self):
        _,cases=preflight()
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
            path=Path(d)/'run.json';r=run(execute=True,api_key='test-secret',output=path,opener=opener,claim_dir=Path(d)/'claims')
            self.assertEqual(r['exact_matches'],23);self.assertEqual(len(set(seen)),23)
            raw=json.loads(path.read_text());self.assertFalse(raw['model_adopted'])
            self.assertNotIn('test-secret',path.with_suffix('.jsonl').read_text())
