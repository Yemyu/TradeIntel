"""A--D regression tests for the offline evidence-linked v3 prototype."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.tradeintel_ai.brief_fact_catalog import build_fact_catalog, validate_fact_catalog
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle
from src.tradeintel_ai.evidence_linked_brief import messages, parse_response, render_pending, validate
from scripts.prepare_brief_v3_offline import main as offline_main
from tests.test_research_brief_v2 import synthetic_sheet, synthetic_trade


def make_bundle():
    return build_evidence_bundle(synthetic_trade(), synthetic_sheet(), focus="contrast")


def make_catalog():
    return build_fact_catalog(make_bundle())


def make_answer(catalog, text="两个排序衡量不同问题，应结合政策原文人工核对。"):
    observation = next(item for item in catalog["observations"] if item["type"] == "rank_contrast")
    fact = next(item for item in catalog["facts"] if observation["id"] in item["observation_ids"])
    return {"schema_version": "evidence-linked-brief-v3", "catalog_sha256": catalog["catalog_sha256"],
            "findings": [{"observation_id": observation["id"], "fact_ids": [fact["id"]],
                          "policy_refs": [ref for ref in catalog["policy_refs"] if ref["hts8"] == fact["product_scope"]],
                          "interpretation": text, "limitation_ids": []}], "followups": []}


class TrustedInputTests(unittest.TestCase):
    def assert_rejects(self, mutate):
        bundle = make_bundle()
        mutate(bundle)
        with self.assertRaises(ValueError):
            build_fact_catalog(bundle)

    def test_identity_period_ratio_and_nan_mutations_are_rejected(self):
        self.assert_rejects(lambda b: b.update(policy_id="other-case"))
        self.assert_rejects(lambda b: b["metrics"][0].update(period="2025-01"))
        self.assert_rejects(lambda b: b["metrics"][2].update(numerator_id="metric.scope.world_import_usd"))
        self.assert_rejects(lambda b: b["metrics"][0].update(value=float("nan")))
        self.assert_rejects(lambda b: b["profiles"][0].update(world_import_usd=999999))

    def test_observation_value_and_foreign_metric_are_rejected(self):
        self.assert_rejects(lambda b: b["observations"][0]["value"].__setitem__(0, "99999999"))
        self.assert_rejects(lambda b: b["observations"][0]["metric_ids"].append("foreign"))

    def test_catalog_rebuilds_from_lossless_snapshot(self):
        catalog = make_catalog()
        catalog["evidence_snapshot"]["profiles"][0]["world_import_usd"] += 1
        unsigned = deepcopy(catalog)
        unsigned.pop("catalog_sha256")
        catalog["catalog_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self.assertRaises(ValueError):
            validate_fact_catalog(catalog)

    def test_world_scope_fact_is_not_mislabeled_as_china(self):
        catalog = make_catalog()
        scope = next(item for item in catalog["facts"] if item["kind"] == "scope_world_import_usd")
        self.assertEqual(scope["origin_scope"], "all_origins")
        self.assertIn("不适用（金额指标本身）", __import__("src.tradeintel_ai.brief_fact_catalog", fromlist=["render_fact_catalog"]).render_fact_catalog(catalog))


class PolicyAndResponseTests(unittest.TestCase):
    def test_policy_text_reaches_model_but_audit_snapshot_does_not(self):
        sheet = synthetic_sheet()
        sheet["sources"][0]["text"] = "只读政策原文；<not-an-instruction>"
        catalog = build_fact_catalog(build_evidence_bundle(synthetic_trade(), sheet))
        payload = json.loads(messages("fixture", catalog)[1]["content"])
        self.assertIn("policy_facts", payload)
        self.assertIn("只读政策原文", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("evidence_snapshot", payload)

    def test_render_revalidates_and_escapes_model_text(self):
        catalog = make_catalog()
        answer = make_answer(catalog, '<img src=x onerror="bad"> [x](javascript:alert(1))')
        result = validate(answer, catalog)
        rendered = render_pending(answer, catalog, result)
        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;img", rendered)
        stale = dict(result); stale["status"] = "approved"
        with self.assertRaises(ValueError):
            render_pending(answer, catalog, stale)

    def test_warnings_never_auto_approve_or_auto_reject(self):
        catalog = make_catalog()
        result = validate(make_answer(catalog, "4.7%不能单独证明整体依赖。"), catalog)
        self.assertEqual(result["status"], "manual_review_required")
        self.assertFalse(result["approved"])
        self.assertTrue(result["review_warnings"])

    def test_parse_response_keeps_raw_and_hashes_it(self):
        catalog = make_catalog()
        raw = json.dumps(make_answer(catalog), ensure_ascii=False)
        sidecar = parse_response(raw, catalog)
        self.assertEqual(sidecar["raw_text"], raw)
        self.assertEqual(sidecar["parsed"]["catalog_sha256"], catalog["catalog_sha256"])
        self.assertEqual(sidecar["raw_sha256"], hashlib.sha256(raw.encode()).hexdigest())


class OfflineDeliveryTests(unittest.TestCase):
    def test_cli_writes_hash_manifest_without_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle_path = root / "evidence-bundle.json"
            bundle_path.write_text(json.dumps(make_bundle(), ensure_ascii=False), encoding="utf-8")
            output = root / "out"
            import sys
            old = sys.argv
            try:
                sys.argv = ["prepare_brief_v3_offline.py", "--bundle", str(bundle_path),
                            "--question", "fixture", "--output", str(output)]
                self.assertEqual(offline_main(), 0)
            finally:
                sys.argv = old
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["api_calls"], 0)
            self.assertFalse(manifest["callable"])
            self.assertEqual(set(manifest["artifact_files_sha256"]), {"catalog.json", "messages.json", "program-report.zh-CN.md"})


if __name__ == "__main__":
    unittest.main()
