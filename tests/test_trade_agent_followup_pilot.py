"""Offline tests for the independent, single-use second-question gate."""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from scripts import run_trade_agent_followup_pilot as followup
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.trade_agent import TOOL_SCHEMAS, initial_messages
from tradeintel_ai.trade_agent_deepseek import DeepSeekThinkingToolModel
from tradeintel_ai.trade_agent_store import begin_turn, finish_turn, read_session


class FakeExportHTTP:
    def __init__(self, *, timeout: bool = False):
        self.payloads = []
        self.timeout = timeout

    def __call__(self, request, *, timeout):
        payload = json.loads(request.data)
        self.payloads.append(payload)
        if self.timeout:
            raise TimeoutError("synthetic unknown outcome")
        assistant = [item for item in payload["messages"] if item["role"] == "assistant"]
        for index, item in enumerate(assistant):
            if item.get("reasoning_content") != f"private-{index + 1}":
                raise AssertionError("thinking content was not replayed")
        last = payload["messages"][-1]
        if last["role"] == "user":
            if "此前用户问题" not in last["content"] or followup.FIRST_QUESTION not in last["content"]:
                raise AssertionError("follow-up lost the first question")
            name, arguments = "search_products", {"term": "大豆", "flow": "export"}
        elif "candidates" in (result := json.loads(last["content"])):
            name, arguments = "query_trade", {"candidate_id": result["candidates"][0]["id"],
                                                "flow": "export", "partner": "all",
                                                "period": {"type": "latest_contiguous", "count": 2}}
        else:
            name, arguments = "finish", {"report_ids": [result["report_id"]],
                                          "explanation": "7月出口额较6月减少。", "source_ids": []}
        message = {"content": None, "reasoning_content": f"private-{len(self.payloads)}",
                   "tool_calls": [{"id": f"call-{len(self.payloads)}", "type": "function",
                                   "function": {"name": name,
                                                "arguments": json.dumps(arguments, ensure_ascii=False)}}]}
        response = {"id": f"fake-{len(self.payloads)}", "model": "deepseek-flash",
                    "choices": [{"finish_reason": "tool_calls", "message": message}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        return io.BytesIO(json.dumps(response, ensure_ascii=False).encode())


@unittest.skipUnless(followup.DATA_ROOT.is_dir(), "verified local data bundle not installed")
class FollowupPilotTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.addCleanup(patch.stopall)
        patch.object(followup, "ROOT", self.root).start()
        patch.object(followup, "LEDGER_DIR", self.root / ".local/trade-agent-live-pilot/20260929-v1").start()
        self.session_id = uuid.uuid4().hex
        begin_turn(self.root, None, self.session_id, followup.FIRST_QUESTION)
        finish_turn(self.root, self.session_id, self.session_id,
                    {"status": "completed", "message": "已查大豆进口", "report_ids": [uuid.uuid4().hex]},
                    {"product_code": "1201", "product_label": "大豆", "flow": "import"})

    def model(self, fake):
        return DeepSeekThinkingToolModel(OpenAICompatibleConfig(
            "https://api.deepseek.com", "deepseek-flash", api_key="test-secret",
            timeout_seconds=2, temperature=0), system_prompt="", opener=fake,
            request_params={"max_tokens": 4096, "thinking": {"type": "enabled"},
                            "reasoning_effort": "high"})

    def _snapshot(self, model):
        state = read_session(self.root, self.session_id)
        pending = copy.deepcopy(state)
        pending["turns"].append({"question": followup.QUESTION, "status": "in_progress"})
        payload = model._payload(messages=initial_messages(followup.QUESTION, pending, followup.first.AS_OF),
                                 tools=TOOL_SCHEMAS)
        return {"first_session_id": self.session_id,
                "request_payload_sha256": followup.first._sha(followup.first._json_bytes(payload))}

    def test_followup_uses_same_first_request_as_preflight_and_cannot_repeat(self):
        fake = FakeExportHTTP()
        model = self.model(fake)
        snapshot = self._snapshot(model)
        patch.object(followup, "preflight", return_value=(snapshot, model)).start()
        result = followup.run_live(snapshot, model)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["session_id"], self.session_id)
        self.assertEqual(len(fake.payloads), 3)
        self.assertEqual(followup.first._sha(followup.first._json_bytes(fake.payloads[0])),
                         snapshot["request_payload_sha256"])
        ledger = json.loads((followup.LEDGER_DIR / "second-question.json").read_text())
        self.assertEqual(ledger["status"], "completed")
        self.assertNotIn("private-", json.dumps(ledger))
        self.assertNotIn("test-secret", json.dumps(ledger))
        self.assertEqual([turn["question"] for turn in read_session(self.root, self.session_id)["turns"]],
                         [followup.FIRST_QUESTION, followup.QUESTION])
        with self.assertRaisesRegex(ValueError, "已有账本"):
            followup.run_live(snapshot, model)
        self.assertEqual(len(fake.payloads), 3)

    def test_unknown_outcome_keeps_second_ledger_and_does_not_retry(self):
        fake = FakeExportHTTP(timeout=True)
        model = self.model(fake)
        snapshot = self._snapshot(model)
        patch.object(followup, "preflight", return_value=(snapshot, model)).start()
        result = followup.run_live(snapshot, model)
        self.assertEqual(result["status"], "unknown_outcome")
        self.assertEqual(len(fake.payloads), 1)
        self.assertEqual(json.loads((followup.LEDGER_DIR / "second-question.json").read_text())["status"],
                         "unknown_outcome")
        with self.assertRaisesRegex(ValueError, "已有账本"):
            followup.run_live(snapshot, model)

    def test_changed_snapshot_rejects_before_creating_ledger(self):
        fake = FakeExportHTTP()
        model = self.model(fake)
        snapshot = self._snapshot(model)
        patch.object(followup, "preflight", return_value=(snapshot, model)).start()
        with self.assertRaisesRegex(ValueError, "快照已变化"):
            followup.run_live({**snapshot, "request_payload_sha256": "0" * 64}, model)
        self.assertFalse((followup.LEDGER_DIR / "second-question.json").exists())
        self.assertEqual(fake.payloads, [])


if __name__ == "__main__":
    unittest.main()
