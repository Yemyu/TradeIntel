import io,json,tempfile,unittest
from pathlib import Path
from scripts.run_planner_v4 import run,preflight


class RunnerTests(unittest.TestCase):
    def test_two_stage_budget_and_exact_fields(self):
        _,cases=preflight()
        def opener(request,**kwargs):
            p=json.loads(request.data);content=p['messages'][1]['content']
            if content.startswith('{'):
                q=json.loads(content)['question'];c=next(c for c in cases if c['question']==q)
                obj=dict(verdict='clarify' if c['missing'] else 'accept',issue='scope' if c['missing'] else 'none',
                         quote=q if c['missing'] else '',missing=[{'field':f,'quote':q} for f in c['missing']])
            else:
                q=content;c=next(c for c in cases if c['question']==q);steps=[]
                for req in c['expected'] or []:
                    ev={'task':q}
                    if req['task']=='trade':ev.update({'request.'+k:q for k in req['request']})
                    steps.append(dict(status='proposal',request=req,evidence=ev,missing=[]))
                obj=dict(status='plan' if steps else 'clarify',steps=steps,missing=[] if steps else ['months'])
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(obj)}}]}).encode())
        with tempfile.TemporaryDirectory() as d:
            r=run(execute=True,api_key='test-secret',output=Path(d)/'r.json',claim_dir=Path(d)/'claims',opener=opener)
            self.assertEqual(r['api_requests'],8);self.assertEqual(r['exact_matches'],4)
            rows=json.loads((Path(d)/'r.json').read_text())['questions']
            self.assertTrue(all(len(r['responses'])==2 for r in rows))

    def test_transport_no_second_call(self):
        def fail(*a,**kw):raise ConnectionResetError('test-secret')
        with tempfile.TemporaryDirectory() as d:
            r=run(execute=True,api_key='test-secret',output=Path(d)/'r.json',claim_dir=Path(d)/'claims',opener=fail)
            self.assertEqual(r['api_requests'],1)
            self.assertNotIn('test-secret',(Path(d)/'r.jsonl').read_text())
