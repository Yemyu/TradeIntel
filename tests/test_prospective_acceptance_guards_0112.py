import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.prospective_acceptance import (
    AcceptanceGuardError,
    AcceptanceStopped,
    FrozenInputChanged,
    ProspectiveCallLedger,
    ReferenceLeakage,
    assert_no_reference_leakage,
    digest,
    freeze_dependencies,
    validate_structured_review,
    validate_terminal,
)


class ProspectiveAcceptanceGuardTests(unittest.TestCase):
    def frozen(self, tmp: Path):
        source = tmp / "runner.py"
        source.write_text("frozen = True\n", encoding="utf-8")
        return source, freeze_dependencies([source], configuration={"model": "fixture"})

    def support_packet(self):
        return {
            "preview": {"status": "needs_confirmation", "tasks": ["policy"]},
            "result": {
                "status": "policy_draft",
                "tasks": ["policy"],
                "policy": {"generation": {"status": "draft_requires_semantic_review",
                    "claims": [{"text": "税率25%", "citations": ["p1"]}]}},
                "policy_evidence": {"hits": [{"id": "p1", "text": "公布税率为25%"}]},
                "amount": 25,
            },
            "delivery": {"verified": True, "status": "complete", "missing_files": []},
            "checklist": [
                {"id": "P1", "kind": "policy"},
                {"id": "N1", "kind": "number", "checks": [{"path": ["amount"], "expected": 25}]},
            ],
        }

    def passing_review(self):
        return {
            "overall": {"status": "pass", "reason": "逐项核对完成"},
            "items": [
                {"id": "P1", "status": "supported", "reason": "原文摘录一致",
                 "witnesses": [{"claim_index": 0, "claim_text": "税率25%",
                                "citation_id": "p1", "evidence_excerpt": "公布税率为25%"}]},
                {"id": "N1", "status": "supported", "reason": "独立复算一致",
                 "witnesses": [{"value": 25}], "checks": [{"path": ["amount"], "expected": 25}]},
            ],
        }

    def test_hard_connection_failure_cannot_be_overridden_by_reviewer(self):
        packet = self.support_packet()
        packet["result"]["status"] = "needs_review"
        packet["result"]["diagnostic"] = {"category": "connection"}
        guarded = validate_terminal(
            preview=packet["preview"], result=packet["result"], delivery=packet["delivery"],
            review={"approved": True}, expected_tasks=["policy"],
        )
        self.assertFalse(guarded["approved"])
        self.assertTrue(guarded["reviewer_cannot_override"])
        self.assertIn("diagnostic:connection", guarded["hard_failures"])

    def test_structure_and_incomplete_delivery_are_hard_failures(self):
        packet = self.support_packet()
        packet["result"]["audit"] = {"diagnostic": {"category": "structure"}}
        packet["delivery"] = {"verified": False, "status": "incomplete", "missing_files": ["result.json"]}
        guarded = validate_terminal(
            preview=packet["preview"], result=packet["result"], delivery=packet["delivery"],
            review={"approved": True}, expected_tasks=["policy"],
        )
        self.assertFalse(guarded["approved"])
        self.assertIn("diagnostic:structure", guarded["hard_failures"])
        self.assertIn("delivery:incomplete", guarded["hard_failures"])

    def test_non_support_terminal_cannot_be_executed(self):
        guarded = validate_terminal(
            preview={"status": "needs_confirmation"},
            result={"status": "policy_draft", "executed": True},
            review={"approved": True}, expected_kind="clarification",
        )
        self.assertFalse(guarded["approved"])
        self.assertIn("terminal:unsafe_execution", guarded["hard_failures"])

    def test_structured_review_requires_every_item_and_witnesses(self):
        packet = self.support_packet()
        incomplete = {"overall": {"status": "pass", "reason": "看过了"},
                      "packet_sha256": digest(packet),
                      "items": [{"id": "P1", "status": "supported", "reason": "有引用",
                                 "witnesses": [{"citation_id": "p1", "evidence_excerpt": "税率"}]}]}
        with self.assertRaises(AcceptanceGuardError):
            validate_structured_review(packet, incomplete, reviewer="fixture", expected_tasks=["policy"])

        review = self.passing_review()
        review["packet_sha256"] = digest(packet)
        accepted = validate_structured_review(packet, review, reviewer="fixture", expected_tasks=["policy"])
        self.assertTrue(accepted["approved"])
        self.assertFalse(accepted["semantic_coverage_verified"])

    def test_reference_values_do_not_enter_model_messages(self):
        reference = {"answer": "2018-07-06", "amount": 36587820118}
        assert_no_reference_leakage([{"role": "user", "content": "请分析政策"}], reference)
        with self.assertRaises(ReferenceLeakage):
            assert_no_reference_leakage([{"role": "system", "content": "amount=36587820118"}], reference)

    def test_dependency_tampering_blocks_next_reservation(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            source, snapshot = self.frozen(tmp)
            ledger = ProspectiveCallLedger(["Q1", "Q2"], tmp / "run", frozen_snapshot=snapshot)
            source.write_text("frozen = False\n", encoding="utf-8")
            with self.assertRaises(FrozenInputChanged):
                ledger.reserve("Q1", "planning")
            persisted = json.loads((tmp / "run" / "ledger.json").read_text())
            self.assertEqual(persisted["calls"], [])
            self.assertEqual(persisted["status"], "stopped")
            self.assertEqual(persisted["stop_reason"], "frozen_inputs_changed")

    def test_reservation_is_persisted_before_fake_provider_and_failure_stops(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            _, snapshot = self.frozen(tmp)
            ledger = ProspectiveCallLedger(["Q1", "Q2"], tmp / "run", frozen_snapshot=snapshot)
            reservation = ledger.reserve("Q1", "planning")
            persisted = json.loads((tmp / "run" / "ledger.json").read_text())
            self.assertEqual(persisted["calls"][0]["status"], "reserved")
            self.assertEqual(persisted["questions"][0]["status"], "in_progress")
            failed = ledger.fail(reservation, category="connection")
            self.assertEqual(failed["status"], "failed")
            summary = ledger.summary()
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(summary["not_run"], ["Q2"])
            with self.assertRaises(AcceptanceStopped):
                ledger.reserve("Q2", "planning")

    def test_unknown_usage_stops_and_keeps_remaining_questions_not_run(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            _, snapshot = self.frozen(tmp)
            ledger = ProspectiveCallLedger(["Q1", "Q2", "Q3"], tmp / "run", frozen_snapshot=snapshot)
            reservation = ledger.reserve("Q1", "planning")
            row = ledger.complete(reservation, metadata={"finish_reason": "stop", "usage": {}})
            self.assertEqual(row["usage_status"], "unknown")
            summary = ledger.summary()
            self.assertEqual(summary["stop_reason"], "unknown_usage")
            self.assertEqual(summary["not_run"], ["Q2", "Q3"])

    def test_reported_token_boundary_stops_without_another_call(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            _, snapshot = self.frozen(tmp)
            ledger = ProspectiveCallLedger(["Q1", "Q2"], tmp / "run", frozen_snapshot=snapshot,
                                           token_budget=80_000)
            reservation = ledger.reserve("Q1", "planning")
            ledger.complete(reservation, metadata={"finish_reason": "stop", "usage": {"total_tokens": 80_000}})
            self.assertEqual(ledger.summary()["stop_reason"], "reported_token_budget_reached")
            with self.assertRaises(AcceptanceStopped):
                ledger.reserve("Q2", "planning")

    def test_non_returned_completion_is_stopped_as_structure_failure(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            _, snapshot = self.frozen(tmp)
            ledger = ProspectiveCallLedger(["Q1"], tmp / "run", frozen_snapshot=snapshot)
            reservation = ledger.reserve("Q1", "planning")
            row = ledger.complete(reservation, metadata={"usage": {"total_tokens": 3}},
                                  response_status="needs_review")
            self.assertEqual(row["status"], "failed")
            self.assertEqual(ledger.summary()["stop_reason"], "call_failed:structure")

    def test_raw_response_and_review_are_redacted_and_hashed(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            _, snapshot = self.frozen(tmp)
            ledger = ProspectiveCallLedger(["Q1"], tmp / "run", frozen_snapshot=snapshot)
            reservation = ledger.reserve("Q1", "planning")
            row = ledger.complete(
                reservation,
                metadata={"usage": {"total_tokens": 4}, "finish_reason": "stop"},
                raw_response={"text": "safe", "credential": "secret-key"},
                secret="secret-key",
            )
            response_path = tmp / "run" / row["raw_response"]["path"]
            self.assertNotIn("secret-key", response_path.read_text())
            self.assertEqual(row["raw_response"]["sha256"],
                             ledger.state["artifacts"][row["raw_response"]["path"]]["sha256"])
            artifacts = ledger.record_review("Q1", "planning",
                                             {"overall": {"status": "fail", "reason": "未通过",
                                                           "credential": "secret-key"}},
                                             packet={"question": "safe"}, secret="secret-key")
            self.assertEqual(len(artifacts), 2)
            self.assertNotIn("secret-key", (tmp / "run" / artifacts[next(iter(artifacts))]["path"]).read_text())


if __name__ == "__main__":
    unittest.main()
