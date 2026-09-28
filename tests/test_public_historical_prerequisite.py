import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.tradeintel_ai.public_eval_ledger import (
    DuplicatePublicRun,
    LedgerStateError,
    HISTORICAL_PREREQUISITE_EVENT,
    canonical_sha,
    claim,
    file_sha256,
    load,
    ledger_path,
    register_historical_prerequisite,
    require_previous_review,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUN = "pub-20260922T072305-168f830f1a"
SOURCE_RUN_DIR = ROOT / "tmp/public-brief-eval-v1/high-v2-runs-20260922/flash-q1"
SOURCE_PACKAGE = ROOT / "tmp/public-brief-eval-v1/candidate-high-v2-20260922"
TARGET_PACKAGE = ROOT / "tmp/public-brief-eval-v1/candidate-v3-r5-20260922"
SOURCE_FREEZE = ROOT / "tmp/public-brief-eval-v1/high-v2-freezes-20260922/flash.json"
TARGET_FREEZE = ROOT / "tmp/public-brief-eval-v1/v3-freezes-20260922/flash-v3-r5.json"
MATRIX = ROOT / "evals/public_brief_v1/provider_matrix_high_v2.json"
REVIEW = ROOT / "evals/public_brief_v1/historical_reviews/flash_high_q1_20260922.json"


class HistoricalPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        # Self-contained ledger fixtures: no live ledger, credentials or stale
        # frozen runtime packages are prerequisites for a unit test.
        paths = {}
        def artifact(name, value, path=None):
            path = path or self.root / (name + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
            paths[name] = str(path)
            return file_sha256(path)
        source_manifest = artifact("source_manifest", {"fixture": "source"})
        target_manifest = artifact("target_manifest", {"fixture": "target"})
        raw_sha = artifact("source_raw", {"answer": "fixture"})
        provider = {"id": "fixture", "model_id": "fixture"}
        source_freeze = {"provider": provider, "params": {"budget_protocol": "v2"},
                         "package_manifest_sha256": source_manifest}
        target_freeze = {"provider": provider, "params": {"budget_protocol": "v3"},
                         "package_manifest_sha256": target_manifest}
        artifact("source_freeze", source_freeze)
        artifact("target_freeze", target_freeze)
        metadata = {"finish_reason": "stop", "usage": {"completion_tokens": 100}}
        artifact("source_metadata", metadata)
        artifact("source_run", {"run_id": SOURCE_RUN, "question_id": "q1",
                 "response_metadata": metadata,
                 "status": "blocked_output_budget", "raw_sha256": raw_sha,
                 "freeze_sha256": canonical_sha(source_freeze)}, self.root / "run/q1/run.json")
        checks = {k: {"passed": k != "facts", "reason": "fixture review"}
                  for k in ("structure", "facts", "relevance", "usefulness")}
        review_sha = artifact("source_review", {
            "schema_version": "public-brief-historical-review-v1",
            "source_run_id": SOURCE_RUN, "verdict": "minor_error", "checks": checks})
        for qid in ("q1", "q2", "q3", "q4"):
            for kind in ("request", "host"):
                for side in ("source", "target"):
                    artifact(f"{side}_{kind}_{qid}", {"question": qid, "kind": kind})
        self.prefix = target_manifest + ":" + "a" * 64
        self.record = dict(source_run_id=SOURCE_RUN, source_manifest_sha256=source_manifest,
            source_freeze_sha256=canonical_sha(source_freeze), target_manifest_sha256=target_manifest,
            target_freeze_sha256=canonical_sha(target_freeze), target_provider_digest="a" * 64,
            review_sha256=review_sha, verdict="minor_error", checks=checks,
            artifact_paths=paths, artifact_hashes={k: file_sha256(Path(v)) for k, v in paths.items()})
        source_events = [dict(event="started", run_id=SOURCE_RUN, metadata={
            "output_dir": str(self.root / "run"), "freeze_sha256": canonical_sha(source_freeze)}),
            dict(event="blocked_output_budget", run_id=SOURCE_RUN, raw_sha256=raw_sha)]
        path = ledger_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": "public-brief-ledger-v1",
                                    "events": source_events}))

    def tearDown(self):
        self.temp.cleanup()

    def add_event(self, event):
        value = load(self.root)
        value["events"].append(event)
        ledger_path(self.root).write_text(json.dumps(value))

    def register(self):
        return register_historical_prerequisite(self.root, target_prefix=self.prefix,
                                                question_id="q1", record=self.record)

    def test_later_unknown_source_blocks_registration(self):
        self.add_event(dict(event="unknown_outcome", run_id=SOURCE_RUN))
        with self.assertRaises(LedgerStateError):
            self.register()

    def test_existing_target_run_blocks_registration(self):
        self.add_event(dict(event="started", base_key=self.prefix + ":q2"))
        with self.assertRaises(LedgerStateError):
            self.register()

    def test_historical_record_cannot_override_target_failure(self):
        self.register()
        self.add_event(dict(event="major_error_stop", base_key=self.prefix + ":q1"))
        with self.assertRaises(LedgerStateError):
            require_previous_review(self.root, base_key=self.prefix + ":q2")

    def test_idempotent_registration_rechecks_missing_material(self):
        self.register()
        Path(self.record["artifact_paths"]["source_raw"]).unlink()
        with self.assertRaises(LedgerStateError):
            self.register()

    def test_claim_is_bound_to_target_freeze_and_cannot_repeat_q1(self):
        self.register()
        for qid in ("q1", "q2"):
            with self.assertRaises(LedgerStateError):
                claim(self.root, base_key=self.prefix + ":" + qid,
                      metadata={"question_id": qid, "freeze_sha256": "0" * 64})
        claim(self.root, base_key=self.prefix + ":q2", metadata={"question_id": "q2",
              "freeze_sha256": self.record["target_freeze_sha256"]})

    def test_unmatched_material_cannot_be_registered_even_with_updated_hash(self):
        path = Path(self.record["artifact_paths"]["target_request_q3"])
        path.write_text('{"changed": true}')
        self.record["artifact_hashes"]["target_request_q3"] = file_sha256(path)
        with self.assertRaises(LedgerStateError):
            self.register()

    def test_response_usage_edit_cannot_be_registered_even_with_updated_hash(self):
        path = Path(self.record["artifact_paths"]["source_metadata"])
        path.write_text(json.dumps({"finish_reason": "stop", "usage": {"completion_tokens": 1}}))
        self.record["artifact_hashes"]["source_metadata"] = file_sha256(path)
        with self.assertRaisesRegex(LedgerStateError, "响应元数据"):
            self.register()

    def test_changed_generation_parameters_cannot_be_registered(self):
        path = Path(self.record["artifact_paths"]["target_freeze"])
        value = json.loads(path.read_text())
        value["params"]["temperature"] = 1
        path.write_text(json.dumps(value))
        self.record["artifact_hashes"]["target_freeze"] = file_sha256(path)
        self.record["target_freeze_sha256"] = canonical_sha(value)
        with self.assertRaisesRegex(LedgerStateError, "生成参数"):
            self.register()

    def test_register_is_non_consuming_and_unlocks_only_q2(self):
        event = register_historical_prerequisite(self.root, target_prefix=self.prefix,
                                                  question_id="q1", record=self.record)
        self.assertEqual(event["event"], HISTORICAL_PREREQUISITE_EVENT)
        self.assertEqual(len(load(self.root)["events"]), 3)
        require_previous_review(self.root, base_key=self.prefix + ":q2")
        with self.assertRaisesRegex(LedgerStateError, "q2"):
            require_previous_review(self.root, base_key=self.prefix + ":q3")

    def test_exact_duplicate_is_idempotent_conflict_is_rejected(self):
        first = register_historical_prerequisite(self.root, target_prefix=self.prefix,
                                                  question_id="q1", record=self.record)
        second = register_historical_prerequisite(self.root, target_prefix=self.prefix,
                                                   question_id="q1", record=self.record)
        self.assertEqual(first, second)
        changed = copy.deepcopy(self.record)
        changed["reviewer"] = "different"
        with self.assertRaises(DuplicatePublicRun):
            register_historical_prerequisite(self.root, target_prefix=self.prefix,
                                              question_id="q1", record=changed)

    def test_tampered_material_or_unknown_source_cannot_unlock(self):
        event = register_historical_prerequisite(self.root, target_prefix=self.prefix,
                                                  question_id="q1", record=self.record)
        ledger_file = ledger_path(self.root)
        value = json.loads(ledger_file.read_text())
        value["events"][-1]["artifact_hashes"]["source_review"] = "0" * 64
        ledger_file.write_text(json.dumps(value))
        with self.assertRaisesRegex(LedgerStateError, "摘要"):
            require_previous_review(self.root, base_key=self.prefix + ":q2")

    def test_major_or_unknown_prerequisite_is_rejected_by_registration(self):
        changed = copy.deepcopy(self.record)
        changed["verdict"] = "major_error"
        changed["checks"] = {k: {"passed": False, "reason": "重大错误"}
                              for k in ("structure", "facts", "relevance", "usefulness")}
        with self.assertRaises(ValueError):
            register_historical_prerequisite(self.root, target_prefix=self.prefix,
                                              question_id="q1", record=changed)

    def test_target_freeze_or_material_change_is_rejected_before_registration(self):
        changed = copy.deepcopy(self.record)
        changed["target_freeze_sha256"] = "0" * 64
        with self.assertRaises(LedgerStateError):
            register_historical_prerequisite(self.root, target_prefix=self.prefix,
                                              question_id="q1", record=changed)


if __name__ == "__main__":
    unittest.main()
