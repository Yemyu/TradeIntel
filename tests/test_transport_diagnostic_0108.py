import json
from pathlib import Path
import ssl
import tempfile
import unittest
from urllib.error import URLError
from unittest.mock import Mock

from tradeintel_ai.transport_diagnostic import transport_detail
from tradeintel_ai.development_smoke import CallLedger
from tradeintel_ai.unified_research import UnifiedResearchWorkflow


def failure():
    outer = RuntimeError('private key / private URL')
    outer.__cause__ = URLError(ssl.SSLEOFError(8, 'private key / private URL'))
    return outer


class TransportTests(unittest.TestCase):
    def test_tls_chain_has_no_error_strings(self):
        value = transport_detail(failure())
        self.assertEqual([r['type'] for r in value['exception_chain']], ['wrapper', 'url', 'tls_eof'])
        self.assertNotIn('private', json.dumps(value))

    def test_string_reason_and_cycles_are_bounded(self):
        e = URLError('private URL')
        e.__cause__ = e
        value = transport_detail(e)
        self.assertEqual(len(value['exception_chain']), 1)
        self.assertNotIn('private', json.dumps(value))

    def test_planning_connection_failure_not_reported_as_format_failure(self):
        model = Mock()
        model.complete.side_effect = failure()
        value = UnifiedResearchWorkflow(model).prepare('查询历史政策')
        self.assertIn('连接中断', value['response'])
        self.assertEqual(value['planner_audit']['transport_detail']['exception_chain'][-1]['type'], 'tls_eof')
        self.assertNotIn('private', json.dumps(value))

    def test_ledger_retains_safe_underlying_error_and_one_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = CallLedger(Path(tmp), {'source_kind': 'fixture'}, lambda: True)
            model = Mock(side_effect=failure())
            with self.assertRaises(RuntimeError):
                ledger.call('D89-1', 'planning', model)
            data = json.loads((Path(tmp) / 'batch.json').read_text())
            self.assertEqual(len(data['calls']), 1)
            self.assertEqual(data['calls'][0]['transport_detail']['exception_chain'][-1]['type'], 'tls_eof')
            self.assertNotIn('private', json.dumps(data))
