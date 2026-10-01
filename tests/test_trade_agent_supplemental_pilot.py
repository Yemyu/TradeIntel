"""Offline checks for raw-soy aliases, the lean finish contract and case ledgers."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_trade_agent_supplemental_pilot as pilot
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.trade_agent import TOOL_SCHEMAS
from tradeintel_ai.trade_agent_deepseek import DeepSeekThinkingToolModel
from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_data_repository import TradeDataError
from tradeintel_ai.trade_agent import read_public_session
from tradeintel_ai.trade_report_store import get_state


class FakeHTTP:
    def __init__(self, case, *, timeout=False):
        self.case, self.timeout, self.payloads = case, timeout, []

    def __call__(self, request, *, timeout):
        payload = json.loads(request.data)
        self.payloads.append(payload)
        if self.timeout:
            raise TimeoutError("synthetic unknown outcome")
        last = payload["messages"][-1]
        if last["role"] == "user":
            name, args = "search_products", {"term": "豆油" if self.case == "soybean-oil" else "soybean",
                                               "flow": "import"}
        else:
            result = json.loads(last["content"])
            if "candidates" in result:
                name, args = "query_trade", {"candidate_id": result["candidates"][0]["id"],
                    "flow": "import", "partner": "all",
                    "period": {"type": "latest_contiguous", "count": 2}}
            else:
                name, args = "finish", {"report_ids": [result["report_id"]], "source_ids": []}
        response = {"id": f"fake-{len(self.payloads)}", "model": "deepseek-flash",
            "choices": [{"finish_reason": "tool_calls", "message": {
                "content": None, "reasoning_content": "private",
                "tool_calls": [{"id": f"call-{len(self.payloads)}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        return io.BytesIO(json.dumps(response, ensure_ascii=False).encode())


@unittest.skipUnless(pilot.DATA_ROOT.is_dir(), "verified local data bundle not installed")
class SupplementalTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.addCleanup(patch.stopall)
        patch.object(pilot, "ROOT", self.root).start()
        patch.object(pilot, "LEDGER_DIR", self.root / ".local/trade-agent-live-pilot/supplemental-boundaries-20260930-v1").start()

    def test_raw_soy_aliases_keep_derivatives_related_in_every_direction(self):
        tools = TradeAgentTools(pilot.DATA_ROOT, self.root, question="最近美国大豆贸易如何？")
        for flow in ("import", "export", "both"):
            for term in ("soybean", "soybeans", "soya bean", "soya beans", "  SOYBEAN  "):
                with self.subTest(flow=flow, term=term):
                    found = tools.search_products(term, flow)["candidates"]
                    self.assertEqual([x["id"] for x in found if x["match_type"] == "exact_product"],
                                     [f"{flow}:1201"])
            found = tools.search_products("soybean", flow)["candidates"]
            self.assertTrue(any(x["code"] == "1507" for x in found))
            for code in ("1507", "2304"):
                with self.assertRaises(TradeDataError):
                    tools.query_trade(f"{flow}:{code}", flow, "all", {"type": "latest_contiguous", "count": 2})
        for term, code in (("soybean oil", "1507"), ("豆油", "1507"),
                           ("soybean meal", "2304"), ("豆粕", "2304")):
            self.assertEqual(tools.search_products(term, "import")["candidates"][0]["id"],
                             f"import:{code}")

    def test_finish_schema_only_requests_reference_fields(self):
        finish = next(x for x in TOOL_SCHEMAS if x["name"] == "finish")["parameters"]
        self.assertEqual(set(finish["properties"]), {"report_ids", "source_ids"})
        self.assertEqual(set(finish["required"]), {"report_ids", "source_ids"})
        self.assertFalse(finish["additionalProperties"])

    @staticmethod
    def model(fake):
        return DeepSeekThinkingToolModel(OpenAICompatibleConfig(
            "https://api.deepseek.com", "deepseek-flash", api_key="test-secret", temperature=0.0),
            system_prompt="", opener=fake,
            request_params={"max_tokens": 4096, "thinking": {"type": "enabled"}, "reasoning_effort": "high"})

    def run_fake(self, case, *, timeout=False):
        snapshot, _ = pilot.preflight(case)
        fake = FakeHTTP(case, timeout=timeout)
        model = self.model(fake)
        with patch.object(pilot, "preflight", return_value=(snapshot, model)):
            result = pilot.run_live(case, snapshot, model)
            with self.assertRaisesRegex(ValueError, "已有账本"):
                pilot.run_live(case, snapshot, model)
        self.assertEqual(pilot.first._sha(pilot.first._json_bytes(fake.payloads[0])),
                         snapshot["request_payload_sha256"])
        ledger = json.loads((pilot.LEDGER_DIR / f"{case}.json").read_text())
        self.assertNotIn("test-secret", json.dumps(ledger))
        self.assertNotIn("reasoning_content", json.dumps(ledger))
        return result, fake

    def test_oil_completes_using_new_finish_and_correct_data(self):
        result, fake = self.run_fake("soybean-oil")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(fake.payloads), 3)
        report = get_state(self.root, result["report_ids"][0])
        self.assertEqual(report["scope"]["product_code"], "1507")
        self.assertEqual(report["summary"]["latest_value_usd"], 27_503_913)
        self.assertEqual(report["summary"]["month_change_usd"], -3_340_380)

    def test_missing_month_cannot_be_changed_by_model_to_latest(self):
        result, fake = self.run_fake("missing-last-month")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(len(fake.payloads), 2)
        state = read_public_session(self.root, result["session_id"])
        self.assertEqual(state["turns"][-1]["report_ids"], [])
        self.assertIn("2026-08", state["turns"][-1]["message"])
        self.assertIn("2026-07", state["turns"][-1]["message"])

    def test_timeout_preserves_one_attempt(self):
        result, fake = self.run_fake("soybean-oil", timeout=True)
        self.assertEqual(result["status"], "unknown_outcome")
        self.assertEqual(len(fake.payloads), 1)

    def test_snapshot_change_stops_before_any_send(self):
        snapshot, _ = pilot.preflight("soybean-oil")
        fake = FakeHTTP("soybean-oil")
        with patch.object(pilot, "preflight", return_value=(snapshot, self.model(fake))):
            with self.assertRaisesRegex(ValueError, "快照已变化"):
                pilot.run_live("soybean-oil", {**snapshot, "snapshot_sha256": "changed"}, self.model(fake))
        self.assertEqual(fake.payloads, [])
        self.assertFalse(pilot._path("soybean-oil").exists())


if __name__ == "__main__":
    unittest.main()
