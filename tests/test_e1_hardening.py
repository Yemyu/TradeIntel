"""E1 hardening regression tests.

Covers the Astra counter-example list for the offline v3 prototype: malformed
IDs, zero denominators, tied leaders, single-product 100%, wrong origin/HTS/
version, missing citations, duplicate JSON keys, conflicting duplicated source
text, unknown conditions/exceptions reaching the report and the model input,
the complete A3 program report, the reversible compact business view, and the
fake experiment executor.  Everything is offline; no model is called.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.tradeintel_ai.brief_business_view import business_payload, build_view, restore, view_request
from src.tradeintel_ai.brief_fact_catalog import build_fact_catalog, render_fact_catalog, validate_fact_catalog
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle
from src.tradeintel_ai.evidence_linked_brief import messages, parse_response, validate
from scripts.prepare_brief_v3_offline import estimate_input_tokens
from tests.test_v3_repairs import make_answer, make_catalog

MONTH = "2026-07"


def trade_with(rows):
    """rows: list of (hts8, world, china) for one month."""
    return {"status": "ok", "data_version": "v1",
            "data": {"policy_id": "fixture-policy", "coverage_complete": True,
                     "measure": "import_value_consumption_usd", "origin": "China",
                     "hts8": None, "requested_months": [MONTH],
                     "series": [{"month": MONTH, "product_breakdown": [
                         {"hts8": code, "all_origins_value_usd": world,
                          "china_value_usd": china, "china_share_percent": None}
                         for code, world, china in rows]}]},
            "limitations": ["没有企业实际税单。"],
            "evidence": {"sources": [{"id": "trade:t1", "url": "https://example.test/data"}]}}


def sheet_with(details_for=None, **overrides):
    sheet = {"policy_id": "fixture-policy", "data_version": "v1",
             "sources": [{"id": "policy:p1", "url": "https://example.test/policy",
                          "text": "共享条款原文。"}],
             "product_rates": [{"hts8": "11111111", "source_id": "policy:p1"},
                               {"hts8": "22222222", "source_id": "policy:p1"}],
             "origin": "中国原产", "effective_date": "2025-01-01",
             "clock_24h": "00:01", "timezone": "美国东部标准时间（EST）",
             "entry_events": ["消费入境", "从仓库提取消费"],
             "limitations": ["政策条款是存档视图。"]}
    sheet.update(overrides)
    if details_for:
        for row in sheet["product_rates"]:
            if row["hts8"] in details_for:
                row["details"] = deepcopy(details_for[row["hts8"]])
    return sheet


def catalog_with(rows, details_for=None, **sheet_overrides):
    return build_fact_catalog(build_evidence_bundle(
        trade_with(rows), sheet_with(details_for, **sheet_overrides)))


def answer_for(catalog, text="两个排序衡量不同问题，应结合政策原文人工核对。"):
    observation = catalog["observations"][0]
    fact = next(item for item in catalog["facts"] if observation["id"] in item["observation_ids"])
    return {"schema_version": "evidence-linked-brief-v3", "catalog_sha256": catalog["catalog_sha256"],
            "findings": [{"observation_id": observation["id"], "fact_ids": [fact["id"]],
                          "policy_refs": [ref for ref in catalog["policy_refs"]
                                          if ref["hts8"] == fact["product_scope"]],
                          "interpretation": text, "limitation_ids": []}],
            "followups": []}


class MalformedInputTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_catalog()

    def assert_controlled(self, mutate):
        answer = make_answer(self.catalog)
        mutate(answer)
        with self.assertRaises(ValueError):
            validate(answer, self.catalog)

    def test_observation_id_type_is_checked_before_hashing(self):
        for bad in ({}, [], True, False, None, 3, 4.7):
            with self.subTest(bad=bad):
                self.assert_controlled(lambda a, value=bad: a["findings"][0].__setitem__(
                    "observation_id", value))

    def test_source_id_and_hts8_types_are_checked_before_membership(self):
        self.assert_controlled(lambda a: a["findings"][0]["policy_refs"].__setitem__(
            0, {"source_id": {"x": 1}, "hts8": "28046100"}))
        self.assert_controlled(lambda a: a["findings"][0]["policy_refs"].__setitem__(
            0, {"source_id": [], "hts8": "28046100"}))
        self.assert_controlled(lambda a: a["findings"][0]["policy_refs"].__setitem__(
            0, {"source_id": "trade:t1", "hts8": {"x": 1}}))
        self.assert_controlled(lambda a: a["findings"][0]["policy_refs"].__setitem__(
            0, {"source_id": "trade:t1", "hts8": "280461"}))

    def test_malformed_limitation_and_fact_ids_raise_valueerror(self):
        self.assert_controlled(lambda a: a["findings"][0].__setitem__("limitation_ids", [{"x": 1}]))
        self.assert_controlled(lambda a: a["findings"][0].__setitem__("fact_ids", [{"x": 1}]))

    def test_duplicate_observation_id_is_rejected(self):
        answer = make_answer(self.catalog)
        answer["findings"].append(deepcopy(answer["findings"][0]))
        with self.assertRaises(ValueError):
            validate(answer, self.catalog)

    def test_missing_policy_citation_is_not_silent(self):
        self.assert_controlled(lambda a: a["findings"][0].__setitem__("policy_refs", []))

    def test_duplicate_json_keys_are_rejected(self):
        raw = ('{"schema_version":"evidence-linked-brief-v3","catalog_sha256":"x",'
               '"findings":[],"followups":[],"findings":[]}')
        with self.assertRaises(ValueError):
            parse_response(raw, self.catalog)


class CounterExampleTests(unittest.TestCase):
    def test_zero_denominator_is_unknown_not_zero(self):
        catalog = catalog_with([("11111111", 0, 0), ("22222222", 9000, 900)])
        share = next(fact for fact in catalog["facts"]
                     if fact["kind"] == "china_share_of_product_percent"
                     and fact["product_scope"] == "11111111")
        self.assertEqual(share["status"], "unknown")
        self.assertIn("未知", share["text"])
        self.assertIn("不能补零", share["text"])
        report = render_fact_catalog(catalog)
        self.assertIn("未知原因", report)
        self.assertIn("分母为零", report)

    def test_tied_amount_leaders_are_all_reported(self):
        catalog = catalog_with([("11111111", 1000, 700), ("22222222", 9000, 700)])
        leaders = next(item for item in catalog["observations"] if item["type"] == "amount_leader")
        self.assertEqual(leaders["value"], ["11111111", "22222222"])
        report = render_fact_catalog(catalog)
        self.assertIn("并列", report)
        self.assertIn("11111111", report)
        self.assertIn("22222222", report)

    def test_tied_share_leaders_are_all_reported(self):
        catalog = catalog_with([("11111111", 1000, 500), ("22222222", 2000, 1000)])
        leaders = next(item for item in catalog["observations"] if item["type"] == "share_leader")
        self.assertEqual(leaders["value"], ["11111111", "22222222"])

    def test_single_product_100_percent_is_scoped_to_selection(self):
        catalog = catalog_with([("81019910", 800, 800)],
                               product_rates=[{"hts8": "81019910", "source_id": "policy:p1"}])
        share = next(fact for fact in catalog["facts"]
                     if fact["kind"] == "china_share_of_product_percent")
        self.assertEqual(share["status"], "known")
        self.assertIn("100%", share["text"])
        self.assertIn("仅表示该统计期该商品美国消费进口的原产地构成", share["text"])
        report = render_fact_catalog(catalog).replace("\\_", "_")
        self.assertIn("single_product_profile", report)
        self.assertIn("仅指本次所选范围的构成", report)

    def test_china_amount_above_world_is_rejected(self):
        with self.assertRaises(ValueError):
            catalog_with([("11111111", 100, 200), ("22222222", 9000, 900)])

    def test_wrong_hts8_format_is_rejected(self):
        with self.assertRaises(ValueError):
            catalog_with([("1111111", 1000, 700), ("22222222", 9000, 900)])
        sheet = sheet_with()
        sheet["product_rates"][0]["hts8"] = "123456789"
        with self.assertRaises(ValueError):
            build_fact_catalog(build_evidence_bundle(trade_with(
                [("11111111", 1000, 700), ("22222222", 9000, 900)]), sheet))

    def test_wrong_version_and_identity_are_rejected(self):
        sheet = sheet_with(data_version="v2")
        with self.assertRaises(ValueError):
            build_fact_catalog(build_evidence_bundle(trade_with(
                [("11111111", 1000, 700), ("22222222", 9000, 900)]), sheet))
        catalog = make_catalog()
        answer = make_answer(catalog)
        answer["catalog_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate(answer, catalog)

    def test_requested_products_must_exactly_match_profiles(self):
        catalog = catalog_with([("11111111", 1000, 700), ("22222222", 9000, 900)])
        snapshot = catalog["evidence_snapshot"]
        snapshot["policy_facts"]["requested_products"] = ["11111111"]
        with self.assertRaises(ValueError):
            build_fact_catalog(snapshot)

    def test_missing_metric_field_differs_from_explicit_unknown(self):
        catalog = catalog_with([("11111111", 1000, 700), ("22222222", 9000, 900)])
        snapshot = catalog["evidence_snapshot"]
        del snapshot["metrics"][2]["value"]
        with self.assertRaises(ValueError):
            build_fact_catalog(snapshot)

    def test_same_source_id_with_two_texts_is_rejected(self):
        catalog = catalog_with([("11111111", 1000, 700), ("22222222", 9000, 900)])
        snapshot = catalog["evidence_snapshot"]
        snapshot["policy_facts"]["sources"][0]["text"] = "被篡改的另一份文本。"
        with self.assertRaises(ValueError):
            build_fact_catalog(snapshot)


class CompleteReportTests(unittest.TestCase):
    def setUp(self):
        clause = "所列税号中用于旋涂、曝光工序的光刻胶产品，须在申报时注明用途；本段为共享上下文。"
        details = {
            "original_scope_clause": clause,
            "conditions": {"status": "unknown", "reason": "独有条件原因XYZ未逐笔核验。"},
            "exceptions": {"status": "unknown", "reason": "独有例外原因ABC未核全章98与排除清单。"},
        }
        self.catalog = catalog_with([("11111111", 1000, 700), ("22222222", 9000, 900)],
                                    details_for={"11111111": details, "22222222": dict(details)})
        self.report = render_fact_catalog(self.catalog)

    def test_every_observation_and_tie_reaches_the_report(self):
        for observation in self.catalog["observations"]:
            self.assertIn(observation["id"].replace("_", ""), self.report.replace("\\_", ""))

    def test_rate_meaning_and_scope_snapshot_reach_the_report(self):
        for marker in ("存档额外税率", "不是现行综合税则", "中国原产", "2025-01-01",
                       "美国东部标准时间（EST）", "消费入境", "从仓库提取消费", "00:01"):
            self.assertIn(marker, self.report)

    def test_unique_condition_and_exception_strings_reach_report_and_model_input(self):
        self.assertIn("独有条件原因XYZ未逐笔核验。", self.report)
        self.assertIn("独有例外原因ABC未核全章98与排除清单。", self.report)
        payload = json.loads(messages("fixture", self.catalog)[1]["content"])
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertIn("独有条件原因XYZ未逐笔核验。", blob)
        self.assertIn("独有例外原因ABC未核全章98与排除清单。", blob)

    def test_identical_clause_text_is_printed_once_with_citations(self):
        clause = "所列税号中用于旋涂、曝光工序的光刻胶产品，须在申报时注明用途；本段为共享上下文。"
        self.assertEqual(self.report.count(clause), 1)
        self.assertIn("[S1]", self.report)
        self.assertIn("trade:t1", self.report)
        self.assertIn("https://example.test/policy", self.report)

    def test_all_limitations_reach_the_report(self):
        for limitation in self.catalog["limitations"]:
            self.assertIn(limitation["text"], self.report)

    def test_report_does_not_fabricate_missing_rates(self):
        catalog = self.catalog
        snapshot = catalog["evidence_snapshot"]
        for row in snapshot["policy_facts"]["product_rates"]:
            row.pop("additional_duty_percent", None)
        stripped = build_fact_catalog(snapshot)
        self.assertIn("未提供（该版本未记录此字段，不能补零）", render_fact_catalog(stripped))


class BusinessViewTests(unittest.TestCase):
    def setUp(self):
        clause = "所列税号中用于旋涂、曝光工序的光刻胶产品，须在申报时注明用途；本段为共享上下文。"
        details = {"original_scope_clause": clause,
                   "conditions": {"status": "unknown", "reason": "独有条件原因XYZ未逐笔核验。"},
                   "exceptions": {"status": "unknown", "reason": "独有例外原因ABC未核全章98与排除清单。"}}
        self.catalog = catalog_with([("11111111", 1000, 700), ("22222222", 9000, 900)],
                                    details_for={"11111111": details, "22222222": dict(details)})
        self.question = "2026年7月两个排序有什么区别？"
        self.view, self.sidecar = build_view(self.question, self.catalog)
        self.payload = business_payload(self.catalog)

    def test_restore_equals_original_payload(self):
        self.assertEqual(restore(self.view, self.sidecar), self.payload)

    def test_sidecar_does_not_contain_a_payload_copy(self):
        blob = json.dumps(self.sidecar, ensure_ascii=False)
        # Only machine fields, ID mappings, paths and equality relations --
        # never the business text itself (clauses, fact sentences, sources).
        self.assertNotIn("共享条款原文", blob)
        self.assertNotIn("统计期", blob)
        self.assertNotIn("消费进口金额", blob)
        self.assertIn("id_map", blob)
        self.assertIn("clause_refs", blob)

    def test_view_is_readable_and_keeps_full_meaning(self):
        business = self.view["business"]
        self.assertTrue(all(fact["text"] for fact in business["facts"]))
        self.assertEqual(len(business["sources"]), 2)
        self.assertTrue(all(source.get("url") for source in business["sources"]))
        self.assertIn("独有条件原因XYZ未逐笔核验。",
                      json.dumps(self.view, ensure_ascii=False))
        # One identical clause + two identical unknown reasons, each stored once.
        self.assertEqual(len(self.view["shared_clauses"]), 3)
        clause = next(text for key, text in self.view["shared_clauses"].items()
                      if key.startswith("text_") and "共享上下文" in text)
        self.assertIn("共享上下文", clause)
        self.assertEqual(self.view["question"], self.question)
        self.assertEqual(self.view["policy"]["catalog_sha256"], self.catalog["catalog_sha256"])

    def test_policy_prose_is_not_abbreviated(self):
        blob = json.dumps(self.view["business"], ensure_ascii=False)
        self.assertIn("共享条款原文。", blob)
        self.assertNotIn("f1：", blob)

    def test_tampered_sidecar_breaks_restore(self):
        sidecar = deepcopy(self.sidecar)
        sidecar["id_map"].pop(next(iter(sidecar["id_map"])))
        self.assertNotEqual(restore(self.view, sidecar), self.payload)

    def test_view_request_estimate_is_recorded(self):
        estimate = estimate_input_tokens(view_request(self.view))
        self.assertLess(int(estimate["tokens"]), 16000)


class FakeExecutorTests(unittest.TestCase):
    def _prepare(self, root):
        bundle_path = root / "evidence-bundle.json"
        bundle_path.write_text(json.dumps(build_evidence_bundle(
            trade_with([("11111111", 1000, 700), ("22222222", 9000, 900)]),
            sheet_with()), ensure_ascii=False), encoding="utf-8")
        package = root / "package"
        from scripts.prepare_brief_v3_offline import main as prepare_main
        argv = sys.argv
        try:
            sys.argv = ["prepare_brief_v3_offline.py", "--bundle", str(bundle_path),
                        "--question", "fixture", "--output", str(package)]
            self.assertEqual(prepare_main(), 0)
        finally:
            sys.argv = argv
        return package

    def _run_executor(self, package, output):
        from scripts.run_fake_experiment import main as run_main
        argv = sys.argv
        try:
            sys.argv = ["run_fake_experiment.py", "--package", str(package),
                        "--output", str(output)]
            return run_main()
        finally:
            sys.argv = argv

    def test_fake_executor_validates_and_writes_manifest_last(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = self._prepare(root)
            run_dir = root / "run"
            self.assertEqual(self._run_executor(package, run_dir), 0)
            run = json.loads((run_dir / "run-manifest.json").read_text())
            self.assertEqual(run["api_calls"], 0)
            self.assertEqual(run["mode"], "fake_no_provider")
            self.assertEqual(run["status"], "fake_response_validated")
            for name, digest in run["artifact_files_sha256"].items():
                import hashlib
                self.assertEqual(hashlib.sha256((run_dir / name).read_bytes()).hexdigest(), digest)
            report = (run_dir / "pending-report.zh-CN.md").read_text()
            self.assertIn("待人工审阅", report)

    def test_interrupted_package_directory_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = self._prepare(root)
            interrupted = root / "interrupted"
            interrupted.mkdir()
            (interrupted / "catalog.json").write_text(
                (package / "catalog.json").read_text(), encoding="utf-8")
            with self.assertRaises(SystemExit):
                self._run_executor(interrupted, root / "run")

    def test_non_ready_status_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = self._prepare(root)
            blocked = root / "blocked"
            blocked.mkdir()
            for item in package.iterdir():
                (blocked / item.name).write_text(item.read_text(), encoding="utf-8")
            manifest = json.loads((blocked / "manifest.json").read_text())
            manifest["status"] = "blocked_budget"
            (blocked / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(SystemExit):
                self._run_executor(blocked, root / "run")


if __name__ == "__main__":
    unittest.main()
