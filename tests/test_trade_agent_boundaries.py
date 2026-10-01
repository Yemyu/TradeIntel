"""Offline regressions for calendar wording and public agent explanations."""
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from tradeintel_ai.agent import ModelResponse, ModelToolCall
from tradeintel_ai.trade_agent import TradeResearchAgent
from tradeintel_ai.trade_agent_store import begin_turn, finish_turn, read_session
from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.web_app import create_server


DATA_ROOT = Path(__file__).resolve().parents[1] / "tmp/handoff-runs/trade-demo-data-20260925"


class BoundaryModel:
    def __init__(self, period: dict, explanation: str = "这证明政策已经奏效。"):
        self.period = period
        self.explanation = explanation
        self.calls = 0

    def complete(self, *, messages, tools):
        self.calls += 1
        previous = messages[-1]
        if previous["role"] == "user":
            return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "search_products",
                {"term": "大豆", "flow": "import"}),))
        result = json.loads(previous["content"])
        if previous["name"] == "search_products":
            return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "query_trade",
                {"candidate_id": result["candidates"][0]["id"], "flow": "import",
                 "partner": "all", "period": self.period}),))
        if previous["name"] == "query_trade":
            return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "finish",
                {"report_ids": [result["report_id"]], "explanation": self.explanation,
                 "source_ids": []}),))
        raise AssertionError(f"unexpected tool {previous['name']}")


@unittest.skipUnless(DATA_ROOT.is_dir(), "verified local data bundle not installed")
class TradeAgentBoundaryTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)

    def test_last_month_cannot_be_silently_changed_to_latest_available(self):
        model = BoundaryModel({"type": "latest_contiguous"})
        result = TradeResearchAgent(DATA_ROOT, self.root, model, today=date(2026, 9, 29)).turn(
            "上个月美国大豆进口额是多少？", uuid.uuid4().hex)
        turn = result["turns"][-1]
        self.assertEqual(turn["status"], "needs_clarification")
        self.assertIn("2026-08", turn["message"])
        self.assertIn("2026-07", turn["message"])
        self.assertEqual(turn["report_ids"], [])
        self.assertEqual(model.calls, 2)

    def test_correct_calendar_relative_request_still_reports_missing_month(self):
        model = BoundaryModel({"type": "calendar_relative", "unit": "month", "offset": -1})
        result = TradeResearchAgent(DATA_ROOT, self.root, model, today=date(2026, 9, 29)).turn(
            "上月美国大豆进口额是多少？", uuid.uuid4().hex)
        self.assertEqual(result["turns"][-1]["status"], "needs_clarification")
        self.assertEqual(result["turns"][-1]["report_ids"], [])
        self.assertEqual(model.calls, 2)

    def test_available_last_month_is_one_month_and_recent_keeps_long_range(self):
        single = BoundaryModel({"type": "latest_contiguous", "count": 1}, "请查看数据。")
        result = TradeResearchAgent(DATA_ROOT, self.root, single, today=date(2026, 8, 29)).turn(
            "上个月美国大豆进口额是多少？", uuid.uuid4().hex)
        self.assertEqual(result["turns"][-1]["status"], "completed")
        self.assertEqual((result["scope"]["start_month"], result["scope"]["end_month"]),
                         ("2026-07", "2026-07"))
        recent = BoundaryModel({"type": "latest_contiguous", "count": 12}, "请查看数据。")
        result = TradeResearchAgent(DATA_ROOT, self.root, recent, today=date(2026, 9, 29)).turn(
            "最近美国大豆进口有什么变化？", uuid.uuid4().hex)
        self.assertEqual(result["turns"][-1]["status"], "completed")
        self.assertEqual(result["scope"]["end_month"], "2026-07")
        self.assertNotEqual(result["scope"]["start_month"], "2026-07")

    def test_comparison_and_negated_last_month_are_not_forced_to_one_month(self):
        tool = TradeAgentTools(DATA_ROOT, self.root, today=date(2026, 8, 29),
                               question="上个月以来美国大豆进口额怎么变？")
        tool.search_products("大豆", "import")
        result = tool.query_trade("import:1201", "import", "all",
                                  {"type": "latest_contiguous", "count": 2})
        self.assertEqual(result["period"], {"start": "2026-06", "end": "2026-07",
                                             "latest_available": "2026-07"})
        negated = TradeAgentTools(DATA_ROOT, self.root, today=date(2026, 9, 29),
                                  question="不是上月，查最新可用月的美国大豆进口额")
        negated.search_products("大豆", "import")
        self.assertEqual(negated.query_trade("import:1201", "import", "all",
                         {"type": "latest_contiguous", "count": 1})["period"]["end"], "2026-07")

    def test_model_policy_effect_claim_is_never_public_completion(self):
        model = BoundaryModel({"type": "latest_contiguous", "count": 2})
        agent = TradeResearchAgent(DATA_ROOT, self.root, model, today=date(2026, 9, 29))
        request_id = uuid.uuid4().hex
        result = agent.turn("最近美国大豆进口有什么变化？", request_id)
        turn = result["turns"][-1]
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(turn["message_kind"], "program_summary_v1")
        self.assertIn("46,041,287", turn["message"])
        self.assertIn("不能判断政策效果", turn["message"])
        self.assertNotIn("政策已经奏效", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("政策已经奏效", json.dumps(read_session(self.root, result["session_id"]),
                                         ensure_ascii=False))
        self.assertNotIn("政策已经奏效", json.dumps(agent.state(result["session_id"]),
                                         ensure_ascii=False))
        self.assertNotIn("政策已经奏效", json.dumps(agent.turn(
            "最近美国大豆进口有什么变化？", request_id), ensure_ascii=False))
        self.assertEqual(model.calls, 3)

    def test_valid_policy_source_id_still_does_not_publish_model_causal_claim(self):
        class PolicyModel(BoundaryModel):
            def complete(self, *, messages, tools):
                previous = messages[-1]
                if previous["role"] == "tool" and previous["name"] == "query_trade":
                    self.calls += 1
                    return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "search_policy",
                        {"query": "大豆政策"}),))
                if previous["role"] == "tool" and previous["name"] == "search_policy":
                    self.calls += 1
                    report = json.loads(messages[-3]["content"])
                    return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "finish",
                        {"report_ids": [report["report_id"]],
                         "explanation": "这证明政策已经奏效。",
                         "source_ids": ["source:test"]}),))
                return super().complete(messages=messages, tools=tools)

        def fake_search_policy(tools, query, candidate_id=None):
            source = {"citation_id": "source:test", "policy_id": "test", "url": "https://example.test/",
                      "text": "Some official policy text."}
            tools.policy_sources[source["citation_id"]] = source
            return {"status": "ok", "hits": [source]}

        model = PolicyModel({"type": "latest_contiguous", "count": 2})
        with patch.object(TradeAgentTools, "search_policy", fake_search_policy):
            result = TradeResearchAgent(DATA_ROOT, self.root, model, today=date(2026, 9, 29)).turn(
                "最近美国大豆进口有什么变化，政策是否奏效？", uuid.uuid4().hex)
        turn = result["turns"][-1]
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(turn["policy_source_ids"], ["source:test"])
        self.assertNotIn("政策已经奏效", json.dumps(result, ensure_ascii=False))
        self.assertIn("不能判断政策效果", turn["message"])

    def test_comparison_requires_at_least_one_report_covering_requested_month(self):
        tool = TradeAgentTools(DATA_ROOT, self.root, today=date(2026, 8, 29),
                               question="上月相比前月，美国大豆进口额有什么变化？")
        tool.search_products("大豆", "import")
        previous = tool.query_trade("import:1201", "import", "all",
                                    {"type": "absolute", "start": "2026-06", "end": "2026-06"})
        with self.assertRaisesRegex(ValueError, "没有回答用户指定的日历上月"):
            tool.validate_finish_period([previous["report_id"]])
        current = tool.query_trade("import:1201", "import", "all",
                                   {"type": "absolute", "start": "2026-07", "end": "2026-07"})
        tool.validate_finish_period([previous["report_id"], current["report_id"]])

    def test_old_saved_free_text_is_hidden_on_all_public_read_paths(self):
        request_id = uuid.uuid4().hex
        state, _ = begin_turn(self.root, None, request_id, "美国大豆进口变化？")
        old = finish_turn(self.root, state["session_id"], request_id,
                          {"status": "completed", "message": "这证明政策已经奏效。",
                           "report_ids": [uuid.uuid4().hex]})
        self.assertIn("政策已经奏效", old["turns"][-1]["message"])
        self.assertNotIn("政策已经奏效", json.dumps(
            TradeResearchAgent(DATA_ROOT, self.root, BoundaryModel({})).state(state["session_id"]),
            ensure_ascii=False))
        server = create_server(root=self.root, trade_data_root=DATA_ROOT,
                               host="127.0.0.1", port=0)
        from threading import Thread
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/trade/agent/state?"
                     f"session_id={state['session_id']}") as response:
            public = json.load(response)
        self.assertEqual(public["turns"][-1]["message_kind"], "legacy_unreviewed_hidden")
        self.assertNotIn("政策已经奏效", json.dumps(public, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
