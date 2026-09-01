import unittest

from src.tradeintel_ai.repository import EvidenceRepository, default_paths
from src.tradeintel_ai.router import answer_question, classify_question, infer_comparison_id
from src.tradeintel_ai.tools import (
    build_evidence_bundle,
    get_causal_readiness,
    get_data_quality_status,
    get_descriptive_change,
    get_policy_event,
    get_trade_series,
    ToolRegistry,
)


class TradeIntelAiToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = EvidenceRepository(default_paths())

    def test_policy_event_is_registered_and_source_linked(self):
        result = get_policy_event(repository=self.repository)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["policy_hts8_count"], 818)
        self.assertEqual(result["data"]["effective_date"], "2018-07-06")
        self.assertAlmostEqual(result["data"]["additional_rate_percent"], 25.0)
        self.assertTrue(result["evidence"]["official_policy_url"].startswith("https://"))
        self.assertFalse(result["causal_claim"])

    def test_trade_series_uses_fixed_scope_and_exact_descriptive_values(self):
        result = get_trade_series(
            origin="China",
            start="2018-08",
            end="2018-12",
            repository=self.repository,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["scope"], "section301_list1")
        self.assertEqual(result["data"]["months"], 5)
        self.assertEqual(result["data"]["missing_months"], [])
        self.assertEqual(result["data"]["total_usd"], 10393832954)
        self.assertEqual(len(result["evidence"]["sources"]), 9)
        self.assertFalse(result["causal_claim"])

    def test_descriptive_change_is_never_marked_causal(self):
        result = get_descriptive_change(repository=self.repository)
        self.assertEqual(result["data"]["comparison_id"], "immediate_post_same_months")
        self.assertAlmostEqual(result["data"]["target_change_pct"], -0.2370914594)
        self.assertFalse(result["data"]["causal_claim"])
        self.assertFalse(result["causal_claim"])
        self.assertTrue(any("不是" in item for item in result["limitations"]))

    def test_quality_and_causal_status_expose_reviews_and_hard_refusal(self):
        quality = get_data_quality_status(repository=self.repository)
        self.assertEqual(quality["data"]["overall_status"], "pass_with_review")
        self.assertEqual(quality["data"]["summary"]["failed_rule_count"], 0)
        self.assertEqual(
            {item["rule_id"] for item in quality["data"]["review_rules"]},
            {"ORIGIN-002", "COVERAGE-001"},
        )
        readiness = get_causal_readiness(repository=self.repository)
        self.assertEqual(readiness["data"]["status"], "blocked_before_pretrend_v3")
        self.assertFalse(readiness["data"]["causal_allowed"])
        self.assertEqual(readiness["data"]["matching"]["v1_coverage_rate"], 0.9015873015873016)
        self.assertEqual(readiness["data"]["matching"]["v3_solver_status_code"], 2)
        self.assertEqual(readiness["data"]["pretrend"], "not_run")

    def test_bundle_deduplicates_sources_and_preserves_safety_signal(self):
        descriptive = get_descriptive_change(repository=self.repository)
        readiness = get_causal_readiness(repository=self.repository)
        bundle = build_evidence_bundle(
            "关税导致进口下降了吗？",
            [descriptive, readiness],
            repository=self.repository,
        )
        self.assertTrue(bundle["generated_from_declared_tools"])
        self.assertFalse(bundle["safety"]["causal_claim"])
        self.assertFalse(bundle["safety"]["causal_language_allowed"])
        self.assertTrue(bundle["safety"]["causal_blocked"])
        self.assertEqual(
            len(bundle["sources"]),
            len({repr(source) for source in bundle["sources"]}),
        )

    def test_bundle_rejects_unregistered_tool_results(self):
        with self.assertRaises(ValueError):
            build_evidence_bundle(
                "测试",
                [{"tool_name": "run_any_sql", "status": "ok", "data": {}}],
                repository=self.repository,
            )

    def test_registry_rejects_unknown_tools_and_arbitrary_parameters(self):
        registry = ToolRegistry(self.repository)
        unknown = registry.call("run_any_sql", {})
        self.assertEqual(unknown["status"], "error")
        invalid = registry.call("get_trade_series", {"start": "2015-01"})
        self.assertEqual(invalid["status"], "error")
        self.assertIn("固定范围", invalid["error"]["message"])

    def test_router_baseline_routes_and_refuses_causal_language(self):
        self.assertEqual(classify_question("数据质量怎么样？"), "data_quality")
        self.assertEqual(classify_question("关税导致进口下降了吗？"), "causal_readiness")
        answer = answer_question(
            "2018年关税后中国进口下降多少？能证明关税导致下降吗？",
            registry=ToolRegistry(self.repository),
        )
        self.assertEqual(answer["status"], "ok")
        self.assertEqual(answer["intent"], "causal_readiness")
        self.assertIn("get_causal_readiness", answer["selected_tools"])
        self.assertIn("不能据此说关税导致了变化", answer["response"])
        self.assertFalse(answer["evidence_bundle"]["safety"]["causal_language_allowed"])

    def test_router_uses_only_declared_comparison_aliases(self):
        self.assertEqual(
            infer_comparison_id("政策前安慰剂比较是多少？"),
            "pre_policy_placebo_same_months",
        )
        self.assertEqual(
            infer_comparison_id("持续性监测窗口是多少？"),
            "persistence_monitoring_same_months",
        )
        self.assertEqual(
            infer_comparison_id("最近政策前窗口是多少？"),
            "recent_clean_pre_same_months",
        )

    def test_registry_exposes_exactly_six_declared_tools(self):
        registry = ToolRegistry(self.repository)
        self.assertEqual(
            registry.names(),
            [
                "get_policy_event",
                "get_trade_series",
                "get_descriptive_change",
                "get_data_quality_status",
                "get_causal_readiness",
                "build_evidence_bundle",
            ],
        )
        self.assertEqual(
            {schema["name"] for schema in registry.schemas()},
            set(registry.names()),
        )


if __name__ == "__main__":
    unittest.main()
