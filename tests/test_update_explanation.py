import json
import tempfile
import unittest
from pathlib import Path
from src.tradeintel_ai.agent import ModelResponse
from src.tradeintel_ai.update_explanation import run
from tests.test_update_brief import snapshot, month


class UpdateExplanationTests(unittest.TestCase):
    def test_model_gets_both_versions_and_exact_values(self):
        before=snapshot({'2026-06':month()})
        after=snapshot({'2026-06':month(),'2026-07':month(200,30)})
        seen=[]
        class Model:
            def complete(self,**kwargs):
                seen.append(json.loads(kwargs['messages'][1]['content']))
                return ModelResponse(text=json.dumps({'notes':[{'fact_ids':['update.month.2026-07'],
                    'text':'可补入新月份，但企业价格判断仍需合同信息。'}]}))
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'run';result=run(before,after,output,Model())
            self.assertEqual(result['status'],'manual_review_required')
            self.assertEqual(seen[0]['facts'][-1]['value']['after']['metrics']['china_value_usd'],30)
            self.assertEqual(seen[0]['before_version'],before['version'])
            with self.assertRaises(FileExistsError):run(before,after,output,Model())
            self.assertEqual(len(seen),1)

    def test_unchanged_skips_model(self):
        state=snapshot({'2026-06':month()})
        with tempfile.TemporaryDirectory() as folder:
            result=run(state,state,Path(folder)/'run',None)
            self.assertEqual(result['attempts'],0)

    def test_invalid_reference_preserves_raw_response_and_stops(self):
        before=snapshot({'2026-06':month()});after=snapshot({'2026-06':month(90,20)})
        class Model:
            def complete(self,**kwargs):
                return ModelResponse(text='{"notes":[{"fact_ids":["invented"],"text":"bad"}]}')
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'run';result=run(before,after,output,Model())
            self.assertEqual(result['status'],'failed');self.assertEqual(result['attempts'],1)
            self.assertTrue((output/'response.json').is_file())
            self.assertFalse((output/'explanation.zh-CN.md').exists())
            self.assertEqual(result['diagnostic']['code'],'unknown_evidence_reference')

    def test_boundary_is_explicitly_citable_and_shares_defined(self):
        before=snapshot({'2026-06':month()});after=snapshot({'2026-06':month(90,20)})
        class Model:
            def complete(inner,**kwargs):
                facts={f['id']:f['value'] for f in json.loads(kwargs['messages'][1]['content'])['facts']}
                self.assertIn('update.boundary',facts)
                self.assertEqual(len(facts['update.scope']['share_definitions']),3)
                return ModelResponse(text='{"notes":[{"fact_ids":["update.boundary"],"text":"企业税负需要税单证据。"}]}')
        with tempfile.TemporaryDirectory() as folder:
            result=run(before,after,Path(folder)/'run',Model())
            self.assertEqual(result['status'],'manual_review_required')
            self.assertFalse(result['approved'])
