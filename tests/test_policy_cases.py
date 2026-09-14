import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch
from src.tradeintel_ai.policy_cases import resolve_case, CASES
from src.tradeintel_ai.policy_exposure_tools import get_policy_exposure_series
from src.tradeintel_ai.tools import ToolError


class PolicyCaseTests(unittest.TestCase):
    def test_public_catalog_tracks_status_without_private_paths(self):
        from src.tradeintel_ai.policy_cases import public_case_catalog
        catalog = public_case_catalog()
        second = next(c for c in catalog['cases'] if c['policy_id'] == 'us_301_solar2024')
        self.assertFalse(second['query_enabled'])
        self.assertEqual(set(second), {'policy_id','label','status','query_enabled','status_label','registered_window'})
        candidate = CASES['us_301_solar2024']
        with patch.dict(CASES, {candidate.policy_id: replace(candidate, status='enabled')}):
            updated = next(c for c in public_case_catalog()['cases'] if c['policy_id'] == candidate.policy_id)
            self.assertTrue(updated['query_enabled'])
            self.assertNotIn('候选', updated['status_label'])
        self.assertEqual(CASES[candidate.policy_id].status, 'candidate')

    def test_enabled_case_selects_its_own_store(self):
        from src.tradeintel_ai.exposure_version_store import pin_repository
        candidate = CASES['us_301_solar2024']
        repo = SimpleNamespace(paths=SimpleNamespace(root=Path('/test-root')))
        with patch.dict(CASES, {candidate.policy_id: replace(candidate, status='enabled')}):
            with patch('src.tradeintel_ai.exposure_version_store.ExposureVersionStore') as factory:
                factory.return_value.active_version.return_value = None
                self.assertIs(pin_repository(repo, candidate.policy_id), repo)
                factory.assert_called_once_with(repo.paths.root, repo.paths.root / candidate.versions)

    def test_pinned_repository_cannot_be_reused_for_another_case(self):
        from src.tradeintel_ai.exposure_version_store import pin_repository, VersionStoreError
        candidate = CASES['us_301_solar2024']
        store = MagicMock()
        store.load_snapshot.return_value = {'policy_id': 'us_301_review2025_tungsten_solar'}
        repo = SimpleNamespace(exposure_version='version', exposure_store=store)
        with patch.dict(CASES, {candidate.policy_id: replace(candidate, status='enabled')}):
            with self.assertRaises(VersionStoreError):
                pin_repository(repo, candidate.policy_id)
        store.release_root.assert_not_called()

    def test_wrong_policy_in_selected_store_stops_before_release_read(self):
        from src.tradeintel_ai.exposure_version_store import pin_repository, VersionStoreError
        repo = SimpleNamespace(paths=SimpleNamespace(root=Path('/test-root')))
        with patch('src.tradeintel_ai.exposure_version_store.ExposureVersionStore') as factory:
            store = factory.return_value
            store.active_version.return_value = 'version'
            store.load_snapshot.return_value = {'policy_id': 'us_301_solar2024'}
            with self.assertRaises(VersionStoreError):
                pin_repository(repo)
            store.release_root.assert_not_called()

    def test_candidate_and_unknown_never_reach_default_version_store(self):
        for value in ['us_301_solar2024', 'invented', '../escape', None]:
            with patch('src.tradeintel_ai.exposure_version_store.pin_repository') as pin:
                with self.assertRaises(ToolError):get_policy_exposure_series(policy_id=value)
                pin.assert_not_called()

    def test_case_resources_and_version_directories_are_disjoint(self):
        cases=list(CASES.values())
        for field in ['event','products','manifest','monthly','corpus','versions']:
            self.assertNotEqual(getattr(cases[0],field),getattr(cases[1],field))
        self.assertEqual(resolve_case('us_301_solar2024',require_enabled=False).status,'candidate')

    def test_mismatched_snapshot_is_rejected(self):
        from types import SimpleNamespace
        from src.tradeintel_ai.exposure_version_store import VersionStoreError
        repo=SimpleNamespace(exposure_snapshot={'start':'2025-01','end':'2026-07','policy_id':'wrong'})
        with patch('src.tradeintel_ai.exposure_version_store.pin_repository',return_value=repo):
            with self.assertRaises(VersionStoreError):get_policy_exposure_series()
