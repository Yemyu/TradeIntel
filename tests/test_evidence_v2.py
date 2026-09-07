from copy import deepcopy
import unittest

from src.tradeintel_ai.agent import ModelResponse, ModelToolCall
from src.tradeintel_ai.evidence_v2 import EvidenceAgentV2, EvidenceRegistryV2, build_report


class ScriptedModel:
    def __init__(self, calls, draft):
        self.calls, self.draft = calls, draft
    def complete(self, *, messages, tools):
        if len(messages) == 1 and self.calls:
            return ModelResponse(tool_calls=tuple(ModelToolCall(str(i), n, a) for i,(n,a) in enumerate(self.calls)))
        return ModelResponse(text=self.draft, metadata={"finish_reason":"stop"})


class EvidenceV2Tests(unittest.TestCase):
    def test_negation_and_positive_claim_both_keep_facts_and_quarantine_prose(self):
        for text in ("不能说关税导致下降", "关税导致下降99%。来源https://fake.invalid/x"):
            agent = EvidenceAgentV2(ScriptedModel([("get_descriptive_change", {})], text))
            result = agent.answer("报告描述性变化")
            self.assertIn("13,623,956,741", result["response"])
            self.assertIn("10,393,832,954", result["response"])
            self.assertIn("-23.7091", result["response"])
            self.assertNotIn(text, result["response"])
            self.assertEqual(result["draft_for_audit_only"], text)
            self.assertFalse(result["model_prose_published"])
            self.assertFalse(result["task_success_verified"])

    def test_v1_counts_and_units_present(self):
        result = EvidenceRegistryV2().call("get_causal_readiness")
        m = result["data"]["matching"]
        self.assertEqual(m["v1_treated_denominator"], 315)
        self.assertEqual(m["v1_treated_with_at_least_two_controls"], 284)
        self.assertIsNone(m["v3_selected_treated"])
        report = build_report([result])
        self.assertIn("HS6_2017商品", report.render())

    def test_numeric_fact_sources_are_statistical_not_policy(self):
        result = EvidenceAgentV2(ScriptedModel([("get_descriptive_change", {})], "完成")).answer("变化")
        facts = [f for f in result["facts"] if f["unit"] in ("美元", "%", "个百分点") and "覆盖率" not in f["label"]]
        self.assertTrue(facts)
        for fact in facts:
            self.assertTrue(all(result["sources"][sid]["path"].endswith("statistical_baseline_summary.json") for sid in fact["source_ids"]))

    def test_selected_months_sum_and_overlap_are_not_double_counted(self):
        registry = EvidenceRegistryV2()
        results = [registry.call("get_trade_series", {"start":m, "end":m}) for m in ("2017-01", "2017-03", "2017-05", "2017-03")]
        report = build_report(results)
        self.assertEqual(report.facts[-1]["value"], 7885853095)
        self.assertEqual(report.facts[-2]["value"]["months"], ["2017-01", "2017-03", "2017-05"])

    def test_conflicting_values_rejected_and_missing_not_zero(self):
        result = EvidenceRegistryV2().call("get_trade_series", {"start":"2017-01", "end":"2017-01"})
        changed = deepcopy(result)
        changed["data"]["series"][0]["value_usd"] = None
        changed["data"]["total_usd"] = None
        changed["data"]["missing_months"] = ["2017-01"]
        self.assertIsNone(build_report([changed]).facts[-1]["value"])
        with self.assertRaises(ValueError):
            build_report([result, changed])

    def test_no_successful_tool_does_not_publish_fabricated_answer(self):
        result = EvidenceAgentV2(ScriptedModel([], "关税造成下降")).answer("问题")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("response", result)

    def test_all_five_tools_render_and_every_fact_has_known_source(self):
        registry = EvidenceRegistryV2()
        args = {"get_trade_series": {"start":"2018-08", "end":"2018-08"}}
        results = [registry.call(name, args.get(name, {})) for name in registry.names() if name != "build_evidence_bundle"]
        self.assertTrue(all(r["status"] == "ok" for r in results))
        report = build_report(results)
        self.assertGreater(len(report.facts), 30)
        for fact in report.facts:
            self.assertTrue(fact["source_ids"])
            self.assertTrue(all(s in report.sources for s in fact["source_ids"]))


if __name__ == "__main__":
    unittest.main()
