import json
import socket
import ssl
import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError
from src.tradeintel_ai.model_adapter import ModelAdapterError, safe_error_details


class SafeErrorTests(unittest.TestCase):
    def wrap(self, cause):
        error = ModelAdapterError('secret-do-not-log')
        error.__cause__ = cause
        return error

    def test_http_status_only(self):
        for status in (400,401,403,429,500,503):
            error = HTTPError('https://secret.invalid', status, 'secret',
                              {'Authorization': 'secret'}, BytesIO(b'secret'))
            result = safe_error_details(self.wrap(error))
            self.assertEqual(result, {'category':'http_error','http_status':status})
            self.assertNotIn('secret',json.dumps(result))

    def test_typed_network_causes(self):
        for cause, expected in ((ssl.SSLCertVerificationError('secret'), 'tls_certificate_verification'),
                                (ssl.SSLError('secret'), 'tls_error'),
                                (socket.gaierror('secret'), 'dns_error'),
                                (TimeoutError('secret'), 'timeout'),
                                (ConnectionRefusedError('secret'), 'connection_error')):
            self.assertEqual(safe_error_details(self.wrap(URLError(cause))), {'category':expected})

    def test_arbitrary_messages_not_parsed(self):
        self.assertEqual(safe_error_details(self.wrap(URLError('401 secret'))),
                         {'category':'unclassified_error'})

    def test_decode_error(self):
        e=json.JSONDecodeError('secret','secret',0)
        self.assertEqual(safe_error_details(self.wrap(e)), {'category':'response_decode_error'})

    def test_cycle_terminates(self):
        error=self.wrap(None);error.__cause__=error
        self.assertEqual(safe_error_details(error), {'category':'unclassified_error'})


if __name__ == '__main__': unittest.main()
