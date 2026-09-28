"""Synthetic records test the gate; never invoke or impersonate live results."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from src.tradeintel_ai.provider_executor import verify_development_review, _canonical


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.frozen = {'experiment_id': 'test-only', 'development_gate': {'path': 'review.json'},
                       'allowed_runs': [{'stage': 'development', 'contract': c,
                                         'package': 'd1', 'manifest_sha256': 'packagehash'} for c in ('B','C')]}
        self.sha = hashlib.sha256(_canonical(self.frozen).encode()).hexdigest()
        self.record = {'schema': 's3-development-gate-v1', 'status': 'approved',
                       'reviewer': 'synthetic-test', 'experiment_id': 'test-only',
                       'freeze_sha256': self.sha, 'hard_checks': [0,0,0],
                       'gain_checks': [1,1,0], 'd1_runs': []}
        self.ledger = {'events': []}
        for c in ('B', 'C'):
            folder = self.root/c
            folder.mkdir()
            raw = folder/'raw-response.json'
            raw.write_text('test-only synthetic response')
            manifest = {'run_id': c, 'contract': c, 'status': 'completed', 'provider_kind': 'real',
                        'experiment_id': 'test-only', 'freeze_sha256': self.sha,
                        'package': str(self.root/'d1'), 'package_manifest_sha256': 'packagehash',
                        'artifact_files_sha256': {'raw-response.json': self.digest(raw)}}
            path = folder/'run-manifest.json'
            path.write_text(json.dumps(manifest))
            self.record['d1_runs'].append({'contract': c, 'run_manifest': str(path),
                                         'run_manifest_sha256': self.digest(path)})
            self.ledger['events'] += [{'event': 'started', 'run_id': c, 'freeze_sha256': self.sha,
                                      'output_dir': str(folder)}, {'event': 'completed', 'run_id': c}]

    def digest(self, path): return hashlib.sha256(path.read_bytes()).hexdigest()

    def check(self): return verify_development_review(self.root,self.frozen,self.ledger,self.record)

    def modify_run(self, **changes):
        ref=self.record['d1_runs'][0]; path=Path(ref['run_manifest'])
        value=json.loads(path.read_text()); value.update(changes)
        path.write_text(json.dumps(value)); ref['run_manifest_sha256']=self.digest(path)

    def test_review_does_not_change_freeze(self):
        before=deepcopy(self.frozen)
        self.assertEqual(self.check(), self.sha)
        self.assertEqual(self.frozen,before)

    def test_stub_is_not_real_evidence(self):
        self.modify_run(provider_kind='stub')
        with self.assertRaises(ValueError): self.check()

    def test_other_experiment_refused(self):
        self.modify_run(experiment_id='other')
        with self.assertRaises(ValueError): self.check()

    def test_other_package_refused(self):
        self.modify_run(package=str(self.root/'q1'))
        with self.assertRaises(ValueError): self.check()

    def test_unknown_response_refused(self):
        self.modify_run(status='unknown_outcome')
        with self.assertRaises(ValueError): self.check()

    def test_changed_answer_refused(self):
        (self.root/'B/raw-response.json').write_text('changed')
        with self.assertRaises(ValueError): self.check()

    def test_missing_ledger_refused(self):
        self.ledger['events']=[]
        with self.assertRaises(ValueError): self.check()

    def test_replaced_manifest_refused(self):
        (self.root/'C/run-manifest.json').write_text('{}')
        with self.assertRaises(ValueError): self.check()

    def test_duplicate_contract_refused(self):
        self.record['d1_runs'][1]=deepcopy(self.record['d1_runs'][0])
        with self.assertRaises(ValueError): self.check()

    def test_scores_must_pass_and_be_integers(self):
        for key,value in [('gain_checks',[1,0,0]),('hard_checks',[0,1,0]),('hard_checks',[False,0,0])]:
            saved=deepcopy(self.record);self.record[key]=value
            with self.assertRaises(ValueError): self.check()
            self.record=saved

    def test_foreign_freeze_refused(self):
        self.record['freeze_sha256']='other'
        with self.assertRaises(ValueError): self.check()


if __name__ == '__main__': unittest.main()
