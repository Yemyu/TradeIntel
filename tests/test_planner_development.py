import io
import json
from pathlib import Path
import tempfile
import unittest
from scripts.run_planner_development import run,preflight


class PlannerRunTests(unittest.TestCase):
    def test_mock_six_calls_no_confirmation_or_reference_payload(self):
        _,cases=preflight();seen=[]
        def opener(request,**kwargs):
            payload=json.loads(request.data);q=payload['messages'][1]['content'];seen.append(q)
            self.assertEqual(len(payload['messages']),2);self.assertNotIn('tools',payload)
            c=next(c for c in cases if c['question']==q)
            steps=[]
            for req in c['expected'] or []:
                ev={'task':q}
                if req['task']=='trade':ev.update({'request.'+k:q for k in req['request']})
                if req['task']=='comparison':ev['comparison_id']=q
                steps.append(dict(status='proposal',request=req,evidence=ev,missing=[]))
            obj=dict(status='plan' if steps else 'clarify',steps=steps,missing=[] if steps else ['months'])
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(obj)}}]}).encode())
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'run.json'
            r=run(execute=True,api_key='test-secret',opener=opener,output=path,claim_dir=Path(d)/'claims')
            self.assertEqual(r['exact_matches'],6);self.assertEqual(len(set(seen)),6)
            self.assertNotIn('test-secret',path.with_suffix('.jsonl').read_text())
            self.assertTrue(all(not q['result']['executed'] for q in json.loads(path.read_text())['questions']))

    def test_transport_stops_at_one(self):
        def fail(*args,**kwargs):raise ConnectionResetError('secret')
        with tempfile.TemporaryDirectory() as d:
            r=run(execute=True,api_key='secret',opener=fail,output=Path(d)/'r.json',claim_dir=Path(d)/'claims')
            self.assertEqual(r['api_requests'],1);self.assertEqual(r['status'],'stopped')
