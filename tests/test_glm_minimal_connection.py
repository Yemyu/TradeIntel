import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from diagnose_glm_connection import probe
from run_policy_bounded import PolicyBoundedModel,OpenAICompatibleConfig,OpenAICompatibleModel


class ProbeTests(unittest.TestCase):
    def test_policy_override_preserves_original_messages(self):
        config=OpenAICompatibleConfig('https://example.invalid','glm-4.7','',60,0)
        messages=[{'role':'system','content':'fixture rules'},{'role':'user','content':'fixture question'}]
        original=OpenAICompatibleModel(config)._payload(messages=messages,tools=[])
        bounded=PolicyBoundedModel(config)._payload(messages=messages,tools=[])
        self.assertEqual(bounded,{**original,'thinking':{'type':'disabled'},'max_tokens':512,'stream':False})
        self.assertNotIn('thinking',original)

    def test_payload_and_single_attempt(self):
        seen=[]
        def opener(request,timeout):
            seen.append(json.loads(request.data))
            response=io.BytesIO(b'{"choices":[{"message":{"content":"OK"}}]}')
            response.status=200
            return response
        with tempfile.TemporaryDirectory() as temp:
            result=probe('fake-key',Path(temp),opener)
            self.assertTrue(result['exact_ok'])
            self.assertEqual(result['http_status'],200)
            self.assertEqual(seen[0]['max_tokens'],16)
            self.assertEqual(seen[0]['thinking'],{'type':'disabled'})
            self.assertEqual(len(seen[0]['messages']),1)
            with self.assertRaises(FileExistsError): probe('fake-key',Path(temp),opener)
            self.assertEqual(len(seen),1)

    def test_http_error_safe(self):
        def opener(request,timeout): raise HTTPError('private-url',401,'secret',{},None)
        with tempfile.TemporaryDirectory() as temp:
            result=probe('fake-key',Path(temp),opener)
            self.assertEqual(result['diagnostic'],{'category':'http','http_status':401})
            self.assertNotIn('private-url',(Path(temp)/'result.json').read_text())
