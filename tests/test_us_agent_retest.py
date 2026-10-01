import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_us_agent_retest_reference import aggregate
from scripts.run_us_agent_retest import GateError, RequestLedger, GuardedOpener, RecordingModel
import io
import json
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.trade_agent_deepseek import DeepSeekThinkingToolModel
from tradeintel_ai.trade_agent_metrics import request_configuration
from scripts.score_us_agent_retest import check_report, count_results
from scripts.score_us_agent_retest import audit_query_actions
from scripts.run_us_agent_retest import snapshot_files, verify_snapshot
from scripts.score_us_agent_retest import check_saved_report
from tradeintel_ai.trade_report_store import create_record
from scripts.run_us_agent_retest import execute_cases
from scripts.score_us_agent_retest import check_policy_bundles
from tradeintel_ai.trade_agent_policy_evidence import evidence_bundles
from scripts.run_us_agent_retest import AgentCaseExecutor
from scripts.run_us_agent_retest import write_new, build_review_materials
import uuid


class AgentExecutorTests(unittest.TestCase):
    def test_real_agent_two_turn_readback_offline(self):
        from tests.test_trade_agent_mainline import ScriptedModel, DATA_ROOT
        project = Path(__file__).resolve().parents[1]
        reference_path = project / "tmp/handoff-runs/us-agent-retest-20261001-v1/reference/trade.json"
        if not DATA_ROOT.exists() or not reference_path.exists():
            self.skipTest("Independent local data/reference not installed")
        plan = json.loads((project / "evals/us_agent_retest_v1/scenarios.json").read_text())
        reference = json.loads(reference_path.read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executor = AgentCaseExecutor(plan, reference, DATA_ROOT, root / "runtime", root / "output", lambda _: ScriptedModel())
            first_id = uuid.uuid4().hex
            for case, request_id in zip(plan["cases"][:2], (first_id, uuid.uuid4().hex)):
                result = executor({"case_id": case["id"], "question": case["question"],
                                   "request_id": request_id, "session_id": first_id})
                self.assertTrue(result["numeric_complete"])
                self.assertEqual(result["responses"], 3)
                self.assertEqual(result["product_result"], "pending_audit")


class BatchPolicyTests(unittest.TestCase):
    def batch(self):
        ids = ["R01", "R02", "T01", "T02", "T04"]
        cases = [{"id": name, "question": name, "kind": "normal", **({"requires": "R01"} if name == "R02"
                  else {"requires": "T01"} if name == "T02" else {})} for name in ids]
        turns = [{"case_id": case["id"], "question": case["question"], "requires": case.get("requires")} for case in cases]
        return {"cases": cases}, turns

    def test_failed_first_gate_stops_no_extra_execution(self):
        plan, turns = self.batch()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            def run(turn):
                calls.append(turn)
                self.assertNotIn("expected_product", turn)
                return {"case_id": turn["case_id"], "product_result": "incomplete", "responses": 1}
            result = execute_cases(plan, turns, Path(directory) / "batch", run)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result[-1]["status"], "not_run_batch_stop")
            with self.assertRaises(GateError):
                execute_cases(plan, turns, Path(directory) / "batch", run)

    def test_failure_skips_dependent_not_independent(self):
        plan, turns = self.batch()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            def run(turn):
                calls.append(turn["case_id"])
                return {"case_id": turn["case_id"], "product_result": "incomplete" if turn["case_id"] == "T01" else "complete",
                        "continuation_ready": turn["case_id"] != "T01",
                        "request_accounting_complete": True, "accounting_complete": True, "responses": 1}
            result = execute_cases(plan, turns, Path(directory) / "batch", run)
            self.assertEqual(calls, ["R01", "R02", "T01", "T04"])
            self.assertEqual(result[3]["status"], "not_run_prerequisite")

    def test_policy_original_dependencies_and_tamper(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_policy(project, root)
            store = load_announcement_store(root, POLICY_ID)
            # Explicit in-memory test fixture only; never saved or human-confirmed.
            store["documents"][0]["status"] = "enabled"
            result = PolicySearch(store, policy_id=POLICY_ID).search("8101.94.00")
            bundles = evidence_bundles(store, result)
            self.assertTrue(check_policy_bundles(bundles, store)["passed"])
            bundles[0]["required_context"] = []
            self.assertFalse(check_policy_bundles(bundles, store)["passed"])


class SnapshotReadbackTests(unittest.TestCase):
    def test_new_file_atomic_no_overwrite_or_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_new(path, {"original": True})
            with self.assertRaises(FileExistsError):
                write_new(path, {"original": False})
            self.assertEqual(json.loads(path.read_text()), {"original": True})
            with self.assertRaises(ValueError):
                write_new(Path(directory) / "invalid.json", {"value": float("nan")})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_review_template_has_no_success_or_model_score(self):
        material = build_review_materials({"cases": [{"id": "R06", "question": "fixture"}]})
        self.assertFalse(material["model_context_allowed"])
        self.assertEqual(material["cases"][0]["decision"], "pending")
        self.assertIsNone(material["cases"][0]["model_raw_correct"])
    def test_snapshot_changes_and_empty_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_text("original")
            snapshot_files([source], root / "snapshot.json")
            self.assertFalse(verify_snapshot(root / "snapshot.json")["live_ready"])
            source.write_text("changed")
            with self.assertRaises(GateError):
                verify_snapshot(root / "snapshot.json")
            with self.assertRaises(GateError):
                snapshot_files([], root / "empty.json")

    def test_saved_report_readback_and_tamper(self):
        case, report, gold = ScoringTests().fixture()
        report.update(kind="trade-query-v1", question="fixture", sources=[], notes=[], ai_status="not_run")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = create_record(root, report)
            self.assertTrue(check_saved_report(root, saved["report_id"], case, gold)["passed"])
            path = root / ".local/trade-reports" / (saved["report_id"] + ".json")
            record = json.loads(path.read_text())
            record["report"]["series"][0]["value_usd"] = 999
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                check_saved_report(root, saved["report_id"], case, gold)


class ScoringTests(unittest.TestCase):
    def test_blocked_wrong_attempt_not_hidden_by_correct_final_query(self):
        case, _, _ = self.fixture()
        feedback = [{"tools": [{"name": "search_products", "content": json.dumps({"candidates": [
            {"id": "import:1507", "code": "1507"}, {"id": "import:1201", "code": "1201"}]})}]}]
        responses = [{"tool_calls": [{"name": "query_trade", "arguments": {
            "candidate_id": candidate, "flow": "import", "partner": "all", "period": {"type": "latest_contiguous"}}}]
            } for candidate in ("import:1507", "import:1201")]
        result = audit_query_actions(case, responses, feedback)
        self.assertEqual(result["query_attempts"], 2)
        self.assertFalse(result["query_actions_correct"])
        self.assertIn("wrong_product_attempt", result["errors"])

    def fixture(self):
        case = {"expected_product": "1201", "flow": "import", "partner": "all",
                "period_rule": "recent_with_previous_month"}
        reference = {"months": {month: {"import": {"values": {"1201": {"all": {"value_usd": value}}}}}
                                 for month, value in (("2026-06", 10), ("2026-07", 15))}}
        report = {"scope": {"reporter": "US", "product_code": "1201", "flow": "import", "partner": "ALL_ORIGINS",
                            "start_month": "2026-06", "end_month": "2026-07"},
            "series": [{"month": "2026-06", "value_usd": 10, "status": "observed"},
                       {"month": "2026-07", "value_usd": 15, "status": "observed"}],
            "summary": {"latest_month": "2026-07", "latest_value_usd": 15, "previous_month": "2026-06",
                        "month_change_usd": 5, "period_total_usd": 25, "complete_window": True}}
        return case, report, reference

    def test_good_report_and_wrong_scope(self):
        case, report, gold = self.fixture()
        self.assertTrue(check_report(case, report, gold)["passed"])
        for key, wrong in (("reporter", "CN"), ("product_code", "1507"), ("flow", "export"), ("partner", "CHINA")):
            changed = json.loads(json.dumps(report))
            changed["scope"][key] = wrong
            self.assertFalse(check_report(case, changed, gold)["passed"])

    def test_value_summary_and_month_rejected(self):
        case, report, gold = self.fixture()
        report["summary"]["month_change_usd"] = 6
        self.assertFalse(check_report(case, report, gold)["passed"])
        report["series"][0]["month"] = "2026-07"
        self.assertFalse(check_report(case, report, gold)["passed"])

    def test_unknown_is_not_zero(self):
        case, report, gold = self.fixture()
        gold["months"]["2026-07"]["import"]["values"]["1201"]["all"]["value_usd"] = None
        self.assertFalse(check_report(case, report, gold)["passed"])

    def test_denominator_includes_responded_failure_not_program_precheck(self):
        result = count_results([
            {"case_id": "R01", "executed": True, "origin": "api", "responses": 1, "raw_decision_correct": False},
            {"case_id": "R06", "executed": True, "responses": 0, "origin": "program_precheck"},
            {"case_id": "R02", "executed": False, "responses": 0}])
        self.assertEqual(result["model_denominator"], 1)
        self.assertEqual(result["model_raw_correct"], 0)
        self.assertEqual(result["batch_status"], "partial")


class WireRecordingTests(unittest.TestCase):
    def test_actual_adapter_replay_body_and_private_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bodies = []
            def transport(request, *, timeout):
                bodies.append(json.loads(request.data))
                return io.BytesIO(json.dumps({"model": "fixture-model", "choices": [{
                    "finish_reason": "tool_calls", "message": {"content": None,
                    "reasoning_content": "private-reasoning-sentinel",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {
                        "name": "coverage", "arguments": "{}"}}]}}]}).encode())
            opener = GuardedOpener(RequestLedger(root / "ledger", clock=lambda: 1), transport,
                                    authorized=True, started_at=0)
            config = OpenAICompatibleConfig("https://api.deepseek.com", "deepseek-flash", api_key="fixture-secret")
            params = {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "max_tokens": 8192}
            inner = DeepSeekThinkingToolModel(config, opener=opener, request_params=params)
            model = RecordingModel(inner, root / "recording")
            first = model.complete(messages=[{"role": "user", "content": "fixture"}], tools=[])
            self.assertIsNotNone(first.reasoning_content)
            self.assertEqual(request_configuration(model)["reasoning_effort"], "high")
            model.complete(messages=[{"role": "assistant", "tool_calls": [{"call_id": "c1", "name": "coverage", "arguments": {}}],
                                     "reasoning_content": first.reasoning_content}], tools=[])
            self.assertEqual(bodies[1]["messages"][-1]["reasoning_content"], "private-reasoning-sentinel")
            disk = "".join(path.read_text() for path in root.rglob("*.json"))
            self.assertNotIn("private-reasoning-sentinel", disk)
            self.assertNotIn("fixture-secret", disk)
            self.assertEqual(len(bodies), 2)
            with self.assertRaises(GateError):
                model.complete(messages=[{"role": "user", "content": "x" * 65537}], tools=[])
            self.assertEqual(len(bodies), 2)

    def test_timeout_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            from urllib.request import Request
            sent = []
            opener = GuardedOpener(RequestLedger(directory), lambda *a, **k: sent.append(1))
            with self.assertRaises(GateError):
                opener(Request("https://example.invalid", data=b"{}"), timeout=91)
            self.assertEqual(sent, [])
from scripts.prepare_us_retest_policy import POLICY_ID, prepare_policy, review_candidate
from tradeintel_ai.announcement_flow import load_announcement_store
from tradeintel_ai.policy_search import PolicySearch


class PolicyPreparationTests(unittest.TestCase):
    def test_archived_policy_stays_disabled(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = prepare_policy(project, root)
            self.assertEqual(result["verified_chunks"], 3)
            store = load_announcement_store(root, POLICY_ID)
            candidate = review_candidate(store)
            self.assertEqual(len(candidate["fields"]), 13)
            self.assertEqual(sum(field["status"] == "known" for field in candidate["fields"]), 9)
            self.assertFalse(candidate["missing_required_fields"])
            self.assertEqual(store["documents"][0]["status"], "disabled")
            self.assertFalse(store.get("announcement_candidates"))
            self.assertEqual(PolicySearch(store, policy_id=POLICY_ID).search("8101.94.00")["status"], "no_evidence")
            with self.assertRaises(GateError):
                prepare_policy(project, root)

    def test_modified_source_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            path = project / "data/raw/policy/review2025/cbp-63577329.html"
            path.parent.mkdir(parents=True)
            path.write_text("changed source")
            runtime = Path(directory) / "runtime"
            with self.assertRaises(GateError):
                prepare_policy(project, runtime)
            self.assertFalse(runtime.exists())


class LedgerTests(unittest.TestCase):
    def test_money_reserves_unknown_not_zero_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = RequestLedger(directory)
            with self.assertRaises(GateError):
                ledger.reserve_money("1")
            ledger.reserve_money("1.25", authorized=True)
            with self.assertRaises(GateError):
                RequestLedger(directory).reserve_money("0.76", authorized=True)
            ledger.reserve_money("0.75", authorized=True)
            for value in (None, "NaN", "Infinity", "-1", "0"):
                with self.assertRaises(GateError):
                    ledger.reserve_money(value, authorized=True)

    def test_unauthorized_does_not_reserve(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = RequestLedger(directory)
            with self.assertRaises(GateError):
                ledger.reserve_wire(b"{}", started_at=0)
            self.assertEqual(list(Path(directory).glob("wire-*.json")), [])

    def test_all_bodies_have_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = RequestLedger(directory, clock=lambda: 1)
            ledger.reserve_wire(b"{}", authorized=True, started_at=0)
            with self.assertRaises(GateError):
                ledger.reserve_wire(b"x" * 65537, authorized=True, started_at=0)

    def test_unknown_reservations_count(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = RequestLedger(directory, clock=lambda: 1)
            for _ in range(48):
                ledger.reserve_wire(b"{}", authorized=True, started_at=0)
            with self.assertRaises(GateError):
                RequestLedger(directory, clock=lambda: 1).reserve_wire(b"{}", authorized=True, started_at=0)

    def test_claim_cannot_repeat_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            RequestLedger(directory).claim("R01")
            with self.assertRaises(GateError):
                RequestLedger(directory).claim("R01")

    def test_time_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(GateError):
                RequestLedger(directory, clock=lambda: 7200).reserve_wire(b"{}", authorized=True, started_at=0)


class ReferenceTests(unittest.TestCase):
    def run_rows(self, flow, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            return aggregate(path, flow)

    def test_import_unknown_not_zero_and_partner_separation(self):
        values = self.run_rows("import", [{"hts10": "1801000000", "all_origin_observed": "1",
            "all_origin_import_value_consumption_usd": "42", "china_observed": "0",
            "china_import_value_consumption_usd": "0"}])["1801"]
        self.assertEqual(values["all"]["value_usd"], 42)
        self.assertIsNone(values["china"]["value_usd"])
        self.assertEqual(values["china"]["unobserved_rows"], 1)

    def test_export_observed_zero_and_missing_partner(self):
        values = self.run_rows("export", [{"scheduleb10": "4001000000", "partner_code": "5700",
            "domestic_observed": "1", "foreign_observed": "0", "total_export_fas_usd": "0"}])
        self.assertEqual(values["4001"]["china"]["value_usd"], 0)
        self.assertIsNone(values["1201"]["china"]["value_usd"])

    def test_export_partners_not_substituted(self):
        values = self.run_rows("export", [{"scheduleb10": "2204000000", "partner_code": "1220",
            "domestic_observed": "1", "foreign_observed": "1", "total_export_fas_usd": "17"}])["2204"]
        self.assertEqual(values["all"]["value_usd"], 17)
        self.assertIsNone(values["china"]["value_usd"])

    def test_invalid_flag_rejected(self):
        with self.assertRaises(ValueError):
            self.run_rows("export", [{"scheduleb10": "4001000000", "partner_code": "5700",
                "domestic_observed": "yes", "foreign_observed": "0", "total_export_fas_usd": "0"}])
