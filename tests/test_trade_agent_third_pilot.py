"""Third development question: offline contract and one-use gate tests."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_trade_agent_third_pilot as third
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.trade_agent_deepseek import DeepSeekThinkingToolModel


class FakeBothHTTP:
    def __init__(self, *, timeout=False):
        self.payloads = []
        self.timeout = timeout

    def __call__(self, request, *, timeout):
        payload = json.loads(request.data)
        self.payloads.append(payload)
        if self.timeout:
            raise TimeoutError("synthetic unknown outcome")
        last = payload["messages"][-1]
        if last["role"] == "user":
            self_question = third.QUESTION
            if self_question not in last["content"]:
                raise AssertionError("third question changed")
            name, arguments = "search_products", {"term": "大豆", "flow": "both"}
        else:
            result = json.loads(last["content"])
            if "candidates" in result:
                name, arguments = "query_trade", {
                    "candidate_id": result["candidates"][0]["id"], "flow": "both",
                    "partner": "all", "period": {"type": "latest_contiguous", "count": 2}}
            elif "report_id" in result:
                self.report_id = result["report_id"]
                name, arguments = "search_policy", {"query": "美国大豆贸易政策效果"}
            else:
                name, arguments = "finish", {"report_ids": [self.report_id],
                                               "explanation": "政策已经奏效。", "source_ids": []}
        answer = {"id": f"fake-{len(self.payloads)}", "model": "deepseek-flash",
                  "choices": [{"finish_reason": "tool_calls", "message": {
                      "content": None, "reasoning_content": f"private-{len(self.payloads)}",
                      "tool_calls": [{"id": f"call-{len(self.payloads)}", "type": "function",
                                      "function": {"name": name,
                                                   "arguments": json.dumps(arguments, ensure_ascii=False)}}]}}],
                  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        return io.BytesIO(json.dumps(answer, ensure_ascii=False).encode())


@unittest.skipUnless(third.DATA_ROOT.is_dir(), "verified local data bundle not installed")
class ThirdPilotTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.addCleanup(patch.stopall)
        patch.object(third, "ROOT", self.root).start()
        patch.object(third, "LEDGER_DIR", self.root / ".local/trade-agent-live-pilot/20260929-v1").start()

    @staticmethod
    def model(fake):
        return DeepSeekThinkingToolModel(OpenAICompatibleConfig(
            "https://api.deepseek.com", "deepseek-flash", api_key="test-secret",
            timeout_seconds=2, temperature=0.0), system_prompt="", opener=fake,
            request_params={"max_tokens": 4096, "thinking": {"type": "enabled"},
                            "reasoning_effort": "high"})

    def test_reference_and_real_preflight_are_offline(self):
        # The installed development data is checked, but no provider is contacted.
        with patch.object(third, "ROOT", third.first.ROOT), patch.object(
                third, "LEDGER_DIR", third.first.LEDGER_DIR):
            snapshot, _ = third.preflight()
        self.assertEqual(snapshot["question"], third.QUESTION)
        self.assertEqual(snapshot["model"], "deepseek-flash")
        self.assertEqual(snapshot["reasoning"], "high")
        self.assertLessEqual(snapshot["request_payload_bytes"], 16_000)
        self.assertEqual(len(snapshot["source_sha256"]), 17)

    def test_both_directions_and_policy_limit_without_publishing_model_claim(self):
        fake = FakeBothHTTP()
        model = self.model(fake)
        snapshot, _ = third.preflight()
        patch.object(third, "preflight", return_value=(snapshot, model)).start()
        result = third.run_live(snapshot, model)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(fake.payloads), 4)
        self.assertEqual(third.first._sha(third.first._json_bytes(fake.payloads[0])),
                         snapshot["request_payload_sha256"])
        self.assertEqual(len(result["report_ids"]), 1)
        from tradeintel_ai.trade_agent_store import read_session
        from tradeintel_ai.trade_agent import read_public_session
        from tradeintel_ai.trade_report_store import get_state
        saved = read_session(self.root, result["session_id"])
        public = read_public_session(self.root, result["session_id"])
        report = get_state(self.root, result["report_ids"][0])
        self.assertEqual(report["scope"]["flow"], "both")
        self.assertEqual(report["import_report"]["summary"]["latest_value_usd"], 46_041_287)
        self.assertEqual(report["export_report"]["summary"]["latest_value_usd"], 889_379_312)
        self.assertNotIn("政策已经奏效", public["turns"][0]["message"])
        self.assertIn("不能判断政策效果", public["turns"][0]["message"])
        self.assertEqual(saved["turns"][0]["status"], "completed")
        ledger = json.loads((third.LEDGER_DIR / "third-question.json").read_text())
        self.assertEqual(ledger["status"], "completed")
        self.assertNotIn("test-secret", json.dumps(ledger))
        self.assertNotIn("private-", json.dumps(ledger))
        with self.assertRaisesRegex(ValueError, "已有账本"):
            third.run_live(snapshot, model)
        self.assertEqual(len(fake.payloads), 4)

    def test_unknown_outcome_is_not_retried(self):
        fake = FakeBothHTTP(timeout=True)
        model = self.model(fake)
        snapshot = {"snapshot_sha256": "s"}
        patch.object(third, "preflight", return_value=(snapshot, model)).start()
        result = third.run_live(snapshot, model)
        self.assertEqual(result["status"], "unknown_outcome")
        self.assertEqual(len(fake.payloads), 1)
        with self.assertRaisesRegex(ValueError, "已有账本"):
            third.run_live(snapshot, model)

    def test_changed_snapshot_rejects_before_ledger_and_model(self):
        fake = FakeBothHTTP()
        model = self.model(fake)
        snapshot = {"snapshot_sha256": "s"}
        patch.object(third, "preflight", return_value=(snapshot, model)).start()
        with self.assertRaisesRegex(ValueError, "快照已变化"):
            third.run_live({"snapshot_sha256": "different"}, model)
        self.assertFalse((third.LEDGER_DIR / "third-question.json").exists())
        self.assertEqual(fake.payloads, [])


if __name__ == "__main__":
    unittest.main()
