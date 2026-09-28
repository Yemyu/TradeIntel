"""Offline allowlist, immutable freeze, and five-attempt cap tests."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy

from src.tradeintel_ai.provider_executor import _verify_named_freeze


class NamedFreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / 'package'
        self.package.mkdir()
        (self.package / 'manifest.json').write_text('{}')
        (self.root / 'reference.md').write_text('review only')
        names = ['src/tradeintel_ai/provider_executor.py', 'src/tradeintel_ai/brief_business_view.py',
                 'src/tradeintel_ai/evidence_linked_brief.py', 'src/tradeintel_ai/model_adapter.py',
                 'scripts/run_fake_experiment.py', 'scripts/prepare_brief_v3_offline.py']
        for name in names:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('test runtime')
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.freeze = {'schema_version': 'bounded-provider-freeze-v1', 'experiment_id': 's3-test',
                       'max_calls': 5, 'runtime_sha256': {n: sha(self.root/n) for n in names},
                       'allowed_runs': [{'package': 'package', 'contract': 'C',
                                         'manifest_sha256': sha(self.package/'manifest.json'),
                                         'reference': 'reference.md',
                                         'reference_sha256': sha(self.root/'reference.md'),
                                         'stage': 'development'}]}

    def check(self, ledger=None, **kwargs):
        return _verify_named_freeze(self.root, self.freeze, 's3-test', self.package,
                                    kwargs.get('contract', 'C'), ledger or {'events': []})

    def test_valid(self): self.assertEqual(len(self.check()), 64)

    def test_e_requires_additional_runtime_and_single_development_slot(self):
        self.freeze['max_calls'] = 1
        self.freeze['allowed_runs'][0]['contract'] = 'E'
        with self.assertRaisesRegex(ValueError, 'runtime'):
            self.check(contract='E')
        for name in ('src/tradeintel_ai/bounded_explanation.py',
                     'src/tradeintel_ai/response_contract.py',
                     'src/tradeintel_ai/brief_fact_catalog.py',
                     'scripts/prepare_bounded_explanation.py'):
            path = self.root / name
            path.write_text('test E runtime')
            self.freeze['runtime_sha256'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(len(self.check(contract='E')), 64)
        self.freeze['allowed_runs'][0]['stage'] = 'formal'
        with self.assertRaisesRegex(ValueError, 'development'):
            self.check(contract='E')

    def test_legacy_marker_not_enough(self):
        self.freeze.pop('schema_version')
        with self.assertRaises(ValueError): self.check()

    def test_wrong_experiment(self):
        self.freeze['experiment_id'] = 'other'
        with self.assertRaises(ValueError): self.check()

    def test_budget_type_and_ceiling(self):
        for value in (True, 0, 6, 14, '5'):
            self.freeze['max_calls'] = value
            with self.assertRaises(ValueError): self.check()

    def test_unknown_contract(self):
        with self.assertRaises(ValueError): self.check(contract='B')

    def test_changed_reference(self):
        (self.root/'reference.md').write_text('changed')
        with self.assertRaises(ValueError): self.check()

    def test_changed_runtime(self):
        (self.root/'src/tradeintel_ai/model_adapter.py').write_text('changed')
        with self.assertRaises(ValueError): self.check()

    def test_changed_package(self):
        (self.package/'manifest.json').write_text('{"new":1}')
        with self.assertRaises(ValueError): self.check()

    def test_five_calls_even_when_ledger_says_fourteen(self):
        sha = self.check()
        ledger = {'total_slots': 14, 'events': [
            {'event': 'started', 'run_id': str(i), 'freeze_sha256': sha} for i in range(5)]}
        with self.assertRaisesRegex(ValueError, 'budget exhausted'): self.check(ledger)

    def test_resolved_retry_cannot_reuse_allowlist_entry(self):
        ledger = {'events': [{'event': 'started', 'run_id': '1', 'freeze_sha256': self.check(),
                             'frozen_run_key': str(self.package.resolve()) + ':C'},
                            {'event': 'resolved_retry_authorized', 'run_id': '1'}]}
        with self.assertRaisesRegex(ValueError, 'already attempted'): self.check(ledger)

    def test_changed_freeze_after_attempt(self):
        ledger = {'events': [{'event': 'started', 'run_id': '1', 'freeze_sha256': self.check()}]}
        self.freeze['model'] = 'new-model'
        with self.assertRaisesRegex(ValueError, 'freeze changed'): self.check(ledger)

    def test_duplicate_entries(self):
        self.freeze['allowed_runs'].append(deepcopy(self.freeze['allowed_runs'][0]))
        with self.assertRaises(ValueError): self.check()

    def test_formal_entry_requires_d1_gate(self):
        self.freeze['allowed_runs'][0]['stage'] = 'formal'
        with self.assertRaisesRegex(ValueError, 'D1 development gate'):
            self.check()

    def test_approved_word_alone_cannot_open_gate(self):
        gate = self.root / 'd1-gate.json'
        gate.write_text('{"status":"approved"}')
        self.freeze['allowed_runs'][0]['stage'] = 'formal'
        self.freeze['development_gate'] = {'status': 'approved', 'path': 'd1-gate.json',
                                           'sha256': hashlib.sha256(gate.read_bytes()).hexdigest()}
        with self.assertRaises(ValueError): self.check()

    def test_real_executor_checks_freeze_before_client_or_charge(self):
        from unittest.mock import patch
        from src.tradeintel_ai import provider_executor as executor
        marker = executor.frozen_marker_path(self.root, experiment_id='s3-test')
        marker.parent.mkdir(parents=True)
        self.freeze['max_calls'] = 14
        marker.write_text(json.dumps(self.freeze))
        messages = [{'role': 'user', 'content': '{}'}]
        (self.package/'messages.json').write_text(json.dumps(messages))
        with patch.object(executor, '_load_view_package', return_value=(
                {'question': 'test'}, {}, {}, {})), \
             patch.object(executor, '_build_real_provider') as client:
            with self.assertRaisesRegex(ValueError, 'budget'):
                executor.run_experiment(self.root, package=self.package, contract='C',
                    output=self.root/'never-created', experiment_id='s3-test',
                    authorize_real_call=True)
            client.assert_not_called()
        self.assertFalse((self.root/'never-created').exists())
        self.assertFalse((marker.parent/'provider-ledger-s3-test-real.json').exists())


if __name__ == '__main__': unittest.main()
