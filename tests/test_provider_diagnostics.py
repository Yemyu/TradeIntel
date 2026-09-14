import unittest
import json
from http.client import RemoteDisconnected, IncompleteRead
from urllib.error import HTTPError, URLError
from src.tradeintel_ai.provider_diagnostics import safe_provider_diagnostic


class ProviderDiagnosticsTests(unittest.TestCase):
    def test_transport_and_decode_failures_are_safe(self):
        for error, category in [
            (RemoteDisconnected('secret'), 'remote_disconnected'),
            (ConnectionResetError('secret'), 'connection_error'),
            (IncompleteRead(b'secret'), 'http_protocol_error'),
            (json.JSONDecodeError('secret', 'secret', 0), 'response_decode_error'),
        ]:
            wrapped = RuntimeError('secret')
            wrapped.__cause__ = error
            self.assertEqual(safe_provider_diagnostic(wrapped), {'category': category})

    def test_http_cause_keeps_status_not_secret(self):
        for status, category in [(401,'authentication_rejected'), (403,'access_denied'),
                                 (429,'rate_or_quota_limit'), (503,'provider_server_error')]:
            source = HTTPError('https://secret-url.test', status, 'secret-provider-text',
                               {'Authorization':'secret-key'}, None)
            wrapped = RuntimeError('secret-wrapper')
            wrapped.__cause__ = source
            self.assertEqual(safe_provider_diagnostic(wrapped), {'category':category,'http_status':status})

    def test_network_and_cycle_never_expose_messages(self):
        self.assertEqual(safe_provider_diagnostic(URLError('secret hostname')), {'category':'network_error'})
        self.assertEqual(safe_provider_diagnostic(URLError(TimeoutError('secret'))), {'category':'timeout'})
        err = ValueError('secret')
        err.__cause__ = err
        self.assertEqual(safe_provider_diagnostic(err), {'category':'unclassified_error'})
