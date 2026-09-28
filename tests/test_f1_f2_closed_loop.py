"""F1/F2 acceptance tests: real prepare->fake closed loop and the short-ID
response adapter, including every rejection path from the R1 review."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from src.tradeintel_ai.brief_business_view import adapt_answer, build_view, view_request
from src.tradeintel_ai.brief_fact_catalog import build_fact_catalog
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle
from src.tradeintel_ai.evidence_linked_brief import validate as v3_validate
from tests.test_e1_hardening import sheet_with, trade_with
from scripts.prepare_brief_v3_offline import estimate_input_tokens


def make_bundle():
    return build_evidence_bundle(trade_with([("11111111", 1000, 700), ("22222222", 9000, 900)]),
                                 sheet_with())


def _prepare(root: Path) -> Path:
    bundle_path = root / "evidence-bundle.json"
    bundle_path.write_text(json.dumps(make_bundle(), ensure_ascii=False), encoding="utf-8")
    from scripts.prepare_brief_view_offline import main as prepare_main
    argv = sys.argv
    try:
        sys.argv = ["prepare_brief_view_offline.py", "--bundle", str(bundle_path),
                    "--question", "两个排序有什么区别？", "--output", str(root / "package")]
        self_exit = prepare_main()
    finally:
        sys.argv = argv
    assert self_exit == 0, self_exit
    return root / "package"


def _run_fake(package: Path, output: Path, fake_text: str | None = None) -> int:
    from scripts.run_fake_experiment import main as run_main
    argv = sys.argv
    try:
        argv_list = ["run_fake_experiment.py", "--package", str(package),
                     "--output", str(output)]
        if fake_text is not None:
            argv_list += ["--fake-text", fake_text]
        sys.argv = argv_list
        return run_main()
    finally:
        sys.argv = argv


class ClosedLoopTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="f1-loop-"))
        self.package = _prepare(self.root)

    def test_prepare_then_fake_succeed_end_to_end(self):
        run_dir = self.root / "run"
        self.assertEqual(_run_fake(self.package, run_dir), 0)
        run = json.loads((run_dir / "run-manifest.json").read_text())
        self.assertEqual(run["status"], "fake_response_validated")
        self.assertEqual(run["package_schema"], "brief-view-offline-manifest-v1")
        self.assertTrue(run["adapter"]["used"])
        self.assertEqual(run["validation_status"], "manual_review_required")
        # The short-ID raw answer really uses aliases, the converted answer
        # really uses full IDs, and prose is untouched between the two.
        raw = json.loads((run_dir / "fake-answer.short-id.raw.json").read_text())
        converted = json.loads((run_dir / "fake-answer.converted.json").read_text())
        self.assertNotEqual(raw["findings"][0]["observation_id"],
                            converted["findings"][0]["observation_id"])
        self.assertEqual(raw["findings"][0]["interpretation"],
                         converted["findings"][0]["interpretation"])

    def test_actual_request_estimation_gates_only_actual(self):
        manifest = json.loads((self.package / "manifest.json").read_text())
        self.assertEqual(manifest["input_estimate"]["applies_to"], "actual_messages")
        self.assertEqual(manifest["raw_v3_diagnostic"]["applies_to"],
                         "diagnostic_only_never_gates")
        messages = json.loads((self.package / "messages.json").read_text())
        self.assertEqual(estimate_input_tokens(messages)["tokens"],
                         manifest["input_estimate"]["tokens"])

    def _tampered_copy(self, mutate) -> Path:
        broken = self.root / "broken"
        shutil.copytree(self.package, broken)
        mutate(broken)
        return broken

    def test_missing_required_file_is_refused(self):
        broken = self._tampered_copy(lambda p: (p / "business-view-sidecar.json").unlink())
        with self.assertRaises(SystemExit):
            _run_fake(broken, self.root / "run1")

    def test_modified_question_is_refused(self):
        def mutate(package: Path):
            manifest = json.loads((package / "manifest.json").read_text())
            messages = json.loads((package / "messages.json").read_text())
            messages[1]["content"] = json.dumps({"question": "被篡改的问题"}, ensure_ascii=False)
            (package / "messages.json").write_text(
                json.dumps(messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        broken = self._tampered_copy(mutate)
        with self.assertRaises(SystemExit):
            _run_fake(broken, self.root / "run2")

    def test_modified_sidecar_is_refused(self):
        def mutate(package: Path):
            sidecar = json.loads((package / "business-view-sidecar.json").read_text())
            sidecar["id_map"].pop(next(iter(sidecar["id_map"])))
            (package / "business-view-sidecar.json").write_text(
                json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        broken = self._tampered_copy(mutate)
        with self.assertRaises(SystemExit):
            _run_fake(broken, self.root / "run3")

    def test_empty_hash_list_is_refused(self):
        def mutate(package: Path):
            manifest = json.loads((package / "manifest.json").read_text())
            manifest["artifact_files_sha256"] = {}
            manifest["required_files"] = list(manifest["required_files"])
            (package / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        broken = self._tampered_copy(mutate)
        with self.assertRaises(SystemExit):
            _run_fake(broken, self.root / "run4")

    def test_interrupted_package_is_refused(self):
        interrupted = self.root / "interrupted"
        interrupted.mkdir()
        shutil.copy(self.package / "catalog.json", interrupted / "catalog.json")
        with self.assertRaises(SystemExit):
            _run_fake(interrupted, self.root / "run5")

    def test_output_over_gate_blocks_success_status(self):
        run_dir = self.root / "run6"
        # 3 findings x 280 Chinese chars still validate (<=300 each) but the
        # combined output estimate exceeds the 2000 gate.
        exit_code = _run_fake(self.package, run_dir, fake_text="长" * 280)
        self.assertEqual(exit_code, 2)
        run = json.loads((run_dir / "run-manifest.json").read_text())
        self.assertEqual(run["status"], "blocked_output_budget")
        self.assertFalse(run["output_within_gate"])
        self.assertFalse(run.get("artifact_files_sha256"))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        catalog = build_fact_catalog(make_bundle())
        view, sidecar = build_view("两个排序有什么区别？", catalog)
        self.catalog, self.view, self.sidecar = catalog, view, sidecar

    def _view_answer(self):
        business = self.view["business"]
        observation = business["observations"][0]
        fact = next(f for f in business["facts"]
                    if observation["id"] in (f.get("observation_ids") or []))
        refs = [r for r in business["policy_refs"] if r["hts8"] == fact["product_scope"]]
        return {"schema_version": "evidence-linked-brief-v3",
                "catalog_sha256": self.view["policy"]["catalog_sha256"],
                "findings": [{"observation_id": observation["id"],
                              "fact_ids": [fact["id"]], "policy_refs": refs,
                              "interpretation": "解释原文含f1与o99字样保持原样。",
                              "limitation_ids": []}],
                "followups": []}

    def test_adapter_converts_only_id_fields(self):
        answer = self._view_answer()
        converted = adapt_answer(answer, self.view, self.sidecar, self.catalog)
        self.assertNotEqual(converted["findings"][0]["observation_id"],
                            answer["findings"][0]["observation_id"])
        result = v3_validate(converted, self.catalog)
        self.assertEqual(result["status"], "manual_review_required")
        self.assertIn("解释原文含f1与o99字样保持原样。",
                      converted["findings"][0]["interpretation"])

    def test_unknown_alias_is_rejected_by_validation(self):
        answer = self._view_answer()
        answer["findings"][0]["observation_id"] = "o999"
        converted = adapt_answer(answer, self.view, self.sidecar, self.catalog)
        with self.assertRaises(ValueError):
            v3_validate(converted, self.catalog)

    def test_cross_package_alias_is_rejected(self):
        # An answer generated against ANOTHER package carries the other
        # catalog binding; the adapter rejects it before any ID conversion.
        other = build_fact_catalog(build_evidence_bundle(
            trade_with([("11111111", 2000, 1400), ("22222222", 9000, 900)]), sheet_with()))
        other_view, other_sidecar = build_view("另包问题", other)
        business = other_view["business"]
        observation = business["observations"][0]
        fact = next(f for f in business["facts"]
                    if observation["id"] in (f.get("observation_ids") or []))
        foreign_answer = {"schema_version": "evidence-linked-brief-v3",
                          "catalog_sha256": other_view["policy"]["catalog_sha256"],
                          "findings": [{"observation_id": observation["id"],
                                        "fact_ids": [fact["id"]],
                                        "policy_refs": [], "interpretation": "外包回答。",
                                        "limitation_ids": []}],
                          "followups": []}
        with self.assertRaises(ValueError):
            adapt_answer(foreign_answer, self.view, self.sidecar, self.catalog)

    def test_catalog_binding_mismatch_is_rejected_immediately(self):
        answer = self._view_answer()
        answer["catalog_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            adapt_answer(answer, self.view, self.sidecar, self.catalog)
        with self.assertRaises(ValueError):
            adapt_answer(answer, self.view, self.sidecar,
                         {**self.catalog, "catalog_sha256": "1" * 64})

    def test_prose_with_alias_like_tokens_is_untouched(self):
        answer = self._view_answer()
        answer["findings"][0]["interpretation"] = "s1 f2 m3 l4 都只是原文，不转换。"
        converted = adapt_answer(answer, self.view, self.sidecar, self.catalog)
        self.assertEqual(converted["findings"][0]["interpretation"],
                         "s1 f2 m3 l4 都只是原文，不转换。")


if __name__ == "__main__":
    unittest.main()
