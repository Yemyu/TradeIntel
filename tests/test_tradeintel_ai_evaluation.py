import unittest
from tempfile import TemporaryDirectory
from scripts.evaluate_tradeintel_ai import evaluate, summarise, direct_baseline_scores, score_question
from pathlib import Path


class TradeIntelAiEvaluationTests(unittest.TestCase):
    def test_frozen_sixty_question_report_passes_tool_contract_gates(self):
        with TemporaryDirectory() as directory:
            report = evaluate(output_dir=Path(directory))
        self.assertEqual(report["question_count"], 60)
        self.assertEqual(report["decision"], "tool_contracts_passed_ready_for_llm_adapter")
        tool = report["systems"]["deterministic_tool_baseline"]
        self.assertEqual(tool["tool_selection_accuracy"], 1.0)
        self.assertEqual(tool["tool_data_assertion_accuracy"], 1.0)
        self.assertEqual(tool["source_presence_rate"], 1.0)
        self.assertEqual(tool["refusal_signal_accuracy"], 1.0)
        self.assertEqual(tool["unsafe_permission_signal_count"], 0)
        self.assertFalse(report["model_adopted"])
        self.assertIsNone(report["final_answer_evaluation"]["metrics"])
        self.assertFalse(report["leakage_controls"]["gold_labels_sent_to_router"])
        self.assertFalse(report["leakage_controls"]["post_policy_activity_used_for_matching"])
        self.assertFalse(report["leakage_controls"]["arbitrary_sql_allowed"])

    def test_unrun_baseline_has_no_fabricated_scores(self):
        baseline = direct_baseline_scores([], {})
        self.assertEqual(baseline["status"], "not_run")
        self.assertIsNone(baseline["metrics"])
        self.assertNotIn("unsupported_causal_claims", baseline)

    def test_no_observations_are_not_perfect_accuracy(self):
        metrics = summarise([])
        for key in ("tool_selection_accuracy", "tool_data_assertion_accuracy", "source_presence_rate", "refusal_signal_accuracy"):
            self.assertIsNone(metrics[key])

    def test_failed_response_cannot_pass_with_correct_looking_fields(self):
        score = score_question({"id": "failure", "category": "policy"},
            {"tools": ["get_policy_event"], "assertions": [{"tool": "get_policy_event", "path": "data.rate", "value": 25}], "must_refuse": True, "must_cite": ["official"]},
            {"status": "error", "selected_tools": ["get_policy_event"],
             "tool_results": [{"tool_name": "get_policy_event", "status": "error", "data": {"rate": 25}, "evidence": {"sources": ["official"]}}],
             "evidence_bundle": {"safety": {"causal_claim": False, "causal_language_allowed": False, "causal_blocked": True}}})
        for field in ("tool_selection_passed", "numeric_passed", "source_passed", "refusal_passed"):
            self.assertFalse(score[field])


if __name__ == "__main__":
    unittest.main()
