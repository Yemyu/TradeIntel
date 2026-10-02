"""Finite retest acceptance: real adapter/tools with injected, offline HTTP."""
import csv
import io
import json
import tempfile
import unittest
import uuid
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request

from scripts.run_us_agent_retest import (GateError, RecordingModel, AgentCaseExecutor,
                                        execute_cases, snapshot_files, verify_snapshot)
from scripts.us_retest_transport import (SendLedger, AccountedOpener, ENDPOINT,
                                        NoRedirect, create_accounted_model)
from scripts.score_us_agent_retest import count_results, check_public_turn
from scripts.build_us_agent_retest_reference import aggregate
from tradeintel_ai.model_adapter import OpenAICompatibleConfig


def permit():
    return {"schema": "us-retest-finite-permit-v1", "approved": True, "approver_role": "user",
        "freeze_sha256": "a" * 64, "authorization_message_sha256": "b" * 64,
        "price_source_sha256": "c" * 64, "endpoint": ENDPOINT, "model": "deepseek-flash",
        "reasoning_effort": "high", "currency": "USD", "budget": "2",
        "input_price_per_million": "0.30", "output_price_per_million": "1.20",
        "max_requests": 48, "max_rounds": 6, "max_tools": 12, "max_tokens": 8192,
        "max_body_bytes": 65536, "timeout_seconds": 90, "wall_seconds": 7200,
        "user_turns": 12, "retry_allowed": False, "expires_at": 10000,
        "output_bound_route": "capacity_fallback", "temperature": 0}


def turn(case_id="R01"):
    value = uuid.uuid4().hex
    return {"case_id": case_id, "request_id": value, "session_id": value}


def request(**changes):
    body = {"model": "deepseek-flash", "thinking": {"type": "enabled"},
            "reasoning_effort": "high", "max_tokens": 8192, "temperature": 0,
            "messages": [{"role": "user", "content": "fixture"}]}
    body.update(changes)
    return Request(ENDPOINT, data=json.dumps(body).encode(), method="POST")


def response(usage=None, *, arguments="{}"):
    return io.BytesIO(json.dumps({"model": "offline-transport-fixture", "choices": [{"message": {
        "content": None, "reasoning_content": "private-sentinel", "tool_calls": [{"id": "c1", "type": "function",
        "function": {"name": "get_trade_coverage", "arguments": arguments}}]}}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300} if usage is None else usage}).encode())


class SendTests(unittest.TestCase):
    def ledger(self, root, turns, **changes):
        p = permit()
        p.update(changes)
        return SendLedger(root, p, lambda: "a" * 64, turns=turns, clock=lambda: 1, monotonic=lambda: 1)

    def test_atomic_concurrent_reservation_and_frozen_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            t = turn()
            ledger = self.ledger(directory, [t])
            with ledger.batch():
                def reserve(_):
                    try:
                        return ledger.reserve(request(), t)
                    except GateError:
                        return None
                with ThreadPoolExecutor(max_workers=4) as pool:
                    self.assertEqual(sum(value is not None for value in pool.map(reserve, range(4))), 1)
                record = ledger.records()[0]
                self.assertEqual(record["request_id"], t["request_id"])
                self.assertEqual(record["reserved_cost"], "0.786432")
                self.assertFalse(list(Path(directory).glob("money-*.json")))
            with self.assertRaises(GateError):
                with self.ledger(directory, [t]).batch():
                    pass

    def test_settlement_releases_planning_reserve_not_bill_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            t = turn()
            ledger = self.ledger(directory, [t])
            with ledger.batch():
                opener = AccountedOpener(ledger, t, transport=lambda *a, **k: response())
                for _ in range(6):
                    opener(request(), timeout=90)
                    opener.settle()
                self.assertEqual(len(ledger.records()), 6)
                self.assertTrue(opener.accounting_complete())
                with self.assertRaises(GateError):
                    opener(request(), timeout=90)
                settled = json.loads((Path(directory) / "send-001-settled.json").read_text())
                self.assertEqual(settled["estimated_cost"], "0.00018")
                self.assertEqual(settled["billing"], "not_verified")

    def test_bad_usage_retains_full_reserve_and_stops(self):
        for usage in ({}, {"prompt_tokens": True, "completion_tokens": 1},
                      {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 3},
                      {"prompt_tokens": 1048577, "completion_tokens": 1}):
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as directory:
                t = turn()
                ledger = self.ledger(directory, [t])
                with ledger.batch():
                    opener = AccountedOpener(ledger, t, transport=lambda *a, **k: response(usage))
                    opener(request(), timeout=90)
                    with self.assertRaises(GateError):
                        opener.settle()
                    self.assertEqual(ledger.records()[0]["reserved_cost"], "0.786432")
                    self.assertFalse(list(Path(directory).glob("*-settled.json")))
                    with self.assertRaises(GateError):
                        opener(request(), timeout=90)

    def test_malformed_tool_json_is_received_failure_not_erased(self):
        with tempfile.TemporaryDirectory() as directory:
            t = turn()
            ledger = self.ledger(Path(directory) / "ledger", [t])
            with ledger.batch():
                model = create_accounted_model(OpenAICompatibleConfig("https://api.deepseek.com", "deepseek-flash", api_key="fixture-key", temperature=0),
                    {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "max_tokens": 8192},
                    ledger, t, transport=lambda *a, **k: response(arguments="bad-json"))
                wrapper = RecordingModel(model, Path(directory) / "responses", accounting=model.retest_accounting)
                with self.assertRaises(Exception):
                    wrapper.complete(messages=[{"role": "user", "content": "fixture"}], tools=[])
                received = json.loads((ledger.root / "send-001-received.json").read_text())
                self.assertTrue(received["model_response"])
                self.assertFalse(list(ledger.root.glob("*-settled.json")))
                disk = "".join(p.read_text() for p in Path(directory).rglob("*.json"))
                self.assertNotIn("private-sentinel", disk)
                self.assertNotIn("fixture-key", disk)

    def test_gateway_html_is_not_model_response(self):
        with tempfile.TemporaryDirectory() as directory:
            t = turn()
            ledger = self.ledger(directory, [t])
            with ledger.batch():
                opener = AccountedOpener(ledger, t, transport=lambda *a, **k: io.BytesIO(b"<html>gateway</html>"))
                opener(request(), timeout=90)
                self.assertFalse(opener.received["model_response"])
                with self.assertRaises(GateError):
                    opener.settle()

    def test_configuration_body_timeout_identity_and_redirect_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            t = turn()
            ledger = self.ledger(directory, [t])
            with ledger.batch():
                sent = []
                opener = AccountedOpener(ledger, t, transport=lambda *a, **k: sent.append(1))
                for bad, timeout in ((request(model="wrong"), 90), (request(), 91),
                                     (request(messages=[{"role": "user", "content": "x" * 65536}]), 90),
                                     (Request("https://elsewhere.invalid", data=b"{}"), 90)):
                    with self.assertRaises(GateError):
                        opener(bad, timeout=timeout)
                with self.assertRaises(GateError):
                    ledger.reserve(request(), turn())
                self.assertFalse(sent)
                self.assertFalse(ledger.records())
        with self.assertRaises(GateError):
            NoRedirect().redirect_request(None, None, 302, "redirect", {}, ENDPOINT)

    def test_unapproved_or_unverified_contract_rejected(self):
        for changes in ({"approved": False}, {"currency": "CNY"}, {"expires_at": 0},
                        {"output_bound_route": "confirmed_total_max_tokens"}, {"max_requests": True}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(GateError):
                    self.ledger(directory, [turn()], **changes)

    def test_cny_permission_reservation_and_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            t = turn()
            ledger = self.ledger(directory, [t], currency="CNY", budget="10",
                                  input_price_per_million="2", output_price_per_million="8")
            with ledger.batch():
                opener = AccountedOpener(ledger, t, transport=lambda *a, **k: response())
                opener(request(), timeout=90)
                self.assertEqual(ledger.records()[0]["reserved_cost"], "5.24288")
                opener.settle()
                settled = json.loads((ledger.root / "send-001-settled.json").read_text())
                self.assertEqual(settled["currency"], "CNY")
                self.assertEqual(settled["estimated_cost"], "0.0012")

    def test_total_limit_and_time_backwards_timeout_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            turns = [turn("T" + str(i)) for i in range(9)]
            now = [1]
            ledger = SendLedger(directory, permit(), lambda: "a" * 64, turns=turns,
                                clock=lambda: now[0], monotonic=lambda: now[0])
            with ledger.batch():
                for i in range(48):
                    opener = AccountedOpener(ledger, turns[i // 6], transport=lambda *a, **k: response())
                    opener(request(), timeout=90)
                    opener.settle()
                with self.assertRaises(GateError):
                    AccountedOpener(ledger, turns[8], transport=lambda *a, **k: response())(request(), timeout=90)
                self.assertEqual(len(ledger.records()), 48)
                now[0] = 0
                with self.assertRaises(GateError):
                    ledger.check_time()
                self.assertTrue((ledger.root / "STOP.json").exists())
        with tempfile.TemporaryDirectory() as directory:
            t = turn()
            ledger = self.ledger(directory, [t])
            def timeout(*a, **k):
                raise TimeoutError("offline timeout")
            with ledger.batch():
                opener = AccountedOpener(ledger, t, transport=timeout)
                with self.assertRaises(TimeoutError):
                    opener(request(), timeout=90)
                self.assertFalse(opener.accounting_complete())
                self.assertEqual(len(ledger.records()), 1)


class FinalFlowTests(unittest.TestCase):
    def test_unconfirmed_freeze_or_unapproved_run_never_loads_key(self):
        from unittest.mock import patch
        from scripts.run_us_agent_retest import run_authorized, write_new
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_new(root / "runtime/turns.json", [turn()])
            write_new(root / "permit.json", {**permit(), "approved": False})
            snapshot_files([root / "runtime/turns.json"], root / "FROZEN_MANIFEST.json")
            with patch("tradeintel_ai.local_provider_config.load_product_config") as loader:
                with self.assertRaises(GateError):
                    run_authorized(root, root, root / "permit.json")
                loader.assert_not_called()

    def test_membership_change_detected_without_old_hash_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "policies"
            source.mkdir()
            file = source / "old.json"
            file.write_text("{}")
            snapshot = root / "snapshot.json"
            snapshot_files([file], snapshot, inventories=[(source, "*.json")])
            verify_snapshot(snapshot)
            (source / "added.json").write_text("{}")
            with self.assertRaises(GateError):
                verify_snapshot(snapshot)

    def test_pending_final_score_does_not_block_verified_continuation(self):
        plan = {"cases": [{"id": "R01", "question": "one", "kind": "normal"},
                          {"id": "R02", "question": "two", "kind": "normal", "requires": "R01"}]}
        turns = [{**turn(c["id"]), "question": c["question"], "requires": c.get("requires")} for c in plan["cases"]]
        with tempfile.TemporaryDirectory() as directory:
            rows = execute_cases(plan, turns, Path(directory) / "batch", lambda t: {
                "case_id": t["case_id"], "continuation_ready": True, "request_accounting_complete": True,
                "product_result": "pending_audit", "origin": "offline_fixture", "responses": 1})
            self.assertEqual(sum(r["executed"] for r in rows), 2)
            self.assertEqual(count_results(rows)["model_denominator"], 0)
            self.assertEqual(count_results(rows)["normal_complete"], 0)
            claims = json.loads((Path(directory) / "batch/claims/R01.json").read_text())
            self.assertEqual(claims["request_id"], turns[0]["request_id"])

    def test_free_text_pauses_no_next_send_or_automatic_safe_score(self):
        plan = {"cases": [{"id": "P01", "question": "one", "kind": "normal"},
                          {"id": "P02", "question": "two", "kind": "boundary"}]}
        turns = [{**turn(c["id"]), "question": c["question"], "requires": None} for c in plan["cases"]]
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def execute(t):
                calls.append(t)
                return {"case_id": t["case_id"], "public_safety": "review_required", "product_result": "pending_audit"}
            result = execute_cases(plan, turns, Path(directory) / "batch", execute)
            self.assertEqual(len(calls), 1)
            self.assertFalse(result[-1]["executed"])

    def test_row_dates_sources_and_export_reconcile(self):
        good = {"year": "2026", "month": "7", "source_sha256": "a" * 64, "scheduleb10": "1201000000",
                "partner_code": "5700", "domestic_observed": "1", "foreign_observed": "1",
                "domestic_export_fas_usd": "2", "foreign_reexport_fas_usd": "3", "total_export_fas_usd": "5"}
        expected = {"year": 2026, "month": 7, "source_sha256": "a" * 64}
        for changes in ({}, {"month": "6"}, {"source_sha256": "b" * 64}, {"total_export_fas_usd": "6"}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "rows.csv"
                with path.open("w") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(good))
                    writer.writeheader()
                    writer.writerow({**good, **changes})
                if changes:
                    with self.assertRaises(ValueError):
                        aggregate(path, "export", expected=expected)
                else:
                    self.assertEqual(aggregate(path, "export", expected=expected)["1201"]["china"]["value_usd"], 5)

    def test_real_factory_http_two_turns_final_tools_and_all_reports(self):
        from tests.test_trade_agent_mainline import ScriptedModel, DATA_ROOT
        project = Path(__file__).resolve().parents[1]
        reference_path = project / "tmp/handoff-runs/us-agent-retest-20261001-v1/reference/trade.json"
        if not reference_path.is_file() or not DATA_ROOT.is_dir():
            self.skipTest("local independent data not installed")
        plan = json.loads((project / "evals/us_agent_retest_v1/scenarios.json").read_text())
        plan["cases"] = plan["cases"][:2]
        sid = uuid.uuid4().hex
        turns = [{"case_id": c["id"], "request_id": sid if i == 0 else uuid.uuid4().hex,
                  "session_id": sid, "question": c["question"], "requires": c.get("requires")}
                 for i, c in enumerate(plan["cases"])]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = SendLedger(root / "ledger", permit(), lambda: "a" * 64, turns=turns,
                                clock=lambda: 1, monotonic=lambda: 1)
            params = {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "max_tokens": 8192}
            def factory(case_id):
                scripted = ScriptedModel()
                def transport(req, *, timeout):
                    body = json.loads(req.data)
                    names = {call["id"]: call["function"]["name"] for message in body["messages"]
                             for call in message.get("tool_calls", [])}
                    for message in body["messages"]:
                        if message["role"] == "tool":
                            message["name"] = names[message["tool_call_id"]]
                    answer = scripted.complete(messages=body["messages"], tools=body.get("tools", []))
                    calls = [{"id": call.call_id, "type": "function", "function": {
                        "name": call.name, "arguments": json.dumps(call.arguments)}} for call in answer.tool_calls]
                    return io.BytesIO(json.dumps({"choices": [{"message": {"content": None,
                        "reasoning_content": "private-offline-thought", "tool_calls": calls}}],
                        "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}}).encode())
                return create_accounted_model(OpenAICompatibleConfig("https://api.deepseek.com", "deepseek-flash", api_key="fixture-secret", temperature=0),
                    params, ledger, next(t for t in turns if t["case_id"] == case_id), transport=transport)
            executor = AgentCaseExecutor(plan, json.loads(reference_path.read_text()), DATA_ROOT,
                                         root / "runtime", root / "evidence", factory)
            with ledger.batch():
                results = execute_cases(plan, turns, root / "batch", executor)
            self.assertTrue(all(r["continuation_ready"] for r in results), {
                "results": results, "failures": [json.loads(p.read_text()) for p in root.rglob("*-failed.json")],
                "stop": json.loads((ledger.root / "STOP.json").read_text()) if (ledger.root / "STOP.json").exists() else None})
            self.assertTrue(all(r["product_result"] == "pending_audit" for r in results))
            self.assertEqual(len(ledger.records()), 6)
            self.assertEqual(count_results(results)["model_denominator"], 0)
            for c in ("R01", "R02"):
                last = json.loads((root / "evidence" / c / "responses/tool-003.json").read_text())
                self.assertEqual(last["tools"][0]["name"], "finish")
            disk = "".join(p.read_text() for p in root.rglob("*.json"))
            self.assertNotIn("private-offline-thought", disk)
            self.assertNotIn("fixture-secret", disk)

    def test_all_extra_reports_and_primary_scope_are_independent(self):
        from tests.test_trade_agent_mainline import TwoDestinationModel, DATA_ROOT
        project = Path(__file__).resolve().parents[1]
        reference_path = project / "tmp/handoff-runs/us-agent-retest-20261001-v1/reference/trade.json"
        if not reference_path.is_file() or not DATA_ROOT.is_dir():
            self.skipTest("local independent data not installed")
        plan = json.loads((project / "evals/us_agent_retest_v1/scenarios.json").read_text())
        reference = json.loads(reference_path.read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executor = AgentCaseExecutor(plan, reference, DATA_ROOT, root / "runtime", root / "evidence", lambda _: TwoDestinationModel())
            t = turn("R02")
            result = executor({**t, "question": plan["cases"][1]["question"]})
            self.assertTrue(result["continuation_ready"], result)
            state = json.loads((root / "evidence/R02/session-readback.json").read_text())
            current = state["turns"][-1]
            self.assertEqual(len(current["report_ids"]), 2)
            tools = [json.loads(p.read_text())["tools"][0] for p in sorted((root / "evidence/R02/responses").glob("tool-*.json"))]
            # Correct main all-partners report cannot hide a false China amount.
            bad_gold = json.loads(json.dumps(reference))
            bad_gold["months"]["2026-07"]["export"]["values"]["1201"]["china"]["value_usd"] += 1
            checked = check_public_turn(root / "runtime", current, plan["cases"][1], bad_gold, tools)
            self.assertFalse(checked["passed"])
            self.assertEqual(checked["public_safety"], "unsafe")
            current["primary_report_id"] = current["report_ids"][1]
            checked = check_public_turn(root / "runtime", current, plan["cases"][1], reference, tools)
            self.assertIn("wrong_primary_scope", checked["errors"])

    def test_both_one_record_or_two_separate_records_cover_both_directions(self):
        from tradeintel_ai.trade_agent_tools import TradeAgentTools
        from tradeintel_ai.trade_report_store import create_record, get_state, load_record
        from tradeintel_ai.trade_agent import _program_summary
        from tradeintel_ai.trade_agent_report_view import build_reader_view
        from tests.test_trade_agent_mainline import DATA_ROOT
        project = Path(__file__).resolve().parents[1]
        ref_path = project / "tmp/handoff-runs/us-agent-retest-20261001-v1/reference/trade.json"
        if not DATA_ROOT.is_dir() or not ref_path.is_file():
            self.skipTest("local independent data not installed")
        case = json.loads((project / "evals/us_agent_retest_v1/scenarios.json").read_text())["cases"][3]
        reference = json.loads(ref_path.read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = TradeAgentTools(DATA_ROOT, root, question=case["question"])
            candidate = tools.search_products("大豆", "both")["candidates"][0]["id"]
            result = tools.query_trade(candidate, "both", "all", {"type": "latest_contiguous"})
            saved = load_record(root, result["report_id"])["report"]
            separate = [create_record(root, saved[flow + "_report"])["report_id"] for flow in ("import", "export")]
            for ids in ([result["report_id"]], separate, separate[:1]):
                reports = [get_state(root, rid) for rid in ids]
                current = {"status": "completed", "question": case["question"], "primary_report_id": ids[0],
                    "report_ids": ids, "policy_source_ids": [], "message_kind": "program_summary_v1",
                    "reader_view": build_reader_view(case["question"], reports), "message": _program_summary(reports, 0)}
                evidence = [{"name": "query_trade", "arguments": {}, "content": json.dumps({"report_id": rid})} for rid in ids]
                evidence.append({"name": "finish", "arguments": {"report_ids": ids, "source_ids": []}, "content": json.dumps({"status": "completed"})})
                checked = check_public_turn(root, current, case, reference, evidence)
                self.assertEqual(checked["passed"], len(ids) != 1 or ids[0] == result["report_id"], checked)


class ReferenceRevisionTests(unittest.TestCase):
    def test_new_complete_package_covers_registered_months_without_gold_in_turns(self):
        from scripts.run_us_agent_retest import prepare_final
        from tests.test_trade_agent_mainline import DATA_ROOT
        if not DATA_ROOT.is_dir():
            self.skipTest("local verified data not installed")
        project = Path(__file__).resolve().parents[1]
        scenarios = project / "evals/us_agent_retest_v1/scenarios.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fresh-complete"
            prepare_final(root, project, scenarios, DATA_ROOT)
            reference = json.loads((root / "reference/trade.json").read_text())
            self.assertEqual(reference["coverage_profile"], "manifest_available")
            for flow in ("import", "export"):
                self.assertEqual({m for m, data in reference["months"].items() if flow in data},
                                 set(reference["registered_months"][flow]))
            self.assertIsNone(reference["months"]["2026-07"]["import"]["values"]["1801"]["china"]["value_usd"])
            turns = json.loads((root / "runtime/turns.json").read_text())
            plan = json.loads(scenarios.read_text())
            self.assertEqual([t["question"] for t in turns], [c["question"] for c in plan["cases"]])
            self.assertEqual(len({t["session_id"] for t in turns}), 7)
            self.assertTrue(all(set(t) == {"case_id", "request_id", "session_id", "question", "requires"}
                                for t in turns))
            self.assertFalse((root / "runtime/trade.json").exists())
            self.assertFalse((root / "FROZEN_MANIFEST.json").exists())
            self.assertEqual(json.loads((root / "STATUS.json").read_text())["api_calls"], 0)

    def test_real_r01_old_reference_is_unverified_and_full_reference_verifies(self):
        project = Path(__file__).resolve().parents[1]
        old = project / "tmp/handoff-runs/us-agent-retest-20261001-v4"
        new = project / "tmp/handoff-runs/us-agent-retest-20261001-v5"
        if not new.is_dir():
            self.skipTest("local continuation reference not installed")
        state = json.loads((old / "results/evidence/R01/session-readback.json").read_text())
        case = json.loads((old / "inputs/plan.json").read_text())["cases"][0]
        tools = [t for path in sorted((old / "results/evidence/R01/responses").glob("tool-*.json")) for t in json.loads(path.read_text())["tools"]]
        gold = json.loads((old / "reference/trade.json").read_text())
        result = check_public_turn(old / "runtime", state["turns"][0], case, gold, tools)
        self.assertEqual(result["verification_status"], "unverified_reference")
        self.assertEqual(result["errors"], [])
        self.assertNotEqual(result["public_safety"], "unsafe")
        gold = json.loads((new / "reference/trade.json").read_text())
        self.assertTrue(check_public_turn(old / "runtime", state["turns"][0], case, gold, tools)["passed"])
        gold["months"]["2025-01"]["import"]["values"]["1201"]["all"]["value_usd"] += 1
        self.assertEqual(check_public_turn(old / "runtime", state["turns"][0], case, gold, tools)["public_safety"], "unsafe")

    def test_missing_reference_is_not_null_observation_or_unsafe_fact(self):
        from tests.test_us_agent_retest import ScoringTests
        from scripts.score_us_agent_retest import check_report
        case, report, gold = ScoringTests().fixture()
        del gold["months"]["2026-06"]
        result = check_report(case, report, gold)
        self.assertEqual(result["verification_status"], "unverified_reference")
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["passed"])
        report["series"][-1]["value_usd"] += 1
        result = check_report(case, report, gold)
        self.assertEqual(result["verification_status"], "failed")
        self.assertTrue(result["unverified"])

    def test_known_null_and_unregistered_month_remain_failures(self):
        from tests.test_us_agent_retest import ScoringTests
        from scripts.score_us_agent_retest import check_report
        case, report, gold = ScoringTests().fixture()
        gold["months"]["2026-07"]["import"]["values"]["1201"]["all"]["value_usd"] = None
        self.assertEqual(check_report(case, report, gold)["verification_status"], "failed")
        del gold["months"]["2026-06"]
        gold["registered_months"] = {"import": ["2026-07"]}
        self.assertIn("unregistered_report_month:2026-06", check_report(case, report, gold)["errors"])

    def test_missing_reference_cannot_hide_internally_false_total(self):
        from tests.test_us_agent_retest import ScoringTests
        from scripts.score_us_agent_retest import check_report
        case, report, gold = ScoringTests().fixture()
        del gold["months"]["2026-06"]
        report["summary"]["period_total_usd"] += 1
        self.assertIn("internal_summary:period_total_usd", check_report(case, report, gold)["errors"])

    def test_full_manifest_profile_and_old_core_values(self):
        from scripts.build_us_agent_retest_reference import build_reference
        from tests.test_trade_agent_mainline import DATA_ROOT
        if not DATA_ROOT.is_dir():
            self.skipTest("local verified data not installed")
        core = build_reference(DATA_ROOT)
        full = build_reference(DATA_ROOT, coverage_profile="manifest_available")
        self.assertEqual(sum("import" in v for v in full["months"].values()), 48)
        self.assertEqual(sum("export" in v for v in full["months"].values()), 12)
        self.assertNotIn("2024-12", full["months"])
        for month, values in core["months"].items():
            self.assertEqual(values, full["months"][month])
        self.assertIsNone(full["months"]["2026-07"]["import"]["values"]["1801"]["china"]["value_usd"])


class ContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Path(__file__).resolve().parents[1]
        from tests.test_trade_agent_mainline import DATA_ROOT
        from scripts.build_us_agent_retest_reference import build_reference
        if not DATA_ROOT.is_dir():
            raise unittest.SkipTest("local verified data not installed")
        cls.reference = build_reference(DATA_ROOT, coverage_profile="manifest_available")

    def clone(self, directory):
        """Build a fresh offline seed, never re-seal a historical live run.

        These synthetic fixture hashes bind only temporary files. The separate
        historical test below still requires old v5 to reject current sources.
        """
        from scripts.run_us_agent_retest import file_hash, write_new
        from tests.test_trade_agent_mainline import DATA_ROOT, ScriptedModel
        parent = Path(directory) / "fixture-parent"
        target = Path(directory) / "child"
        plan = json.loads((self.project / "evals/us_agent_retest_v1/scenarios.json").read_text())
        sessions, turns = {}, []
        for case in plan["cases"]:
            rid = uuid.uuid4().hex
            sessions.setdefault(case["session"], rid)
            turns.append({"case_id": case["id"], "request_id": rid,
                          "session_id": sessions[case["session"]],
                          "question": case["question"], "requires": case.get("requires")})
        executor = AgentCaseExecutor(plan, self.reference, DATA_ROOT, parent / "runtime",
                                     parent / "results/evidence", lambda _: ScriptedModel())
        seed = executor(turns[0])
        self.assertTrue(seed["continuation_ready"], seed)
        write_new(parent / "results/batch/R01.json", {**seed, "origin": "offline_fixture"})
        write_new(parent / "fixture-origin.json", {"origin": "offline_fixture", "api_calls": 0})
        write_new(parent / "FROZEN_MANIFEST.json", {"origin": "offline_fixture", "live_ready": False})
        write_new(target / "inputs/plan.json", plan)
        write_new(target / "reference/trade.json", self.reference)
        write_new(target / "runtime/turns.json", turns)
        bootstrap = []
        for source in (parent / "runtime").rglob("*.json"):
            relative = str(source.relative_to(parent / "runtime"))
            for destination in (target / "runtime" / relative, target / "bootstrap/runtime" / relative):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            bootstrap.append({"relative": relative, "sha256": file_hash(source)})
        diagnostic = target / "bootstrap/R01-posthoc.json"
        write_new(diagnostic, {"case_id": "R01", "origin": "offline_fixture", "api_calls": 0})
        write_new(target / "inputs/continuation.json", {
            "schema": "us-retest-continuation-v1", "parent": str(parent),
            "parent_freeze_sha256": file_hash(parent / "FROZEN_MANIFEST.json"),
            "parent_files": {str(p): file_hash(p) for p in parent.rglob("*.json")},
            "consumed_requests": 0, "consumed_cost": "0", "bootstrap": bootstrap,
            "allowlist": [c["id"] for c in plan["cases"][1:]],
            "anchor": {"case_id": "R01", "continuation_ready": True,
                       "diagnostic_sha256": file_hash(diagnostic)}})
        return target

    def test_historical_v5_rejects_changed_sources_without_resealing(self):
        from scripts.run_us_agent_retest import verify_continuation, file_hash
        package = self.project / "tmp/handoff-runs/us-agent-retest-20261001-v5"
        if not package.is_dir():
            self.skipTest("historical v5 not installed")
        before = file_hash(package / "FROZEN_MANIFEST.json")
        with self.assertRaisesRegex(GateError, "Ancestor evidence changed"):
            verify_continuation(package, initial=True)
        self.assertEqual(file_hash(package / "FROZEN_MANIFEST.json"), before)

    def test_bootstrap_ancestor_hash_allowlist_and_initial_seed(self):
        from scripts.run_us_agent_retest import verify_continuation
        with tempfile.TemporaryDirectory() as directory:
            root = self.clone(directory)
            value = verify_continuation(root, initial=True)
            self.assertEqual(len(value["allowlist"]), 11)
            path = root / "inputs/continuation.json"
            wrong = json.loads(path.read_text())
            wrong["allowlist"].insert(0, "R01")
            path.write_text(json.dumps(wrong))
            with self.assertRaises(GateError):
                verify_continuation(root)

            path.write_text(json.dumps(value))
            first = value["bootstrap"][0]["relative"]
            (root / "runtime" / first).write_text("{}")
            with self.assertRaises(GateError):
                verify_continuation(root, initial=True)
            shutil.copyfile(root / "bootstrap/runtime" / first, root / "runtime" / first)
            wrong = json.loads(path.read_text())
            wrong["parent_files"][next(iter(wrong["parent_files"]))] = "0" * 64
            path.write_text(json.dumps(wrong))
            with self.assertRaises(GateError):
                verify_continuation(root)

    def test_ancestor_pending_or_orphan_or_already_claimed_turn_rejected(self):
        from scripts.run_us_agent_retest import ancestor_facts
        original = self.project / "tmp/handoff-runs/us-agent-retest-20261001-v4"
        for change in ("pending", "orphan", "claimed"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory) / "parent"
                parent.mkdir()
                shutil.copyfile(original / "FROZEN_MANIFEST.json", parent / "FROZEN_MANIFEST.json")
                (parent / "runtime").mkdir()
                shutil.copyfile(original / "runtime/turns.json", parent / "runtime/turns.json")
                for relative in ("inputs", "results/batch", "results/evidence", "ledgers/live"):
                    for path in (original / relative).rglob("*.json"):
                        target = parent / path.relative_to(original)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, target)
                if change == "pending":
                    (parent / "ledgers/live/send-001-settled.json").unlink()
                elif change == "orphan":
                    (parent / "ledgers/live/send-006-received.json").write_text("{}")
                else:
                    (parent / "results/batch/claims/R02.json").write_text("{}")
                with self.assertRaises(GateError):
                    ancestor_facts(parent, self.project)

    def test_real_adapter_remaining_turns_use_seed_and_never_run_r01(self):
        from scripts.run_us_agent_retest import verify_continuation, score_package, file_hash
        from tests.test_trade_agent_mainline import DATA_ROOT
        with tempfile.TemporaryDirectory() as directory:
            root = self.clone(directory)
            continuation = verify_continuation(root, initial=True)
            parent_hash = file_hash(Path(continuation["parent"]) / "results/batch/R01.json")
            plan = json.loads((root / "inputs/plan.json").read_text())
            turns = json.loads((root / "runtime/turns.json").read_text())
            chosen = [t for t in turns if t["case_id"] in continuation["allowlist"]]
            ledger = SendLedger(root / "offline-ledger", permit(), lambda: "a" * 64,
                turns=chosen, clock=lambda: 1, monotonic=lambda: 1)
            factories, observed_context = [], []
            def factory(case_id):
                factories.append(case_id)
                def transport(req, *, timeout):
                    payload = json.loads(req.data)
                    messages = payload["messages"]
                    if messages[-1]["role"] == "user":
                        observed_context.append(messages[1]["content"])
                        name, args = "search_products", {"term": "豆油" if case_id == "R03" else "大豆", "flow": "import" if case_id == "R03" else "export"}
                    else:
                        names = {c["id"]: c["function"]["name"] for m in messages for c in m.get("tool_calls", [])}
                        tool_name = names[messages[-1]["tool_call_id"]]
                        content = json.loads(messages[-1]["content"])
                        if tool_name == "search_products":
                            name, args = "query_trade", {"candidate_id": content["candidates"][0]["id"], "flow": "import" if case_id == "R03" else "export", "partner": "all", "period": {"type": "latest_contiguous", "count": 12}}
                        else:
                            name, args = "finish", {"report_ids": [content["report_id"]], "source_ids": []}
                    return io.BytesIO(json.dumps({"choices": [{"message": {"content": None, "reasoning_content": "private-offline-fixture", "tool_calls": [{"id": uuid.uuid4().hex, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}], "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}}).encode())
                return create_accounted_model(OpenAICompatibleConfig("https://api.deepseek.com", "deepseek-flash", api_key="fixture-only", temperature=0),
                    {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "max_tokens": 8192}, ledger,
                    next(t for t in turns if t["case_id"] == case_id), transport=transport)
            executor = AgentCaseExecutor(plan, json.loads((root / "reference/trade.json").read_text()), DATA_ROOT,
                root / "runtime", root / "results/evidence", factory)
            def execute(t):
                if t["case_id"] in {"R02", "R03"}:
                    return executor(t)
                return {"case_id": t["case_id"], "continuation_ready": True,
                    "request_accounting_complete": True, "responses": 0, "origin": "offline_fixture"}
            with ledger.batch():
                results = execute_cases(plan, turns, root / "results/batch", execute,
                    continuation=continuation, verify_inputs=lambda: verify_continuation(root))
            self.assertEqual(factories, ["R02", "R03"], {"results": results,
                "failures": [json.loads(p.read_text()) for p in root.rglob("*-failed.json")]})
            self.assertEqual(len(ledger.records()), 6)
            self.assertEqual(len(results), 11)
            self.assertTrue(all(r["continuation_ready"] for r in results[:2]))
            self.assertIn("编码：1201", observed_context[0])
            self.assertFalse((root / "results/batch/claims/R01.json").exists())
            self.assertFalse((root / "results/batch/R01.json").exists())
            summary = score_package(root)["summary"]
            self.assertEqual((summary["planned"], summary["normal_planned"], summary["boundary_planned"]), (11, 8, 3))
            self.assertEqual(summary["model_denominator"], 0)
            self.assertEqual(summary["release_gate"], "not_comparable_segmented_protocol")
            self.assertEqual(file_hash(Path(continuation["parent"]) / "results/batch/R01.json"), parent_hash)

    def continuation_ledger(self, directory, *, consumed_cost="0.036040"):
        from scripts.us_retest_transport import canonical_hash
        base = Path(directory)
        parent = base / "parent"
        (parent / "ledgers/live").mkdir(parents=True, exist_ok=True)
        p = permit()
        allowlist = ["R02", "R03", "R04", "R05", "R06", "T01", "T02", "T03", "T04", "P01", "P02"]
        c = {"parent": str(parent), "parent_freeze_sha256": "c" * 64, "parent_files": {},
            "consumed_requests": 5, "consumed_cost": consumed_cost, "allowlist": allowlist}
        p.update(schema="us-retest-continuation-permit-v2", currency="CNY", budget="10",
            input_price_per_million="2", output_price_per_million="8", user_turns=11,
            new_time_window_authorized=True, parent_freeze_sha256=c["parent_freeze_sha256"],
            parent_files_sha256=canonical_hash(c["parent_files"]), consumed_requests=5,
            consumed_cost=consumed_cost, allowlist=allowlist)
        turns = [turn(i) for i in allowlist]
        ledger = SendLedger(base / "child/ledgers/live", p, lambda: "a" * 64, turns=turns,
            clock=lambda: 1, monotonic=lambda: 1, continuation=c)
        return ledger, turns

    def test_cumulative_limit_and_only_one_child(self):
        from scripts.us_retest_transport import canonical_hash
        with tempfile.TemporaryDirectory() as directory:
            ledger, turns = self.continuation_ledger(directory)
            with ledger.batch():
                opener = AccountedOpener(ledger, turns[0], transport=lambda *a, **k: response())
                opener(request(), timeout=90)
                opener.settle()
                self.assertEqual(ledger.records()[0]["cumulative_number"], 6)
                for i in range(2, 44):
                    (ledger.root / f"send-{i:03d}.json").write_text(json.dumps({"id": f"send-{i:03d}", "case_id": "fixture", "number": i}))
                    (ledger.root / f"send-{i:03d}-settled.json").write_text(json.dumps({"estimated_cost": "0.0012"}))
                with self.assertRaises(GateError):
                    ledger.reserve(request(), turns[-1])
                self.assertEqual(len(ledger.records()), 43)
            with self.assertRaises(GateError):
                with ledger.batch():
                    pass
            other = SendLedger(Path(directory) / "other/ledgers/live", ledger.permit, lambda: "a" * 64,
                turns=turns, clock=lambda: 1, monotonic=lambda: 1, continuation=ledger.continuation)
            with self.assertRaises(GateError):
                with other.batch():
                    pass

    def test_invalid_carry_or_unapproved_new_time_window_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(GateError):
                self.continuation_ledger(directory, consumed_cost="0")
            ledger, turns = self.continuation_ledger(directory)
            p = dict(ledger.permit)
            p["new_time_window_authorized"] = False
            with self.assertRaises(GateError):
                SendLedger(Path(directory) / "bad", p, lambda: "a" * 64, turns=turns,
                    clock=lambda: 1, continuation=ledger.continuation)

    def test_cumulative_cost_includes_ancestor_and_retains_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, turns = self.continuation_ledger(directory)
            with ledger.batch():
                (ledger.root / "send-001.json").write_text(json.dumps({"id": "send-001", "case_id": "fixture", "number": 1}))
                (ledger.root / "send-001-settled.json").write_text(json.dumps({"estimated_cost": "4.75"}))
                with self.assertRaises(GateError):
                    ledger.reserve(request(), turns[0])
                self.assertEqual(len(ledger.records()), 1)
                (ledger.root / "send-002.json").write_text(json.dumps({"id": "send-002", "case_id": "fixture", "number": 2}))
                with self.assertRaises(GateError):
                    ledger.reserve(request(), turns[0])
                self.assertFalse((ledger.root / "send-002-settled.json").exists())


if __name__ == "__main__":
    unittest.main()
