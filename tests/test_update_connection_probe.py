import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from scripts.probe_update_connection import probe
from tradeintel_ai.model_adapter import OpenAICompatibleConfig


class ProbeTests(unittest.TestCase):
    def test_failure_is_one_attempt_without_secrets(self):
        calls=[]
        def opener(request, timeout):
            calls.append(1)
            raise HTTPError('https://secret',401,'secret-key',None,None)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'probe'
            cfg=OpenAICompatibleConfig('https://example.org','test','secret-key')
            result=probe(cfg,out,opener)
            self.assertEqual(result['diagnostic']['category'],'authentication_rejected')
            self.assertEqual(result['attempts'],1)
            self.assertNotIn('secret', (out/'status.json').read_text())
            with self.assertRaises(FileExistsError):probe(cfg,out,opener)
            self.assertEqual(len(calls),1)

    def test_success_records_usage_not_response(self):
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):
                return json.dumps({'choices':[{'message':{'content':'{"ok":true}'}}],
                                   'usage':{'total_tokens':12}}).encode()
        with tempfile.TemporaryDirectory() as folder:
            state=probe(OpenAICompatibleConfig('https://example.org','test'),
                        Path(folder)/'probe',lambda *args,**kw:Response())
            self.assertEqual(state['status'],'response_received')
            self.assertTrue(state['expected_json'])
            self.assertEqual(state['total_tokens'],12)
