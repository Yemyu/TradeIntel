import json
import unittest
from pathlib import Path


class TradeIntelAiEvaluationTests(unittest.TestCase):
    def test_frozen_sixty_question_report_passes_tool_contract_gates(self):
        root = Path(__file__).resolve().parents[1]
        report = json.loads(
            (root / "data/processed/ai/ai_evaluation_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["question_count"], 60)
        self.assertEqual(report["decision"], "tool_contracts_passed_ready_for_llm_adapter")
        tool = report["systems"]["deterministic_tool_baseline"]
        self.assertEqual(tool["tool_selection_accuracy"], 1.0)
        self.assertEqual(tool["numeric_accuracy"], 1.0)
        self.assertEqual(tool["source_citation_accuracy"], 1.0)
        self.assertEqual(tool["correct_refusal"], 1.0)
        self.assertEqual(tool["unsupported_causal_claims"], 0)
        self.assertFalse(report["leakage_controls"]["gold_labels_sent_to_router"])
        self.assertFalse(report["leakage_controls"]["post_policy_activity_used_for_matching"])
        self.assertFalse(report["leakage_controls"]["arbitrary_sql_allowed"])


if __name__ == "__main__":
    unittest.main()
