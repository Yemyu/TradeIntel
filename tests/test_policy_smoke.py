import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_policy_smoke import run_once, preflight, safe_error
from urllib.error import HTTPError, URLError
from tradeintel_ai.agent import ModelResponse


class SmokeTests(unittest.TestCase):
    def test_http_status_without_sensitive_details(self):
        cause=HTTPError('https://private.invalid',401,'private-secret',{},None)
        error=RuntimeError('private-secret')
        error.__cause__=cause
        self.assertEqual(safe_error(error),{'category':'http','http_status':401})

    def test_timeout_and_connection_classification(self):
        self.assertEqual(safe_error(URLError(TimeoutError())),{'category':'timeout'})
        self.assertEqual(safe_error(URLError('private-secret')),{'category':'connection'})

    def evidence(self):
        return {'question':'fixture', 'as_of':'2018-07-06','hits':[
            {'id':'x','title':'fixture','published':'2018-06-20','page':1,'text':'source'}]}

    def test_once_and_secret_redaction(self):
        model=Mock()
        model.complete.return_value=ModelResponse(text='{"claims":[{"text":"fake-secret","citations":["x"]}]}')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            run_once(model,self.evidence(),path,secret='fake-secret')
            self.assertNotIn('fake-secret',(path/'result.json').read_text())
            with self.assertRaises(FileExistsError): run_once(model,self.evidence(),path)
            self.assertEqual(model.complete.call_count,1)

    def test_transport_error_is_recorded_without_message_or_retry(self):
        model=Mock()
        model.complete.side_effect=RuntimeError('private detail')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            result=run_once(model,self.evidence(),path)
            self.assertEqual(result['status'],'stopped_without_retry')
            self.assertNotIn('private detail',(path/'result.json').read_text())
            self.assertEqual(model.complete.call_count,1)

    def test_no_evidence_no_call(self):
        model=Mock()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError): run_once(model,{'hits':[]},Path(temp))
        model.complete.assert_not_called()

    def test_frozen_preflight(self):
        with self.assertRaisesRegex(ValueError, '冻结检索程序或题集已改变'):
            preflight()
