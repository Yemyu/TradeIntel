import unittest

from src.tradeintel_ai.agent import ModelResponse, ModelToolCall, MockModel, ToolCallingAgent
from src.tradeintel_ai.repository import EvidenceRepository, default_paths
from src.tradeintel_ai.tools import ToolRegistry


class EmptyModel:
    def complete(self, *, messages, tools):
        return ModelResponse(text="没有工具也可以直接回答。")


class LoopingModel:
    def complete(self, *, messages, tools):
        return ModelResponse(
            tool_calls=(ModelToolCall("loop", "get_policy_event", {}),)
        )


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
        self.assertEqual(result["status"], "ok")
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


if __name__ == "__main__":
    unittest.main()
