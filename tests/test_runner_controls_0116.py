"""Positive and negative checks for the real 0116 A/B controls."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.prospective_runner import SyntheticCase, run_synthetic_batch
from tests.test_prospective_runner_0114 import StaticModel, policy_case, trade_case
from tests.test_trade_mapping_proposal_0105 import candidate


class RunnerControls0116Tests(unittest.TestCase):
    def test_control_a_recomputes_trade_from_declared_csv(self):
        original = trade_case()
        case = SyntheticCase(
            original.id, original.question, original.expected_kind,
            original.expected_tasks, original.checklist, original.reference,
            True,
        )
        with TemporaryDirectory() as tmp:
            summary = run_synthetic_batch(
                Path(tmp) / "run", cases=[case],
                model_factory=lambda *_: StaticModel(candidate()),
            )
            self.assertTrue(summary["synthetic_protocol_completed"])
            self.assertFalse(summary["acceptance_ready"])
            controls = summary["controls"]
            self.assertEqual(len(controls), 1)
            artifact = Path(tmp) / "run" / next(iter(controls.values()))["artifact"]["path"]
            payload = json.loads(artifact.read_text())
            self.assertEqual(payload["method"], "independent_csv_recomputation")
            self.assertTrue(payload["checks"]["passed"])
            self.assertEqual(payload["actual"], payload["independent"])

    def test_control_b_records_actual_no_evidence_answer(self):
        original, planning_payload = policy_case()
        case = SyntheticCase(
            original.id, original.question, original.expected_kind,
            original.expected_tasks,
            ({"id": "policy_claim", "kind": "policy",
              "quote": "第一批关税何时生效，额外税率是多少？",
              "required_answer": "生效日期和额外税率",
              "task": "policy", "expected_disposition": "answer"},),
            original.reference, True, ("2018-07-06", "25%"),
        )
        seen_messages = []

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

            def no_evidence(messages, _tools):
                seen_messages.extend(messages)
                return ModelResponse(
                    text=json.dumps({"answer": "无法可靠回答", "claims": []}, ensure_ascii=False),
                    metadata={"finish_reason": "stop", "usage": {"total_tokens": 5}},
                )
            return StaticModel(callback=no_evidence)

        with TemporaryDirectory() as tmp:
            summary = run_synthetic_batch(Path(tmp) / "run", cases=[case], model_factory=factory)
            self.assertTrue(summary["synthetic_protocol_completed"])
            self.assertFalse(summary["acceptance_ready"])
            control = next(iter(summary["controls"].values()))
            payload = json.loads((Path(tmp) / "run" / control["artifact"]["path"]).read_text())
            self.assertEqual(payload["method"], "same_question_without_retrieved_evidence")
            self.assertEqual(payload["answer_quality"], "unreviewed")
            self.assertEqual(payload["literal_matches"], [])
            decision = json.loads((Path(tmp) / "run" /
                                   "reviews/RUN-POLICY-01-policy_with_evidence-decision.json").read_text())
            self.assertTrue(decision["legacy_checklist_review"]["approved"])
            sent = json.dumps(seen_messages, ensure_ascii=False)
            self.assertNotIn("evidence", sent)
            self.assertIn("2018-07-06", sent)


if __name__ == "__main__":
    unittest.main()
