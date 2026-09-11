import json
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock,patch
from src.tradeintel_ai.confirmed_workflow import ConfirmedWorkflow


def model():
    return Mock(complete=Mock(return_value={'text':json.dumps(dict(status='proposal',request={'task':'counts'},
                evidence={'task':'计数'},missing=[])), 'metadata':{'finish_reason':'stop'}}))


class ConfirmationTests(unittest.TestCase):
    def test_unsupported_request_never_gets_confirmation(self):
        from tests.test_intent_presentation import sample
        c=sample(['2017-04'],'查询');c['request']['request']['operation']='delete'
        m=Mock(complete=Mock(return_value={'text':json.dumps(c),'metadata':{'finish_reason':'stop'}}))
        f=ConfirmedWorkflow(m)
        with patch('src.tradeintel_ai.confirmed_workflow.execute_request') as execute:
            p=f.propose('查询')
            self.assertEqual(p['status'],'interpreted_refusal')
            self.assertNotIn('confirmation_token',p)
            self.assertFalse(f.confirm('anything')['execution_attempted'])
            execute.assert_not_called()

    def test_cli_demo_simulated_confirmation_and_cancellation(self):
        root=Path(__file__).resolve().parents[1]
        for answer,expected in [('确认\n','执行状态：evidence_ready'),('取消\n','已取消，没有执行查询')]:
            result=subprocess.run([sys.executable,'scripts/run_confirmed_workflow.py','--demo'],
                                  input=answer,text=True,capture_output=True,cwd=root,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(expected,result.stdout)
            self.assertIn('不调用API',result.stdout)

    def test_confirmation_uses_private_copy_and_only_once(self):
        f=ConfirmedWorkflow(model())
        with patch('src.tradeintel_ai.confirmed_workflow.execute_request',return_value={'status':'evidence_ready'}) as execute:
            p=f.propose('计数');execute.assert_not_called()
            p['request']['task']='quality'
            r=f.confirm(p['confirmation_token'])
            self.assertEqual(execute.call_args.args[0],{'task':'counts'})
            self.assertTrue(r['user_confirmed'])
            self.assertEqual(f.confirm(p['confirmation_token'])['status'],'confirmation_rejected')
            execute.assert_called_once()

    def test_cancel_and_replacement_invalidate(self):
        f=ConfirmedWorkflow(model());p=f.propose('计数');f.cancel()
        self.assertFalse(f.confirm(p['confirmation_token'])['execution_attempted'])
        p=f.propose('计数');f.propose('计数')
        self.assertFalse(f.confirm(p['confirmation_token'])['execution_attempted'])

    def test_parse_failure_cannot_execute(self):
        f=ConfirmedWorkflow(model());p=f.propose('没有对应引文')
        self.assertNotIn('confirmation_token',p)
        self.assertFalse(f.confirm('anything')['execution_attempted'])

    def test_real_read_only_evidence_pipeline(self):
        f=ConfirmedWorkflow(model());p=f.propose('计数');r=f.confirm(p['confirmation_token'])
        self.assertEqual(r['status'],'evidence_ready')
        self.assertTrue(r['sources'])
        self.assertFalse(r['intent_verified'])
        self.assertIn('当前能力边界',r['response'])

    def test_failure_consumes_confirmation(self):
        f=ConfirmedWorkflow(model());p=f.propose('计数')
        with patch('src.tradeintel_ai.confirmed_workflow.execute_request',side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):f.confirm(p['confirmation_token'])
        self.assertFalse(f.confirm(p['confirmation_token'])['execution_attempted'])
