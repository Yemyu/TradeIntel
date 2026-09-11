import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.policy_workflow import run_generation,safe_metadata


class WorkflowTests(unittest.TestCase):
    def evidence(self):
        return {'question':'q','as_of':'2018-07-06','hits':[
            {'id':'a','title':'fixture','published':'2018-06-20','page':1,'text':'source'}]}

    def model(self,finish='stop'):
        model=Mock()
        model.complete.return_value=ModelResponse(text='```json\n{"claims":[{"text":"claim","citations":["a"]}]}\n```',
            metadata={'finish_reason':finish,'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30,'private':'secret'}})
        return model

    def test_live_normalization_audit_and_no_overwrite(self):
        model=self.model()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'run'
            result=run_generation(model,self.evidence(),p)
            self.assertEqual(result['generation']['status'],'draft_requires_semantic_review')
            self.assertEqual(result['audit']['format_changes'],['whole_json_fence_removed'])
            self.assertEqual(result['audit']['new_api_calls'],1)
            self.assertNotIn('private',result['audit']['provider']['usage'])
            self.assertIn('```',(p/'raw_response.json').read_text())
            self.assertNotIn('```',(p/'normalized_response.json').read_text())
            with self.assertRaises(FileExistsError):run_generation(model,self.evidence(),p)
            self.assertEqual(model.complete.call_count,1)

    def test_live_requires_stop(self):
        for finish in ['length','content_filter',None,'unknown']:
            with tempfile.TemporaryDirectory() as t:
                r=run_generation(self.model(finish),self.evidence(),Path(t)/'r')
                self.assertEqual(r['generation']['status'],'rejected_model_output')

    def test_archive_not_new_live_and_unknown_finish_retained(self):
        with tempfile.TemporaryDirectory() as t:
            r=run_generation(self.model(None),self.evidence(),Path(t)/'r',source_kind='archived_replay')
            self.assertEqual(r['audit']['new_api_calls'],0)
            self.assertEqual(r['audit']['completion_gate'],'archive_completion_unknown')

    def test_no_evidence_no_model_call(self):
        model=Mock()
        with tempfile.TemporaryDirectory() as t:
            r=run_generation(model,{'hits':[]},Path(t)/'r')
            self.assertEqual(r['audit']['new_api_calls'],0)
            self.assertEqual(r['generation']['status'],'no_evidence')
        model.complete.assert_not_called()

    def test_error_saved_safely_and_key_redacted(self):
        with tempfile.TemporaryDirectory() as t:
            model=self.model()
            r=run_generation(model,self.evidence(),Path(t)/'r',secret='claim')
            self.assertNotIn('"claim"',(Path(t)/'r/raw_response.json').read_text())
            model.complete.side_effect=TimeoutError('do not expose')
            r=run_generation(model,self.evidence(),Path(t)/'error')
            self.assertEqual(r['audit']['diagnostic'],{'category':'timeout'})
            self.assertNotIn('do not expose',(Path(t)/'error/result.json').read_text())

    def test_metadata_whitelist(self):
        self.assertEqual(safe_metadata({'usage':{'total_tokens':True,'private':'x'}})['usage'],{})
