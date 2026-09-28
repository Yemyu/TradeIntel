"""Exact-value compression: no policy/source text may move out of messages."""
from copy import deepcopy
import unittest

from src.tradeintel_ai.brief_business_view import build_view, business_payload, restore, view_request, adapt_answer
from src.tradeintel_ai.brief_fact_catalog import build_fact_catalog
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle
from src.tradeintel_ai.evidence_linked_brief import validate
from scripts.run_fake_experiment import _fake_answer_from_view
from tests.test_e1_hardening import sheet_with, trade_with


class LosslessViewDedupTests(unittest.TestCase):
    def setUp(self):
        clause = "完整条件：未知未来税率必须待公告，不是豁免。" * 8
        details = {code: {"conditions": {"status": "known", "text": [clause]},
                          "exceptions": {"status": "known", "text": ["独有例外不能删除" + code]}}
                   for code in ("11111111", "22222222")}
        sheet = sheet_with(details)
        for i in range(6):
            sheet["sources"].append({"id": f"policy:extra{i}",
                "url": "https://example.test/long-original-source-document",
                "text": f"独有来源正文{i}\n  保留空白。", "doc_version": "version-1",
                "section_id": f"p{i}"})
        # Preserve missing vs explicit null, even across grouped records.
        sheet["sources"][-1]["optional"] = None
        self.catalog = build_fact_catalog(build_evidence_bundle(
            trade_with([("11111111", 1000, 700), ("22222222", 9000, 900)]), sheet))
        self.before = deepcopy(self.catalog)
        self.view, self.sidecar = build_view("解释差异", self.catalog, deduplicate=True)

    def test_exact_roundtrip_and_input_not_mutated(self):
        self.assertEqual(restore(self.view, self.sidecar), business_payload(self.catalog))
        self.assertEqual(self.catalog, self.before)

    def test_every_source_text_and_url_still_in_request(self):
        content = view_request(self.view)[1]["content"]
        import json
        decoded = json.loads(content)
        strings = []
        def walk(node):
            if isinstance(node, str): strings.append(node)
            elif isinstance(node, dict):
                for value in node.values(): walk(value)
            elif isinstance(node, list):
                for value in node: walk(value)
        walk(decoded)
        for source in self.catalog["sources"]:
            for field in ("text", "url"):
                if isinstance(source.get(field), str): self.assertIn(source[field], strings)
        for row in self.catalog["policy_facts"]["product_rates"]:
            for section in ("conditions", "exceptions"):
                for text in row["details"][section]["text"]: self.assertIn(text, strings)

    def test_duplicate_clause_is_stored_once(self):
        clauses = self.view["shared_values"]
        self.assertEqual(sum(value.startswith("完整条件") for value in clauses.values()), 1)
        self.assertTrue(self.sidecar["value_refs"])

    def test_missing_shared_value_refused(self):
        self.view["shared_values"].clear()
        with self.assertRaises(ValueError): restore(self.view, self.sidecar)

    def test_broken_source_table_refused(self):
        self.view["source_groups"][0]["rows"][0].append("extra")
        with self.assertRaises(ValueError): restore(self.view, self.sidecar)

    def test_changed_marker_refused(self):
        entry = next(e for e in self.sidecar["value_refs"] if e["path"][0] == "policy_facts")
        from src.tradeintel_ai.brief_business_view import _walk
        parent = _walk(self.view["business"], entry["path"][:-1])
        parent[int(entry["path"][-1])] = {"shared_value": "wrong"}
        with self.assertRaises(ValueError): restore(self.view, self.sidecar)

    def test_adapter_and_original_validator_still_work(self):
        answer = _fake_answer_from_view(self.view, "两种排序衡量不同问题，尚需核查企业采购资料。")
        converted = adapt_answer(answer, self.view, self.sidecar, self.catalog)
        self.assertEqual(validate(converted, self.catalog)["status"], "manual_review_required")

    def test_original_format_is_unchanged_and_readable(self):
        view, sidecar = build_view("解释差异", self.catalog)
        self.assertNotIn("source_groups", view)
        self.assertNotIn("value_refs", sidecar)
        self.assertEqual(restore(view, sidecar), business_payload(self.catalog))

    def _package(self):
        import json
        import hashlib
        import tempfile
        from pathlib import Path
        from scripts.prepare_brief_view_offline import REQUIRED_FILES, READY_STATUS, MANIFEST_SCHEMA
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        values = {"catalog.json": self.catalog, "business-view.json": self.view,
                  "business-view-sidecar.json": self.sidecar,
                  "messages.json": view_request(self.view)}
        for name, value in values.items():
            (root / name).write_text(json.dumps(value, ensure_ascii=False))
        (root / "program-report-A3.zh-CN.md").write_text("test program report")
        def seal():
            manifest = {"schema_version": MANIFEST_SCHEMA, "status": READY_STATUS, "callable": False,
                        "question": self.view["question"], "required_files": list(REQUIRED_FILES),
                        "binding": {"view_catalog_sha256": self.catalog["catalog_sha256"]},
                        "artifact_files_sha256": {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
                                                  for name in REQUIRED_FILES}}
            (root / "manifest.json").write_text(json.dumps(manifest))
        seal()
        return root, seal

    def test_resealed_changed_clause_cannot_bypass_catalog(self):
        import json
        from src.tradeintel_ai.provider_executor import _load_view_package
        root, seal = self._package()
        altered = deepcopy(self.view)
        key = next(iter(altered["shared_values"]))
        altered["shared_values"][key] = "changed"
        (root / "business-view.json").write_text(json.dumps(altered))
        (root / "messages.json").write_text(json.dumps(view_request(altered)))
        seal()
        with self.assertRaisesRegex(ValueError, "complete catalog"):
            _load_view_package(root)

    def test_resealed_incomplete_actual_request_refused(self):
        import json
        from src.tradeintel_ai.provider_executor import _load_view_package
        root, seal = self._package()
        messages = view_request(self.view)
        messages[1]["content"] = "only a summary"
        (root / "messages.json").write_text(json.dumps(messages))
        seal()
        with self.assertRaisesRegex(ValueError, "actual request"):
            _load_view_package(root)


if __name__ == "__main__": unittest.main()
