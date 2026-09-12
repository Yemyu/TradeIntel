"""0118 integration checks: independent scope, paired payloads and fact packets."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.prospective_runner import (
    SyntheticCase,
    default_cases,
    run_synthetic_batch,
)
from tradeintel_ai.prospective_acceptance import validate_fact_review, digest
from tests.test_prospective_runner_0114 import StaticModel, policy_case, trade_case
from tests.test_trade_mapping_proposal_0105 import candidate


class RunnerControls0118Tests(unittest.TestCase):
    def test_independent_baseline_is_saved_and_scope_is_compared(self):
        original = trade_case()
        p = candidate()
        case = SyntheticCase(
            original.id, original.question, original.expected_kind,
            original.expected_tasks, original.checklist, original.reference,
            True, (), {"trade": p["trade"], "comparison": p["comparison"]}, (),
        )
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            summary = run_synthetic_batch(
                out, cases=[case], model_factory=lambda *_: StaticModel(candidate())
            )
            self.assertEqual(summary["status"], "completed")
            baseline = json.loads((out / case.id / "baseline.json").read_text())
            scope = json.loads((out / case.id / "scope-comparison.json").read_text())
            self.assertEqual(baseline["reference_origin"],
                             "host_frozen_fixture_request_before_planning")
            self.assertTrue(scope["scope_equal"])
            self.assertFalse(scope["proposal_repaired"])

    def test_scope_mismatch_stops_before_delivery(self):
        original = trade_case()
        p = candidate()
        independent = {"trade": dict(p["trade"]), "comparison": dict(p["comparison"])}
        independent["trade"]["origin"] = "China"
        case = SyntheticCase(
            original.id, original.question, original.expected_kind,
            original.expected_tasks, original.checklist, original.reference,
            True, (), independent, (),
        )
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            summary = run_synthetic_batch(
                out, cases=[case], model_factory=lambda *_: StaticModel(candidate())
            )
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(summary["stop_reason"], "trade_scope_mismatch")
            self.assertFalse((out / case.id / "delivery").exists())
            scope = json.loads((out / case.id / "scope-comparison.json").read_text())
            self.assertIn("trade.origin", scope["differences"])

    def test_policy_pair_captures_settings_and_keeps_fact_review_pending(self):
        case = default_cases()[2]
        plan_case, planning_payload = policy_case()

        def factory(stage, _case):
            if stage == "planning":
                return StaticModel(planning_payload)
            if stage == "policy_with_evidence":
                def with_evidence(messages, _tools):
                    request = json.loads(messages[-1]["content"])
                    citation = request["evidence"][0]["id"]
                    return ModelResponse(
                        text=json.dumps({"claims": [{"text": "证据草稿", "citations": [citation]}]},
                                         ensure_ascii=False),
                        metadata={"finish_reason": "stop", "usage": {"total_tokens": 7}},
                    )
                return StaticModel(callback=with_evidence)
            return StaticModel({"answer": "无法可靠回答", "claims": []})

        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            summary = run_synthetic_batch(out, cases=[case], model_factory=factory)
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(summary["stop_reason"], "fact_review_pending")
            self.assertEqual(summary["stage_counts"]["policy_no_evidence"], 0)
            pending = json.loads((out / "reviews" /
                                  f"{case.id}-facts-with_evidence-pending.json").read_text())
            self.assertEqual(pending["status"], "pending_human")

    def test_mismatched_pair_is_rejected_before_policy_answer(self):
        _, planning_payload = policy_case()

        class Configured(StaticModel):
            def __init__(self, payload, model):
                super().__init__(payload)
                self.config = SimpleNamespace(model=model, base_url="fixture://provider",
                                              temperature=0.0, timeout_seconds=60.0)

        def factory(stage, _case):
            if stage == "planning":
                return Configured(planning_payload, "planner")
            return Configured({"answer": "不确定", "claims": []},
                              "with-model" if stage == "policy_with_evidence" else "without-model")

        case = SyntheticCase(
            "PAIR-MISMATCH-01", policy_case()[0].question, "support", ("policy",),
            ({"id": "policy_claim", "kind": "policy"},), {"gold_marker": "pair"},
            True, ("2018-07-06", "25%"), None, (),
        )
        with TemporaryDirectory() as tmp:
            summary = run_synthetic_batch(Path(tmp) / "run", cases=[case], model_factory=factory)
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(summary["stage_counts"]["policy_with_evidence"], 0)


class FactReview0118Tests(unittest.TestCase):
    def test_fact_review_requires_actual_claims_and_evidence(self):
        packet = {
            "version": "fact-review-packet-0118", "case_id": "P1",
            "arm": "with_evidence", "answer": {
                "text": "税率25%", "claims": [{"text": "税率25%", "citations": ["src1"]}]
            },
            "facts": [{"id": "rate", "required_fact": "额外税率25%"}],
            "evidence": {"src1": {"text": "官方文件：额外税率为25%。"}},
        }
        submission = {
            "case_id": "P1", "arm": "with_evidence", "packet_sha256": digest(packet),
            "reviewer": "human", "reviewed_at": "2026-09-12T00:00:00Z",
            "facts": [{"id": "rate", "status": "supported", "reason": "原文支持",
                       "claim_indices": [0], "source_id": "src1",
                       "evidence_excerpt": "额外税率为25%"}],
            "claims": [{"index": 0, "status": "supported", "reason": "有来源",
                        "fact_ids": ["rate"]}],
            "citation_review": {"status": "pass", "reason": "来源存在"},
        }
        result = validate_fact_review(packet, submission)
        self.assertTrue(result["approved"])
        self.assertEqual(result["fact_counts"]["supported"], 1)


if __name__ == "__main__":
    unittest.main()
