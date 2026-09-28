"""Offline regression of provider wiring and irreversible slot reservations."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tradeintel_ai import provider_executor as executor
from tradeintel_ai.model_adapter import OpenAICompatibleConfig


class ExecutorHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / 'package'
        self.package.mkdir()
        self.messages = [{'role': 'system', 'content': 'frozen system'},
                         {'role': 'user', 'content': 'frozen evidence'}]
        (self.package / 'manifest.json').write_text('{}')
        (self.package / 'messages.json').write_text(json.dumps(self.messages))
        for target, value in [('_load_view_package', ({'question': 'test'}, {'v': 1}, {},
                                                    {'catalog_sha256': 'audit'})),
                              ('view_request', self.messages)]:
            p = patch.object(executor, target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def run_case(self, name, provider, contract='B', **kwargs):
        return executor.run_experiment(self.root, package=self.package, contract=contract,
                                       output=self.root / name, provider=provider, **kwargs)

    def test_resolution_never_refunds_and_retry_needs_new_slot(self):
        def timeout(**kwargs):
            raise TimeoutError('secret must not be copied')
        first = self.run_case('first', timeout)
        self.assertEqual(executor.ledger_remaining_slots(self.root), 13)
        self.assertNotIn('secret', json.dumps(first))
        executor.resolve_unknown_run(self.root, first['run_id'],
                                     resolution='resolved_retry_authorized', decided_by='test')
        self.assertEqual(executor.ledger_remaining_slots(self.root), 13)
        second = self.run_case('second', timeout)
        self.assertEqual(executor.ledger_remaining_slots(self.root), 12)
        executor.resolve_unknown_run(self.root, second['run_id'],
                                     resolution='resolved_mark_failed', decided_by='test')
        self.assertEqual(executor.ledger_remaining_slots(self.root), 12)
        self.assertEqual(self.run_case('third', timeout)['status'], 'refused_duplicate_run')

    def test_concurrent_claim_calls_provider_once(self):
        calls = []
        def provider(**kwargs):
            calls.append(1)
            return 'answer', {'total_tokens': 3}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: self.run_case(f'run{n}', provider), range(4)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(r['status'] == 'completed' for r in results), 1)
        self.assertEqual(executor.ledger_remaining_slots(self.root), 13)

    def test_bad_json_preserves_usage_and_finishes(self):
        result = self.run_case('invalid', lambda **kw: ('not json', {'total_tokens': 17}), 'C')
        self.assertEqual(result['status'], 'invalid_response')
        manifest = json.loads((self.root / 'invalid/run-manifest.json').read_text())
        self.assertEqual(manifest['usage'], {'total_tokens': 17})
        self.assertEqual((self.root / 'invalid/raw-response.json').read_text(), 'not json')
        self.assertEqual(executor.ledger_remaining_slots(self.root), 13)
        self.assertEqual(self.run_case('again', lambda **kw: ('{}', {}), 'C')['status'],
                         'refused_duplicate_run')

    def test_overlong_c_stops_before_parsing_and_cannot_auto_retry(self):
        with patch.object(executor, 'adapt_answer') as adapt:
            result = self.run_case('long', lambda **kw: ('长' * 6000, {}), 'C')
        self.assertEqual(result['status'], 'blocked_output_budget')
        adapt.assert_not_called()
        self.assertEqual(self.run_case('again', lambda **kw: ('{}', {}), 'C')['status'],
                         'refused_duplicate_run')

    def freeze(self):
        marker = executor.frozen_marker_path(self.root)
        marker.parent.mkdir(parents=True, exist_ok=True)
        frozen = {'model': 'frozen-test', 'endpoint': 'https://example.invalid/v4',
                  'params': {'temperature': 0, 'max_tokens': 2000,
                             'thinking': {'type': 'disabled'}}}
        marker.write_text(json.dumps(frozen))
        return frozen

    def test_duplicate_json_keys_rejected_before_adaptation(self):
        with patch.object(executor, 'adapt_answer') as adapt:
            result = self.run_case('duplicate-json', lambda **kw: ('{"x":1,"x":2}', {}), 'C')
        self.assertEqual(result['status'], 'invalid_response')
        adapt.assert_not_called()

    def test_authorized_path_constructs_client_with_frozen_payload(self):
        frozen = self.freeze()
        captured = []
        def complete(client, *, messages, tools):
            captured.append(client._payload(messages=messages, tools=tools))
            return SimpleNamespace(text='answer', metadata={'usage': {'total_tokens': 9}})
        config = OpenAICompatibleConfig(frozen['endpoint'], 'local-old-model', 'test-only')
        with patch('tradeintel_ai.local_provider_config.load_config', return_value=config), \
             patch('tradeintel_ai.model_adapter.OpenAICompatibleModel.complete', complete):
            result = self.run_case('authorized', None, authorize_real_call=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(captured, [{'model': 'frozen-test', 'messages': self.messages,
                                    **frozen['params']}])
        self.assertEqual(result['manifest']['usage'], {'total_tokens': 9})
        self.assertNotIn('test-only', json.dumps(result))

    def test_incomplete_freeze_fails_before_reservation(self):
        frozen = self.freeze()
        frozen['params'] = {}
        executor.frozen_marker_path(self.root).write_text(json.dumps(frozen))
        with self.assertRaisesRegex(ValueError, 'frozen params'):
            self.run_case('bad', None, authorize_real_call=True)
        self.assertEqual(executor.ledger_remaining_slots(self.root), 14)

    def test_endpoint_mismatch_fails_before_reservation(self):
        self.freeze()
        config = OpenAICompatibleConfig('https://other.invalid', 'test', 'test-only')
        with patch('tradeintel_ai.local_provider_config.load_config', return_value=config), \
             self.assertRaisesRegex(ValueError, 'endpoint differs'):
            self.run_case('bad', None, authorize_real_call=True)
        self.assertEqual(executor.ledger_remaining_slots(self.root), 14)

    def test_marker_without_authorization_never_builds_client(self):
        self.freeze()
        with patch.object(executor, '_build_real_provider') as factory:
            result = self.run_case('not-authorized', None)
        self.assertEqual(result['status'], 'real_call_not_authorized')
        factory.assert_not_called()

    def test_explicit_experiment_separates_stub_and_real_ledgers(self):
        calls = []
        result = self.run_case('s3-stub',
                               lambda **kw: (calls.append(1) or ('answer', {'stub': True})),
                               experiment_id='s3-r2')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(calls), 1)
        stub_ledger = self.root / '.local/experiments/provider-ledger-s3-r2-stub.json'
        self.assertTrue(stub_ledger.is_file())
        # A real attempt has a separate namespace and is rejected before any
        # provider construction because no frozen marker is present.
        real = self.run_case('s3-real', None, authorize_real_call=True,
                             experiment_id='s3-r2')
        self.assertEqual(real['status'], 'real_call_not_authorized')
        self.assertFalse((self.root / '.local/experiments/provider-ledger-s3-r2-real.json').exists())
        self.assertEqual(executor.ledger_remaining_slots(
            self.root, experiment_id='s3-r2', provider_kind='stub'), 13)


if __name__ == '__main__':
    unittest.main()
