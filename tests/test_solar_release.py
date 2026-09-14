"""Real local candidate integration; enables routing only inside a test patch."""
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.replay_exposure_update import snapshot
from tradeintel_ai.policy_cases import CASES
from tradeintel_ai.policy_exposure_tools import get_policy_exposure_series
from tradeintel_ai.exposure_version_store import ExposureVersionStore, VersionStoreError
from tradeintel_ai.repository import DataPaths, EvidenceRepository
from tradeintel_ai.tools import ToolError


class SolarReleaseTests(unittest.TestCase):
    def test_real_candidate_release_is_self_contained_and_case_bound(self):
        source = Path(__file__).resolve().parents[1]
        case = CASES['us_301_solar2024']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = Path(case.manifest).parent
            shutil.copytree(source / base, root / base,
                            ignore=shutil.ignore_patterns('versions'))
            repo = EvidenceRepository(DataPaths(root))
            # Production configuration remains candidate; no bypass in tool schema.
            with self.assertRaises(ToolError):
                get_policy_exposure_series(repository=repo, policy_id=case.policy_id)
            with patch.dict(CASES, {case.policy_id: replace(case, status='enabled')}):
                state = snapshot(root, case.end, policy_id=case.policy_id)
                self.assertIn(str(base / 'source.json'), state['policy_files'])
                store = ExposureVersionStore(root, root / case.versions)
                store.bootstrap(state)
                release = store.prepare_release(state['version'])
                receipt = json.loads((release / 'release.json').read_text())
                self.assertTrue(all(p.startswith(str(base) + '/') for p in receipt['files']))
                result = get_policy_exposure_series(repository=repo, policy_id=case.policy_id)
                self.assertEqual(result['data']['months'], 19)
                self.assertTrue(result['data']['coverage_complete'])
                self.assertEqual(result['data_version'], state['version'])
                self.assertEqual(result['policy_evidence']['policy_id'], case.policy_id)
                self.assertEqual(len(result['policy_evidence']['hits']), 4)
                self.assertEqual({p['hts8'] for p in result['data']['series'][0]['product_breakdown']},
                                 {'85414200', '85414300'})
                with self.assertRaises(ToolError):
                    get_policy_exposure_series(repository=repo, policy_id=case.policy_id, hts8='38180000')
                # Source damage outside the release must not change a pinned query.
                (root / base / 'source.json').write_text('{}')
                self.assertEqual(get_policy_exposure_series(repository=repo, policy_id=case.policy_id), result)
                # Damage inside the sealed release must stop query execution.
                (release / base / 'source.json').write_text('{}')
                with self.assertRaises(VersionStoreError):
                    get_policy_exposure_series(repository=repo, policy_id=case.policy_id)
            self.assertEqual(CASES[case.policy_id].status, 'candidate')
