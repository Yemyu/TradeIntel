"""Business regression: rejected updates cannot replace readable evidence."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_policy_exposure_tools import make_fixture
from tests.test_policy_exposure_workflow import Model, DRAFT
from src.tradeintel_ai.agent import ModelResponse, ModelToolCall
from src.tradeintel_ai.exposure_version_store import (
    ExposureVersionStore, VersionStoreError, content_digest, snapshot_difference, pin_repository,
)
from src.tradeintel_ai.policy_exposure_tools import get_policy_exposure_series, POLICY_EXPOSURE_ID
from src.tradeintel_ai.policy_exposure_workflow import run_exposure_demo


def capture(root, repository, end):
    rows = get_policy_exposure_series(repository=repository, start='2025-01', end=end)['data']['series']
    body = dict(policy_id=POLICY_EXPOSURE_ID, start='2025-01', end=end,
                policy_files={str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (root / 'data/processed/policy').glob('*.csv')}, months={})
    for row in rows:
        path = root / f"data/processed/policy_exposure/monthly/{POLICY_EXPOSURE_ID}_{row['month'].replace('-', '_')}.csv"
        body['months'][row['month']] = dict(metrics=row, output_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return {**body, 'version': content_digest(body)}


class ReleaseTests(unittest.TestCase):
    def test_published_update_and_pinned_report_survive_working_file_damage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture(root)
            old, new = capture(root, repo, '2025-01'), capture(root, repo, '2025-02')
            store = ExposureVersionStore(root)
            store.bootstrap(old)
            store.prepare_release(old['version'])
            pinned_old = pin_repository(repo)
            store.stage(old, new, snapshot_difference(old, new))
            store.prepare_release(new['version'])
            store.activate(new['version'])
            self.assertEqual(get_policy_exposure_series(repository=repo, start='2025-02', end='2025-02')['data_version'], new['version'])
            with self.assertRaises(VersionStoreError):
                get_policy_exposure_series(repository=pinned_old, start='2025-02', end='2025-02')
            baseline = get_policy_exposure_series(repository=repo, start='2025-01', end='2025-02')
            candidate = copy.deepcopy(new)
            candidate['months']['2025-02']['metrics']['value_usd'] = 999
            candidate['version'] = content_digest({k: v for k, v in candidate.items() if k != 'version'})
            forged = snapshot_difference(new, candidate)
            forged['requires_review'] = False
            with self.assertRaises(VersionStoreError):
                store.stage(new, candidate, forged)
            store.stage(new, candidate, snapshot_difference(new, candidate))
            with self.assertRaises(VersionStoreError):
                store.activate(candidate['version'])
            # Actually damage the working data, then attempt a rejected release.
            path = next((root / 'data/processed/policy_exposure/monthly').glob('*.csv'))
            path.write_bytes(b'broken candidate')
            with self.assertRaises(VersionStoreError):
                store.prepare_release(candidate['version'])
            self.assertEqual(store.active_version(), new['version'])
            self.assertEqual(get_policy_exposure_series(repository=repo, start='2025-01', end='2025-02'), baseline)
            expected = dict(policy_id=POLICY_EXPOSURE_ID, origin='China', hts8=None, start='2025-01', end='2025-01')
            model = Model([ModelResponse(tool_calls=(ModelToolCall('a', 'get_policy_exposure_series', expected),)),
                           ModelResponse(text=DRAFT), ModelResponse(text='fixture baseline')])
            with patch('src.tradeintel_ai.policy_exposure_workflow.EXPECTED', expected):
                state = run_exposure_demo(model, root / 'report', repository=repo)
            self.assertEqual(state['status'], 'draft_needs_review')
            self.assertEqual(state['data_version'], new['version'])
            self.assertIn(new['version'], (root / 'report/report.zh-CN.md').read_text())
            self.assertEqual(json.loads((root / 'report/tool-result-1.json').read_text())['data_version'], new['version'])

    def test_damaged_release_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture(root)
            old = capture(root, repo, '2025-01')
            store = ExposureVersionStore(root)
            store.bootstrap(old)
            release = store.prepare_release(old['version'])
            path = next((release / 'data/processed/policy_exposure/monthly').glob('*.csv'))
            path.write_bytes(b'damaged release')
            with self.assertRaises(VersionStoreError):
                get_policy_exposure_series(repository=repo, start='2025-01', end='2025-01')
