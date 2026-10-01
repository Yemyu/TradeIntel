"""The paid pilot stays offline here: a fake HTTP provider exercises its real adapter."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_trade_agent_pilot as pilot
from tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleConfig, OpenAICompatibleModel
from tradeintel_ai.trade_agent_deepseek import DeepSeekThinkingToolModel, create_trade_agent_model


class FakeToolHTTP:
    def __init__(self, *, fail_after_first: bool = False,
                 thinking: bool = False, omit_reasoning: bool = False,
                 null_reasoning: bool = False):
        self.payloads = []
        self.fail_after_first = fail_after_first
        self.thinking = thinking
        self.omit_reasoning = omit_reasoning
        self.null_reasoning = null_reasoning

    def __call__(self, request, *, timeout):
        payload = json.loads(request.data)
        self.payloads.append(payload)
        if self.fail_after_first:
            raise TimeoutError("synthetic timeout")
        if self.thinking:
            if "tool_choice" in payload:
                raise AssertionError("thinking-mode request must omit tool_choice")
            for index, message in enumerate(item for item in payload["messages"]
                                            if item["role"] == "assistant" and "tool_calls" in item):
                expected = None if self.null_reasoning else f"private-reasoning-{index + 1}"
                if "reasoning_content" not in message or message["reasoning_content"] != expected:
                    raise AssertionError("reasoning_content was not replayed unchanged")
        last = payload["messages"][-1]
        if last["role"] == "user":
            name, arguments = "search_products", {"term": "大豆", "flow": "import"}
        elif "candidates" in (result := json.loads(last["content"])):
            name, arguments = "query_trade", {
                "candidate_id": result["candidates"][0]["id"], "flow": "import",
                "partner": "all", "period": {"type": "latest_contiguous", "count": 2},
            }
        else:
            name, arguments = "finish", {
                "report_ids": [result["report_id"]], "explanation": "请看已发布数据报告。",
                "source_ids": [],
            }
        response = {"id": f"fake-{len(self.payloads)}", "model": "fake-tool-model",
                    "choices": [{"finish_reason": "tool_calls", "message": {
                        "content": "", "tool_calls": [{"id": f"call-{len(self.payloads)}",
                        "type": "function", "function": {"name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False)}}]}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        if self.thinking and not self.omit_reasoning:
            response["choices"][0]["message"]["reasoning_content"] = (
                None if self.null_reasoning else f"private-reasoning-{len(self.payloads)}")
            response["choices"][0]["message"]["content"] = None
        return io.BytesIO(json.dumps(response, ensure_ascii=False).encode())


@unittest.skipUnless(pilot.DATA_ROOT.is_dir(), "verified local data bundle not installed")
class TradeAgentPilotOfflineTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.addCleanup(patch.stopall)
        patch.object(pilot, "ROOT", self.root).start()
        patch.object(pilot, "LEDGER_DIR", self.root / ".local/trade-agent-live-pilot/20260929-v1").start()

    def model(self, fake):
        return OpenAICompatibleModel(OpenAICompatibleConfig(
            "https://example.test/v1", "fake-tool-model", api_key="test-secret",
            timeout_seconds=2, temperature=0), system_prompt="", opener=fake,
            request_params={"max_tokens": 4096})

    def thinking_model(self, fake):
        return DeepSeekThinkingToolModel(OpenAICompatibleConfig(
            "https://api.deepseek.com", "deepseek-flash", api_key="test-secret",
            timeout_seconds=2, temperature=0), system_prompt="", opener=fake,
            request_params={"max_tokens": 4096, "thinking": {"type": "enabled"},
                            "reasoning_effort": "high"})

    def test_deepseek_thinking_replays_three_tool_rounds_without_persisting_reasoning(self):
        fake = FakeToolHTTP(thinking=True)
        result = pilot.run_live({"snapshot_sha256": "thinking-fixture"}, self.thinking_model(fake))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(fake.payloads), 3)
        self.assertNotIn("tool_choice", fake.payloads[0])
        self.assertEqual([item.get("reasoning_content") for item in fake.payloads[2]["messages"]
                          if item["role"] == "assistant"],
                         ["private-reasoning-1", "private-reasoning-2"])
        self.assertEqual([item.get("content") for item in fake.payloads[2]["messages"]
                          if item["role"] == "assistant"], [None, None])
        ledger = (pilot.LEDGER_DIR / "first-question.json").read_text()
        self.assertNotIn("private-reasoning", ledger)
        self.assertNotIn("test-secret", ledger)
        self.assertNotIn("private-reasoning", json.dumps(result, ensure_ascii=False))

    def test_missing_reasoning_stops_after_one_response(self):
        fake = FakeToolHTTP(thinking=True, omit_reasoning=True)
        result = pilot.run_live({"snapshot_sha256": "missing-fixture"}, self.thinking_model(fake))
        self.assertEqual(result["status"], "unknown_outcome")
        self.assertEqual(len(fake.payloads), 1)

    def test_nullable_reasoning_is_replayed_as_null_not_dropped(self):
        fake = FakeToolHTTP(thinking=True, null_reasoning=True)
        result = pilot.run_live({"snapshot_sha256": "null-fixture"}, self.thinking_model(fake))
        self.assertEqual(result["status"], "completed")
        self.assertTrue(all(item.get("reasoning_content", "missing") is None
                            for item in fake.payloads[2]["messages"]
                            if item["role"] == "assistant"))

    def test_thinking_payload_rejects_assistant_without_reasoning_before_request(self):
        fake = FakeToolHTTP(thinking=True)
        model = self.thinking_model(fake)
        with self.assertRaisesRegex(ModelAdapterError, "缺少 reasoning_content"):
            model._payload(messages=[{"role": "assistant", "content": "",
                                      "tool_calls": [{"call_id": "one", "name": "search_products",
                                                      "arguments": {"term": "大豆", "flow": "import"}}]}],
                           tools=[])
        self.assertEqual(fake.payloads, [])

    def test_product_model_selection_is_scoped_to_deepseek_thinking(self):
        deepseek = OpenAICompatibleConfig("https://api.deepseek.com", "deepseek-flash")
        self.assertIsInstance(create_trade_agent_model(
            deepseek, {"thinking": {"type": "enabled"}}), DeepSeekThinkingToolModel)
        self.assertNotIsInstance(create_trade_agent_model(
            deepseek, {"thinking": {"type": "disabled"}}), DeepSeekThinkingToolModel)
        another = OpenAICompatibleConfig("https://example.test/v1", "other-model")
        self.assertNotIsInstance(create_trade_agent_model(
            another, {"thinking": {"type": "enabled"}}), DeepSeekThinkingToolModel)

    def test_full_adapter_tool_loop_and_single_use_private_audit(self):
        fake = FakeToolHTTP()
        result = pilot.run_live({"snapshot_sha256": "fixture"}, self.model(fake))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(fake.payloads), 3)
        self.assertEqual(fake.payloads[0]["tool_choice"], "auto")
        self.assertEqual(len(fake.payloads[0]["tools"]), 6)
        ledger = json.loads((pilot.LEDGER_DIR / "first-question.json").read_text())
        responses = [item for item in ledger["events"] if item["type"] == "response_saved"]
        self.assertEqual([item["tool_calls"][0]["name"] for item in responses],
                         ["search_products", "query_trade", "finish"])
        self.assertEqual(responses[1]["tool_calls"][0]["arguments"]["candidate_id"], "import:1201")
        self.assertEqual(responses[0]["metadata"]["usage"]["total_tokens"], 15)
        self.assertNotIn("test-secret", json.dumps(ledger))
        with self.assertRaisesRegex(ValueError, "已有账本"):
            pilot.run_live({"snapshot_sha256": "fixture"}, self.model(fake))
        self.assertEqual(len(fake.payloads), 3)

    def test_timeout_keeps_reserved_ledger_and_never_retries(self):
        fake = FakeToolHTTP(fail_after_first=True)
        result = pilot.run_live({"snapshot_sha256": "fixture"}, self.model(fake))
        self.assertEqual(result["status"], "unknown_outcome")
        ledger = json.loads((pilot.LEDGER_DIR / "first-question.json").read_text())
        self.assertEqual([item["type"] for item in ledger["events"]],
                         ["request_started", "agent_finished"])
        with self.assertRaisesRegex(ValueError, "已有账本"):
            pilot.run_live({"snapshot_sha256": "fixture"}, self.model(fake))
        self.assertEqual(len(fake.payloads), 1)


if __name__ == "__main__":
    unittest.main()
