import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.tradeintel_ai.exposure_version_store import (
    ExposureVersionStore,
    VersionStoreError,
    content_digest,
)


def snapshot(end, *, amount=10, policy_hash="policy"):
    body = {
        "policy_id": "registered",
        "start": "2025-01",
        "end": end,
        "mode": "test",
        "months": {"2026-06": {"amount": 10}, **{end: {"amount": amount}}},
        "policy_files": {"policy.csv": policy_hash},
    }
    return {**body, "version": content_digest(body)}


class ExposureVersionStoreTests(unittest.TestCase):
    def test_bootstrap_stage_activate_and_idempotency(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExposureVersionStore(Path(directory))
            old = snapshot("2026-06")
            new = snapshot("2026-07", amount=20)
            diff = {
                "status": "changed",
                "before_version": old["version"],
                "after_version": new["version"],
                "added_months": ["2026-07"],
                "removed_months": [],
                "revised_months": [],
                "policy_changed": False,
                "requires_review": False,
            }
            self.assertEqual(store.bootstrap(old)["status"], "active")
            staged = store.stage(old, new, diff)
            self.assertEqual(staged["status"], "candidate")
            self.assertTrue(staged["ready_for_activation"])
            self.assertEqual(store.stage(old, new, diff)["idempotent"], True)
            with self.assertRaises(VersionStoreError):
                store.activate(new['version'])  # Metadata alone cannot be published.
            self.assertEqual(store.active_version(), old["version"])
            self.assertEqual(store.status()["active"]["status"], "active")
            self.assertEqual(store.status()['candidates'][0]['difference'], diff)

    def test_review_required_candidate_cannot_change_active_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExposureVersionStore(Path(directory))
            old = snapshot("2026-06")
            revised = snapshot("2026-06", amount=11)
            store.bootstrap(old)
            diff = {
                "before_version": old["version"],
                "after_version": revised["version"],
                "revised_months": ["2026-06"],
                "requires_review": True,
            }
            store.stage(old, revised, diff)
            with self.assertRaises(VersionStoreError):
                store.activate(revised["version"])
            self.assertEqual(store.active_version(), old["version"])
            self.assertEqual(store.status()["candidates"][0]["status"], "candidate")

    def test_failed_attempt_is_recorded_without_replacing_old_version(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExposureVersionStore(Path(directory))
            old = snapshot("2026-06")
            store.bootstrap(old)
            failure = store.record_failure(reason="候选月表哈希不一致", candidate_version=None)
            self.assertEqual(failure["active_version"], old["version"])
            self.assertEqual(store.active_version(), old["version"])
            self.assertEqual(store.status()["failure_count"], 1)

    def test_active_base_and_snapshot_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExposureVersionStore(Path(directory))
            old = snapshot("2026-06")
            new = snapshot("2026-07")
            store.bootstrap(old)
            wrong_base = snapshot("2026-05")
            diff = {"before_version": wrong_base["version"], "after_version": new["version"]}
            with self.assertRaises(VersionStoreError):
                store.stage(wrong_base, new, diff)
            path = Path(directory) / "data/processed/policy_exposure/versions" / old["version"] / "snapshot.json"
            tampered = copy.deepcopy(old)
            tampered["months"]["2026-06"]["amount"] = 999
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(VersionStoreError):
                store.load_snapshot(old["version"])


if __name__ == "__main__":
    unittest.main()
