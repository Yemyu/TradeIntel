"""S2: server-created trade coverage and new-announcement A3 integration."""
from pathlib import Path
from copy import deepcopy
import shutil
import tempfile
import unittest

from src.tradeintel_ai.announcement_flow import (
    REQUIRED_FIELDS, check_trade_coverage, confirm_and_enable,
    load_announcement_store, resolve_policy_binding, submit_candidates,
    save_announcement_store,
)
from src.tradeintel_ai.announcement_report import (build_announcement_session_brief,
                                                   build_announcement_policy_facts)
from src.tradeintel_ai.session_store import create_session, load_session
from src.tradeintel_ai.web_app import _handle_announcement_import, _handle_session_post


NOTICE = "\n".join([
    "Synthetic Trade Notice",
    "Effective January 1, 2025",
    "Products of China",
    "HTS 28046100",
    "additional 50 percent rate",
])


class _Repository:
    class _Paths:
        root = Path(__file__).resolve().parents[1]
    paths = _Paths()


class S2TradeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="s2-coverage-")
        self.root = Path(self.tmp.name)
        # Copy only the small, already-published source artifacts.  The test
        # never writes to the project's data directory.
        (self.root / "data/processed").mkdir(parents=True)
        project = Path(__file__).resolve().parents[1]
        shutil.copytree(project / "data/processed/policy", self.root / "data/processed/policy")
        shutil.copytree(project / "data/processed/policy_exposure",
                        self.root / "data/processed/policy_exposure")
        imported = _handle_announcement_import(self.root, {
            "policy_id": "policy-s2", "source_id": "notice:s2:p1",
            "url": "https://official.example/s2", "text": NOTICE,
        })
        self.doc_version = imported["doc_version"]
        self.fields = self._fields()
        submitted = submit_candidates(self.root, "policy-s2", self.doc_version, self.fields)
        enabled = confirm_and_enable(
            self.root, "policy-s2", self.doc_version, self.fields,
            confirmed_by="s2-test", expected_candidate_digest=submitted["candidate_digest"])
        self.candidate_digest = enabled["candidate_digest"]

    def tearDown(self):
        self.tmp.cleanup()

    def _fields(self, code="28046100", precision="whole_hts8", origin="China",
                *, policy_id="policy-s2", doc_version=None):
        store = load_announcement_store(self.root, policy_id)
        doc_version = doc_version or self.doc_version
        sections = store["documents"][0]["sections"]

        def evidence(needle):
            section = next(item for item in sections if needle in item["text"])
            return [{"doc_version": doc_version, "section_id": section["id"],
                     "quote": needle}]

        values = {
            "title": ("known", "Synthetic Trade Notice", evidence("Synthetic Trade Notice")),
            "publication_date": ("unknown", None, []),
            "effective_date": ("known", "2025-01-01", evidence("Effective January 1, 2025")),
            "clock_24h": ("unknown", None, []),
            "timezone": ("unknown", None, []),
            "entry_events": ("unknown", None, []),
            "origin": ("known", origin, evidence("Products of China")),
            "hts_codes": ("known", [{"code": code, "precision": precision}], evidence("HTS 28046100")),
            "rates": ("known", {code: 50}, evidence("additional 50 percent rate")),
            "rate_meaning": ("known", "additional duty", evidence("additional 50 percent rate")),
            "conditions": ("unknown", None, []),
            "exceptions": ("unknown", None, []),
            "revisions": ("unknown", None, []),
        }
        result = []
        for name in REQUIRED_FIELDS:
            status, value, refs = values[name]
            item = {"field": name, "status": status, "value": value, "evidence": refs}
            if status == "unknown":
                item["reason"] = "合成验收材料未提供该字段"
            result.append(item)
        return result

    def test_exact_coverage_is_server_created_and_reportable(self):
        checked = check_trade_coverage(self.root, "policy-s2", self.doc_version,
                                       month="2025-01")
        self.assertEqual(checked["coverage"]["trade_coverage"], "exact")
        self.assertEqual(checked["trade_coverage"]["covered_codes"], ["28046100"])
        binding = resolve_policy_binding(self.root, "policy-s2", self.doc_version,
                                         self.candidate_digest, month="2025-01")
        self.assertEqual(binding["coverage_status"], "exact")
        self.assertRegex(binding["data_version"], r"^[0-9a-f]{64}$")
        store = load_announcement_store(self.root, "policy-s2")
        candidate = store["announcement_candidates"][self.doc_version]["candidate"]
        coverage = store["trade_coverage"][self.doc_version]
        brief = build_announcement_session_brief(
            self.root,
            {"policy_id": "policy-s2", "month": "2025-01", "product": "all",
             "focus": "contrast"},
            binding, store=store, candidate=candidate, coverage=coverage)
        self.assertEqual(brief["kind"], "program-report-a3")
        self.assertIn("policy-s2", brief["a3_markdown"])
        self.assertEqual(brief["evidence_rows"][0]["hts8"], "28046100")

    def test_scope_clause_uses_product_evidence_not_effective_date(self):
        store = load_announcement_store(self.root, "policy-s2")
        candidate = store["announcement_candidates"][self.doc_version]["candidate"]
        facts = build_announcement_policy_facts(store, self.doc_version, candidate,
                                               "test-version", ["28046100"])
        clause = facts["product_rates"][0]["details"]["original_scope_clause"]
        self.assertIn("HTS 28046100", clause)
        self.assertNotIn("Effective January", clause)

    def test_partial_report_language_separates_policy_scope_from_trade_selection(self):
        store = load_announcement_store(self.root, "policy-s2")
        candidate = store["announcement_candidates"][self.doc_version]["candidate"]
        # The candidate has one registered code here; directly exercise the
        # wording helper's input shape with a second registered code.
        fields = self._fields(code="38180000")
        merged = {item["field"]: item for item in self.fields}
        merged["hts_codes"]["value"] = [
            {"code": "28046100", "precision": "whole_hts8"},
            {"code": "38180000", "precision": "whole_hts8"},
        ]
        # Rebuild through the normal candidate projection so this is not a
        # string-only test; the source evidence remains the original notice.
        from src.tradeintel_ai.announcement_report import build_announcement_policy_facts
        projected = build_announcement_policy_facts(
            store, self.doc_version, {**candidate, "fields": list(merged.values())},
            "data-version", ["28046100"])
        limitation = next(item for item in projected["limitations"] if "政策范围包含" in item)
        self.assertIn("贸易统计只核对其中 1 个", limitation)
        self.assertIn("没有纳入本次统计", limitation)

    def test_missing_code_is_not_substituted_by_main_case_products(self):
        # Replace the enabled candidate with a fresh disabled notice so the
        # server must query the requested code, rather than using 28046100.
        imported = _handle_announcement_import(self.root, {
            "policy_id": "policy-s2-missing", "source_id": "notice:s2:missing",
            "url": "https://official.example/missing", "text": NOTICE,
        })
        dv = imported["doc_version"]
        fields = self._fields(code="99999999", policy_id="policy-s2-missing", doc_version=dv)
        # The synthetic text does not contain 99999999, so use a new exact
        # quote in the candidate document by keeping the invalid code unknown;
        # this should remain non-reportable regardless of source data.
        fields = self._fields(code="28046100", policy_id="policy-s2-missing", doc_version=dv)
        fields[7]["value"] = [{"code": "99999999", "precision": "whole_hts8"}]
        submitted = submit_candidates(self.root, "policy-s2-missing", dv, fields)
        confirm_and_enable(self.root, "policy-s2-missing", dv, fields,
                           confirmed_by="s2-test", expected_candidate_digest=submitted["candidate_digest"])
        checked = check_trade_coverage(self.root, "policy-s2-missing", dv, month="2025-01")
        self.assertNotEqual(checked["coverage"]["trade_coverage"], "exact")
        self.assertIn("99999999", checked["trade_coverage"]["missing_codes"])

    def test_partial_precision_never_becomes_exact(self):
        imported = _handle_announcement_import(self.root, {
            "policy_id": "policy-s2-partial", "source_id": "notice:s2:partial",
            "url": "https://official.example/partial", "text": NOTICE,
        })
        dv = imported["doc_version"]
        fields = self._fields(code="28046100", precision="partial_ex",
                              policy_id="policy-s2-partial", doc_version=dv)
        submitted = submit_candidates(self.root, "policy-s2-partial", dv, fields)
        confirm_and_enable(self.root, "policy-s2-partial", dv, fields,
                           confirmed_by="s2-test", expected_candidate_digest=submitted["candidate_digest"])
        checked = check_trade_coverage(self.root, "policy-s2-partial", dv, month="2025-01")
        self.assertEqual(checked["coverage"]["code_precision"], "partial")
        self.assertEqual(checked["coverage"]["trade_coverage"], "partial")

    def test_session_evidence_and_generation_use_announcement_binding(self):
        check_trade_coverage(self.root, "policy-s2", self.doc_version, month="2025-01")
        binding = resolve_policy_binding(self.root, "policy-s2", self.doc_version,
                                         self.candidate_digest, month="2025-01")
        created = create_session(self.root)
        request = {"policy_id": "policy-s2", "month": "2025-01", "product": "all",
                   "focus": "contrast"}
        started = _handle_session_post(
            self.root, "/api/session/task/start",
            {"session_id": created["session_id"], "model": "deterministic",
             "prompt_digest": "s2", "request": request}, _Repository())
        confirmed = _handle_session_post(
            self.root, "/api/session/request",
            {"session_id": created["session_id"], "request": request,
             "policy_binding": binding}, _Repository())
        self.assertEqual(confirmed["session"]["data_version"], binding["data_version"])
        evidence = _handle_session_post(
            self.root, "/api/session/task/evidence",
            {"session_id": created["session_id"], "task_id": started["task_id"]}, _Repository())
        self.assertEqual(evidence["status"], "evidence_ready")
        generated = _handle_session_post(
            self.root, "/api/session/task/generate",
            {"session_id": created["session_id"], "task_id": started["task_id"]}, _Repository())
        self.assertEqual(generated["status"], "needs_review")
        final = load_session(self.root, created["session_id"])
        task = next(item for item in final["tasks"].values() if item["task_id"] == started["task_id"])
        self.assertIn("policy-s2", task["response"]["a3_markdown"])

    def test_report_rejects_modified_coverage_and_candidate(self):
        check_trade_coverage(self.root, "policy-s2", self.doc_version, month="2025-01")
        binding = resolve_policy_binding(self.root, "policy-s2", self.doc_version,
                                         self.candidate_digest, month="2025-01")
        store = load_announcement_store(self.root, "policy-s2")
        candidate = store["announcement_candidates"][self.doc_version]["candidate"]
        coverage = store["trade_coverage"][self.doc_version]
        request = {"policy_id": "policy-s2", "month": "2025-01", "product": "all"}
        altered = deepcopy(coverage)
        altered["requested_codes"] = ["38180000"]
        with self.assertRaisesRegex(ValueError, "覆盖内容"):
            build_announcement_session_brief(self.root, request, binding, store=store,
                                             candidate=candidate, coverage=altered)
        altered_candidate = deepcopy(candidate)
        next(f for f in altered_candidate["fields"] if f["field"] == "rates")["value"] = {"28046100": 99}
        with self.assertRaisesRegex(ValueError, "candidate content changed"):
            build_announcement_session_brief(self.root, request, binding, store=store,
                                             candidate=altered_candidate, coverage=coverage)

    def test_rate_meaning_is_not_assumed_and_fractional_rates_survive(self):
        store = load_announcement_store(self.root, "policy-s2")
        candidate = deepcopy(store["announcement_candidates"][self.doc_version]["candidate"])
        fields = {field["field"]: field for field in candidate["fields"]}
        fields["rates"]["value"] = {"28046100": 7.5}
        fields["rate_meaning"]["value"] = "total tariff"
        sheet = build_announcement_policy_facts(store, self.doc_version, candidate, "test", ["28046100"])
        self.assertNotIn("additional_duty_percent", sheet["product_rates"][0])
        self.assertEqual(sheet["product_rates"][0]["reported_rate"]["value"], 7.5)
        fields["rate_meaning"]["value"] = "additional duty"
        sheet = build_announcement_policy_facts(store, self.doc_version, candidate, "test", ["28046100"])
        self.assertEqual(sheet["product_rates"][0]["additional_duty_percent"], 7.5)

    def test_generation_failure_is_persisted_after_coverage_tamper(self):
        check_trade_coverage(self.root, "policy-s2", self.doc_version, month="2025-01")
        binding = resolve_policy_binding(self.root, "policy-s2", self.doc_version,
                                         self.candidate_digest, month="2025-01")
        created = create_session(self.root)
        request = {"policy_id": "policy-s2", "month": "2025-01", "product": "all",
                   "focus": "contrast"}
        confirmed = _handle_session_post(
            self.root, "/api/session/request",
            {"session_id": created["session_id"], "request": request,
             "policy_binding": binding}, _Repository())
        started = _handle_session_post(
            self.root, "/api/session/task/start",
            {"session_id": created["session_id"], "model": "deterministic",
             "prompt_digest": "failure", "request": request}, _Repository())
        _handle_session_post(
            self.root, "/api/session/task/evidence",
            {"session_id": created["session_id"], "task_id": started["task_id"]}, _Repository())
        store = load_announcement_store(self.root, "policy-s2")
        history = store["trade_coverage_history"][self.doc_version]
        record = next(iter(history.values()))
        record["coverage_digest"] = "tampered"
        save_announcement_store(self.root, "policy-s2", store)
        with self.assertRaisesRegex(ValueError, "覆盖记录摘要不一致"):
            _handle_session_post(
                self.root, "/api/session/task/generate",
                {"session_id": created["session_id"], "task_id": started["task_id"]}, _Repository())
        failed = load_session(self.root, created["session_id"])
        task = next(item for item in failed["tasks"].values()
                    if item["task_id"] == started["task_id"])
        self.assertEqual(task["state"], "failed")


if __name__ == "__main__":
    unittest.main()
