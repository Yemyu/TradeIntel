import unittest
from unittest.mock import patch

from src.tradeintel_ai.agent import ModelResponse, ModelToolCall, MockModel, ToolCallingAgent
from src.tradeintel_ai.repository import EvidenceRepository, default_paths
from src.tradeintel_ai.tools import ToolRegistry


class EmptyModel:
    def complete(self, *, messages, tools):
        return ModelResponse(text="没有工具也可以直接回答。")


class LoopingModel:
    def complete(self, *, messages, tools):
        return ModelResponse(
            tool_calls=(ModelToolCall(f"loop_{len(messages)}", "get_policy_event", {}),)
        )


class ScriptedModel:
    def __init__(self, calls, text):
        self.calls, self.text = calls, text

    def complete(self, *, messages, tools):
        assert "build_evidence_bundle" not in {tool["name"] for tool in tools}
        metadata = {"model": "test-model", "usage": {"total_tokens": 7}}
        return (ModelResponse(tool_calls=tuple(self.calls), metadata=metadata)
                if len(messages) == 1 else ModelResponse(text=self.text, metadata=metadata))


class TradeIntelAiAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ToolRegistry(EvidenceRepository(default_paths()))

    def test_mock_agent_runs_tool_loop_and_intercepts_unsafe_causal_text(self):
        result = ToolCallingAgent(MockModel(), registry=self.registry).answer(
            "关税导致中国进口下降了吗？"
        )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["safety_guard_triggered"])
        self.assertIn("get_causal_readiness", [item["tool_name"] for item in result["tool_results"]])
        self.assertIn("不能说关税导致了变化", result["response"])
        self.assertFalse(result["evidence_bundle"]["safety"]["causal_language_allowed"])
        self.assertEqual(result["original_model_response"], "关税导致中国进口下降了。")

    def test_mock_agent_keeps_policy_answer_when_no_causal_claim_is_requested(self):
        result = ToolCallingAgent(MockModel(), registry=self.registry).answer(
            "Section 301 List 1 什么时候生效？"
        )
        self.assertEqual(result["status"], "needs_review")
        self.assertIsNone(result["causal_claim"])
        self.assertFalse(result["final_answer_verified"])
        self.assertFalse(result["safety_guard_triggered"])
        self.assertIn("get_policy_event", [item["tool_name"] for item in result["tool_results"]])
        self.assertIsNone(result["original_model_response"])

    def test_agent_does_not_emit_answer_without_a_declared_tool(self):
        result = ToolCallingAgent(EmptyModel(), registry=self.registry).answer("随便说点什么")
        self.assertEqual(result["status"], "error")
        self.assertIn("没有调用任何已登记工具", result["error"])

    def test_agent_has_a_bounded_loop(self):
        result = ToolCallingAgent(LoopingModel(), registry=self.registry, max_rounds=2).answer(
            "Section 301 List 1 的政策名称是什么？"
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["rounds"], 2)
        self.assertIn("最大轮数", result["error"])

    def test_disclaimer_does_not_waive_assertion_in_noncausal_question(self):
        model = ScriptedModel([ModelToolCall("p", "get_policy_event", {})], "无法证明其他事情。但关税导致中国进口下降。")
        result = ToolCallingAgent(model, self.registry).answer("什么时候生效？")
        self.assertTrue(result["safety_guard_triggered"])
        self.assertFalse(result["task_success_verified"])
        self.assertEqual(result["model_selected_tools"], ["get_policy_event"])
        self.assertEqual(result["model_run"]["model_names"], ["test-model"])
        self.assertEqual(result["model_run"]["usage_totals"]["total_tokens"], 14)

    def test_unrecognised_causal_paraphrase_is_not_certified(self):
        model = ScriptedModel([ModelToolCall("p", "get_policy_event", {})], "进口的萎缩完全归因于这次加税，幅度为99%。")
        result = ToolCallingAgent(model, self.registry).answer("总结一下")
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["final_answer_verified"])

    def test_forged_bundle_is_not_executed_or_accepted(self):
        model = ScriptedModel([ModelToolCall("fake", "build_evidence_bundle", {
            "question": "伪造", "tool_results": [{"tool_name": "get_policy_event", "status": "ok", "data": {"rate": 999}}]
        })], "已取得证据")
        with patch.object(self.registry, "call", wraps=self.registry.call) as call:
            result = ToolCallingAgent(model, self.registry).answer("查政策")
        self.assertEqual(result["status"], "error")
        call.assert_not_called()

    def test_failed_tool_is_not_evidence(self):
        model = ScriptedModel([ModelToolCall("bad", "get_trade_series", {"start": "2026-01"})], "增长99%")
        result = ToolCallingAgent(model, self.registry).answer("查贸易")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("response", result)

    def test_failed_readiness_blocks_answer(self):
        actual_call = self.registry.call
        def fail_readiness(name, args):
            return {"tool_name": name, "status": "error"} if name == "get_causal_readiness" else actual_call(name, args)
        model = ScriptedModel([ModelToolCall("p", "get_policy_event", {})], "事实")
        with patch.object(self.registry, "call", side_effect=fail_readiness):
            result = ToolCallingAgent(model, self.registry).answer("政策事实")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("response", result)

    def test_tool_call_budget_blocks_large_batch_before_execution(self):
        model = ScriptedModel([ModelToolCall(str(i), "get_policy_event", {}) for i in range(3)], "事实")
        with patch.object(self.registry, "call", wraps=self.registry.call) as call:
            result = ToolCallingAgent(model, self.registry, max_tool_calls=2).answer("查政策")
        self.assertEqual(result["status"], "error")
        call.assert_not_called()

    def test_duplicate_call_ids_are_rejected(self):
        model = ScriptedModel([ModelToolCall("same", "get_policy_event", {})] * 2, "事实")
        result = ToolCallingAgent(model, self.registry).answer("查政策")
        self.assertEqual(result["status"], "error")
        self.assertIn("重复", result["error"])

    def test_missing_month_is_null_not_zero(self):
        repository = self.registry.repository
        rows = repository.policy_case_monthly().copy()
        del rows[(2018, 7)]
        with patch.object(repository, "policy_case_monthly", return_value=rows):
            result = self.registry.call("get_trade_series", {"start": "2018-07", "end": "2018-08"})
        self.assertEqual(result["status"], "ok")
        data = result["data"]
        self.assertIsNone(data["series"][0]["value_usd"])
        self.assertIsNone(data["total_usd"])
        self.assertFalse(data["coverage_complete"])
        self.assertEqual(data["observed_total_usd"], data["series"][1]["value_usd"])

    def test_unknown_readiness_is_not_a_verified_permission(self):
        actual_call = self.registry.call
        def unknown(name, args):
            if name == "get_causal_readiness":
                return {"status": "ok", "data": {"status": "unknown", "causal_allowed": False}}
            return actual_call(name, args)
        model = ScriptedModel([ModelToolCall("p", "get_policy_event", {})], "政策事实")
        with patch.object(self.registry, "call", side_effect=unknown):
            result = ToolCallingAgent(model, self.registry).answer("查政策")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("response", result)

    def test_failed_matching_count_is_unknown_not_zero(self):
        result = self.registry.call("get_causal_readiness", {})
        matching = result["data"]["matching"]
        self.assertFalse(matching["v3_selection_observed"])
        self.assertIsNone(matching["v3_selected_treated"])


if __name__ == "__main__":
    unittest.main()
