import json
import tempfile
import unittest
from pathlib import Path
from tradeintel_ai.structured_task import compile_task
from tradeintel_ai.agent import ModelResponse
from scripts.run_solar_brief_pilot import run

class StructuredTaskTests(unittest.TestCase):
    def task(self,month='2026-07'):
        return dict(policy_id='us_301_solar2024',month=month,product='all',task='source_and_investigation')
    def test_invalid_parameters(self):
        for key,value in [('month','2026-13'),('product',None),('product','81019400'),('policy_id','unknown'),('task','forecast')]:
            item=self.task(); item[key]=value
            with self.assertRaises(ValueError): compile_task(item)
        with self.assertRaises(ValueError): compile_task({**self.task(),'sql':'SELECT 1'})
    def test_single_explanation_no_model_plan(self):
        seen=[]
        class Fixture:
            def complete(self,**kwargs):
                seen.append(kwargs)
                return ModelResponse(text=json.dumps({'notes':[{'kind':'investigation','fact_ids':['policy.entry_events'],
                    'text':'需核查实际入境事件，以判断是否落入公告适用范围。'}]},ensure_ascii=False))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'run'
            result=run(root,Fixture(),structured_task=self.task())
            self.assertEqual(result['status'],'interpretation_needs_review')
            self.assertEqual(result['model_calls'],1)
            self.assertEqual(result['planning_source'],'explicit_user_parameters')
            self.assertEqual(len(seen),1)
            content=json.loads(seen[0]['messages'][1]['content'])
            values={f['id']:f['value'] for f in content['facts']}
            self.assertEqual(values['trade.2026-07.85414200']['all_origins_value_usd'],360659187)
            context=json.loads((root/'run/interpretation-trade-context.json').read_text())
            self.assertEqual(context['data_version'],result['data_version'])
            self.assertFalse((root/'run/plan-response.json').exists())
            self.assertEqual(json.loads((root/'freeze.json').read_text())['max_calls'],1)
            packet=(root/'run/source-packet.zh-CN.md').read_text()
            self.assertIn('360,659,187',packet)
    def test_outside_window_calls_no_model(self):
        class Never:
            def complete(self,**kwargs): raise AssertionError('must not call')
        with tempfile.TemporaryDirectory() as folder:
            result=run(Path(folder)/'run',Never(),structured_task=self.task('2024-07'))
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['model_calls'],0)
