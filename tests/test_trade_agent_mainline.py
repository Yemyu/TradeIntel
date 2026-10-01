"""The real data tools and HTTP path, with a scripted model (no API request)."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from tradeintel_ai.agent import ModelResponse, ModelToolCall
from tradeintel_ai.trade_agent import TradeResearchAgent
from tradeintel_ai.trade_agent_store import begin_turn, finish_turn, read_session
from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_report_store import get_state
from tradeintel_ai.web_app import create_server
from tradeintel_ai.model_adapter import OpenAICompatibleConfig, ModelAdapterError


DATA_ROOT = Path(__file__).resolve().parents[1] / "tmp/handoff-runs/trade-demo-data-20260925"


class ScriptedModel:
    """Choose tools by prior tool result; records calls, does not emulate model quality."""

    def __init__(self):
        self.calls = 0

    def complete(self, *, messages, tools):
        self.calls += 1
        current = messages[1]["content"].rsplit("本轮用户问题：", 1)[-1]
        flow = ("export" if "出口呢" in current else
                "both" if "大豆贸易" in current else "import")
        if messages[-1]["role"] == "user":
            return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "search_products",
                                                           {"term": "大豆", "flow": flow}),))
        previous = json.loads(messages[-1]["content"])
        if messages[-1]["name"] == "search_products":
            return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "query_trade",
                {"candidate_id": previous["candidates"][0]["id"], "flow": flow,
                 "partner": "all", "period": {"type": "latest_contiguous"}}),))
        if messages[-1]["name"] == "query_trade":
            return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "finish",
                {"report_ids": [previous["report_id"]], "explanation": "请查看已发布数据图表。",
                 "source_ids": []}),))
        raise AssertionError("unexpected tool stage")


class TwoDestinationModel:
    """Reproduce the saved second-question tool order without calling a provider."""

    def complete(self, *, messages, tools):
        previous = messages[-1]
        if previous["role"] == "user":
            name, args = "search_products", {"term": "大豆", "flow": "export"}
        elif previous["name"] == "search_products":
            candidate = json.loads(previous["content"])["candidates"][0]["id"]
            name, args = "query_trade", {"candidate_id": candidate, "flow": "export",
                                         "partner": "all", "period": {"type": "latest_contiguous"}}
        elif previous["name"] == "query_trade":
            reports = [json.loads(item["content"])["report_id"] for item in messages
                       if item["role"] == "tool" and item["name"] == "query_trade"]
            if len(reports) == 1:
                name, args = "query_trade", {"candidate_id": "export:1201", "flow": "export",
                                             "partner": "china", "period": {"type": "latest_contiguous"}}
            else:
                name, args = "finish", {"report_ids": reports,
                                        "explanation": "未经核对的模型文字", "source_ids": []}
        else:
            raise AssertionError("unexpected tool stage")
        return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, name, args),))


@unittest.skipUnless(DATA_ROOT.is_dir(), "local verified data bundle not installed")
class TradeAgentMainlineTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.code_root = Path(holder.name)
        self.model = ScriptedModel()

    def test_import_then_export_followup_and_idempotent_replay(self):
        agent = TradeResearchAgent(DATA_ROOT, self.code_root, self.model, today=date(2026, 9, 29))
        first_id = uuid.uuid4().hex
        first = agent.turn("最近美国大豆进口有什么变化？", first_id)
        self.assertEqual(first["turns"][-1]["status"], "completed")
        rid = first["turns"][-1]["report_ids"][0]
        self.assertEqual(get_state(self.code_root, rid)["summary"]["latest_value_usd"], 46_041_287)
        self.assertEqual([row["tool"] for row in first["turns"][-1]["tool_calls"]],
                         ["search_products", "query_trade", "finish"])
        again = agent.turn("最近美国大豆进口有什么变化？", first_id)
        self.assertEqual(again["turns"][-1]["report_ids"], [rid])
        self.assertEqual(self.model.calls, 3)
        second = agent.turn("出口呢？", uuid.uuid4().hex, first["session_id"])
        other = get_state(self.code_root, second["turns"][-1]["report_ids"][0])
        self.assertEqual((other["scope"]["flow"], other["scope"]["product_code"],
                          other["summary"]["latest_value_usd"]), ("export", "1201", 889_379_312))
        self.assertEqual(len(read_session(self.code_root, first["session_id"])["turns"]), 2)
        self.assertIn("total exports (FAS) to all destinations were 889,379,312 USD",
                      second["turns"][-1]["message_en"])
        self.assertNotIn("message_en", read_session(self.code_root, first["session_id"])["turns"][-1])

    def test_unsolicited_china_report_is_labeled_but_does_not_replace_main_scope(self):
        first = TradeResearchAgent(DATA_ROOT, self.code_root, self.model).turn(
            "最近美国大豆进口有什么变化？", uuid.uuid4().hex)
        agent = TradeResearchAgent(DATA_ROOT, self.code_root, TwoDestinationModel())
        second = agent.turn("出口呢？", uuid.uuid4().hex, first["session_id"])
        turn = second["turns"][-1]
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(second["scope"]["partner"], "ALL_DESTINATIONS")
        self.assertEqual(turn["primary_report_id"], turn["report_ids"][0])
        self.assertEqual(len(turn["report_options"]), 2)
        self.assertIn("（全部目的地）出口 FAS 总额为 889,379,312", turn["message"])
        self.assertIn("（中国目的地）出口 FAS 总额为 141,197,240", turn["message"])
        self.assertNotIn("未经核对的模型文字", turn["message"])
        self.assertEqual(agent.state(first["session_id"])["scope"]["partner"], "ALL_DESTINATIONS")

    def test_explicit_china_can_be_primary_even_when_both_reports_exist(self):
        first = TradeResearchAgent(DATA_ROOT, self.code_root, self.model).turn(
            "最近美国大豆进口有什么变化？", uuid.uuid4().hex)
        agent = TradeResearchAgent(DATA_ROOT, self.code_root, TwoDestinationModel())
        second = agent.turn("出口到中国呢？", uuid.uuid4().hex, first["session_id"])
        self.assertEqual(second["scope"]["partner"], "CHINA")
        self.assertEqual(second["turns"][-1]["primary_report_id"], second["turns"][-1]["report_ids"][-1])

    def test_old_multi_report_session_is_projected_safely_without_rewriting_audit(self):
        first_id = uuid.uuid4().hex
        first_state, _ = begin_turn(self.code_root, None, first_id, "最近美国大豆进口有什么变化？")
        first_tools = TradeAgentTools(DATA_ROOT, self.code_root, question="大豆进口")
        first_tools.search_products("大豆", "import")
        import_id = first_tools.query_trade("import:1201", "import", "all",
                                            {"type": "latest_contiguous"})["report_id"]
        finish_turn(self.code_root, first_state["session_id"], first_id,
                    {"status": "completed", "message": "旧版模型文字", "report_ids": [import_id]},
                    first_tools.reports[import_id]["scope"])
        second_id = uuid.uuid4().hex
        begin_turn(self.code_root, first_state["session_id"], second_id, "出口呢？")
        export_tools = TradeAgentTools(DATA_ROOT, self.code_root, question="出口呢？")
        export_tools.search_products("大豆", "export")
        all_id = export_tools.query_trade("export:1201", "export", "all",
                                          {"type": "latest_contiguous"})["report_id"]
        china_id = export_tools.query_trade("export:1201", "export", "china",
                                            {"type": "latest_contiguous"})["report_id"]
        old = finish_turn(self.code_root, first_state["session_id"], second_id,
                          {"status": "completed", "message": "旧摘要未标目的地",
                           "message_kind": "program_summary_v1", "report_ids": [all_id, china_id]},
                          export_tools.reports[china_id]["scope"])
        self.assertEqual(old["scope"]["partner"], "CHINA")
        agent = TradeResearchAgent(DATA_ROOT, self.code_root, self.model)
        public = agent.state(first_state["session_id"])
        self.assertEqual(public["scope"]["partner"], "ALL_DESTINATIONS")
        self.assertEqual(public["turns"][-1]["primary_report_id"], all_id)
        self.assertIn("全部目的地", public["turns"][-1]["message"])
        self.assertIn("中国目的地", public["turns"][-1]["message"])
        self.assertNotIn("旧摘要未标目的地", public["turns"][-1]["message"])
        self.assertEqual(read_session(self.code_root, first_state["session_id"]), old)
        server = create_server(root=self.code_root, trade_data_root=DATA_ROOT,
                               host="127.0.0.1", port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/trade/agent/state?"
                     f"session_id={first_state['session_id']}") as response:
            from_http = json.load(response)
        self.assertEqual(from_http["scope"]["partner"], "ALL_DESTINATIONS")
        self.assertEqual(from_http["turns"][-1]["primary_report_id"], all_id)

        class InspectNextTurn:
            def complete(self, *, messages, tools):
                self_outer.assertIn("伙伴范围：ALL_DESTINATIONS", messages[1]["content"])
                return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "ask_user",
                    {"question": "接下来想看哪个月份？", "choices": ["最近月"]}),))

        self_outer = self
        next_turn = TradeResearchAgent(DATA_ROOT, self.code_root, InspectNextTurn()).turn(
            "接着看呢？", uuid.uuid4().hex, first_state["session_id"])
        self.assertEqual(next_turn["turns"][-1]["status"], "needs_clarification")
        self.assertEqual(next_turn["scope"]["partner"], "ALL_DESTINATIONS")

    def test_broad_trade_question_keeps_two_measurements_separate(self):
        agent = TradeResearchAgent(DATA_ROOT, self.code_root, self.model)
        result = agent.turn("最近美国大豆贸易怎么样？", uuid.uuid4().hex)
        report = get_state(self.code_root, result["turns"][-1]["report_ids"][0])
        self.assertEqual(report["kind"], "trade-query-both-v1")
        self.assertEqual(report["import_report"]["summary"]["latest_value_usd"], 46_041_287)
        self.assertEqual(report["export_report"]["summary"]["latest_value_usd"], 889_379_312)

    def test_http_turn_and_reload(self):
        server = create_server(root=self.code_root, trade_data_root=DATA_ROOT,
                               host="127.0.0.1", port=0,
                               trade_model_factory=lambda _config, _params: self.model)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        question = "最近美国大豆进口有什么变化？"
        request_id = uuid.uuid4().hex
        payload = json.dumps({"question": question, "request_id": request_id}).encode()
        request = Request(base + "/api/trade/agent/turn", payload,
                          {"Content-Type": "application/json"})
        with urlopen(request) as response:
            result = json.load(response)
        self.assertEqual(result["turns"][0]["status"], "completed")
        with urlopen(base + "/api/trade/agent/state?session_id=" + result["session_id"]) as response:
            restored = json.load(response)
        self.assertEqual(restored["turns"][0]["report_ids"], result["turns"][0]["report_ids"])
        with urlopen(request) as response:
            replay = json.load(response)
        self.assertEqual(replay["turns"][0]["report_ids"], restored["turns"][0]["report_ids"])
        self.assertEqual(self.model.calls, 3)

    def test_http_configured_model_branch_builds_adapter_before_querying(self):
        config_file = self.code_root / 'product-model.json'
        config_file.write_text('{}', encoding='utf-8')
        config = OpenAICompatibleConfig(base_url='https://example.invalid',
                                       api_key='offline-test-only', model='offline-model')
        server = create_server(root=self.code_root, trade_data_root=DATA_ROOT,
                               host='127.0.0.1', port=0)  # no factory injection: use the production branch
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        request = Request(f'http://127.0.0.1:{server.server_port}/api/trade/agent/turn',
                          json.dumps({'question':'最近美国大豆进口有什么变化？',
                                      'request_id':uuid.uuid4().hex}).encode(),
                          {'Content-Type':'application/json'})
        with patch('tradeintel_ai.local_provider_config.PRODUCT_CONFIG_PATH', config_file), \
             patch('tradeintel_ai.web_app.load_product_config', return_value=config) as loader, \
             patch('tradeintel_ai.local_provider_config.product_request_params', return_value={}), \
             patch('tradeintel_ai.trade_agent_deepseek.create_trade_agent_model',
                   return_value=self.model) as constructor:
            with urlopen(request, timeout=15) as response:
                result = json.load(response)
        loader.assert_called_once_with()
        constructor.assert_called_once_with(config, {})
        self.assertEqual(result['turns'][-1]['status'], 'completed')
        report = get_state(self.code_root, result['turns'][-1]['report_ids'][0])
        self.assertEqual(report['summary']['latest_value_usd'], 46_041_287)
        self.assertEqual(self.model.calls, 3)

    def test_processed_product_cannot_be_reported_as_raw_soybeans(self):
        tools = TradeAgentTools(DATA_ROOT, self.code_root, question="美国大豆油进口怎么样")
        result = tools.search_products("大豆油", "import")
        self.assertEqual(result["candidates"][0]["id"], "import:1507")
        self.assertEqual(result["candidates"][0]["match_type"], "exact_product")
        self.assertEqual(next(item for item in result["candidates"] if item["id"] == "import:1201")
                         ["match_type"], "related_candidate")
        # Even if a model searches for the shorter term, the query boundary
        # checks the original user question before issuing a report.
        tools.search_products("大豆", "import")
        with self.assertRaisesRegex(ValueError, "相关商品|原问题不一致"):
            tools.query_trade("import:1201", "import", "all", {"type": "latest_contiguous"})

    def test_same_session_switch_to_oil_and_unknown_product(self):
        first = TradeResearchAgent(DATA_ROOT, self.code_root, self.model).turn(
            "最近美国大豆进口有什么变化？", uuid.uuid4().hex)

        class OilModel(ScriptedModel):
            def complete(inner, *, messages, tools):
                inner.calls += 1
                if messages[-1]['role'] == 'user':
                    name, args = 'search_products', {'term':'大豆油','flow':'import'}
                elif messages[-1]['name'] == 'search_products':
                    name, args = 'query_trade', {'candidate_id':'import:1507','flow':'import',
                        'partner':'all','period':{'type':'latest_contiguous'}}
                else:
                    name, args = 'finish', {'report_ids':[json.loads(messages[-1]['content'])['report_id']],
                                           'source_ids':[]}
                return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, name, args),))

        oil = TradeResearchAgent(DATA_ROOT, self.code_root, OilModel()).turn(
            '改看美国大豆油进口', uuid.uuid4().hex, first['session_id'])
        self.assertEqual(oil['turns'][-1]['status'], 'completed')
        self.assertEqual(oil['scope']['product_code'], '1507')
        restored = TradeResearchAgent(DATA_ROOT, self.code_root, self.model).state(first['session_id'])
        self.assertEqual(restored['scope']['product_code'], '1507')
        report = get_state(self.code_root, oil['turns'][-1]['primary_report_id'])
        self.assertEqual(report['scope']['product_code'], '1507')
        tools = TradeAgentTools(DATA_ROOT, self.code_root, question='美国不存在商品XYZ进口')
        found = tools.search_products('不存在商品XYZ', 'import')
        self.assertFalse(found['candidates'])
        with self.assertRaises(ValueError):
            tools.query_trade('import:1201', 'import', 'all', {'type':'latest_contiguous'})

    def test_configured_http_failure_is_saved_and_not_retried(self):
        config_file = self.code_root / 'product-model.json'
        config_file.write_text('{}', encoding='utf-8')
        config = OpenAICompatibleConfig(base_url='https://example.invalid',
                                       api_key='offline-test-only', model='offline-model')
        server = create_server(root=self.code_root, trade_data_root=DATA_ROOT,
                               host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for error, expected in [(ModelAdapterError('模型服务返回 HTTP 400', details={'http_status':400}),
                                 'failed'), (TimeoutError('offline timeout'), 'unknown_outcome')]:
            with self.subTest(expected=expected):
                class FailingModel:
                    calls = 0
                    def complete(inner, **kwargs):
                        inner.calls += 1
                        raise error
                model = FailingModel()
                request = Request(f'http://127.0.0.1:{server.server_port}/api/trade/agent/turn',
                    json.dumps({'question':'美国大豆进口','request_id':uuid.uuid4().hex}).encode(),
                    {'Content-Type':'application/json'})
                with patch('tradeintel_ai.local_provider_config.PRODUCT_CONFIG_PATH', config_file), \
                     patch('tradeintel_ai.web_app.load_product_config', return_value=config), \
                     patch('tradeintel_ai.local_provider_config.product_request_params', return_value={}), \
                     patch('tradeintel_ai.trade_agent_deepseek.create_trade_agent_model', return_value=model):
                    with urlopen(request, timeout=15) as response:
                        result = json.load(response)
                    with urlopen(request, timeout=15) as response:
                        replay = json.load(response)
                self.assertEqual(model.calls, 1)
                self.assertEqual(result['turns'][-1]['status'], expected)
                self.assertEqual(replay['turns'][-1]['status'], expected)
                metrics = result['turns'][-1]['execution_metrics']
                self.assertEqual((metrics['complete_attempts'], metrics['responses_received']), (1, 0))
                self.assertEqual(metrics['attempts'][0]['status'], 'failed_or_unknown')
                self.assertEqual(metrics['attempts'][0]['failure_kind'],
                                 'http_error' if expected == 'failed' else 'timeout')
                self.assertEqual(metrics, replay['turns'][-1]['execution_metrics'])
                self.assertIsNone(metrics['token_totals']['total_tokens']['reported_sum'])
                self.assertFalse(result['turns'][-1]['report_ids'])
                self.assertEqual(read_session(self.code_root, result['session_id'])['turns'][-1]['status'], expected)

    def test_related_corn_and_tea_headings_remain_visible_but_not_queryable(self):
        tools = TradeAgentTools(DATA_ROOT, self.code_root, question="美国玉米进口最近怎样")
        corn = tools.search_products("玉米", "import")["candidates"]
        self.assertEqual((corn[0]["id"], corn[0]["match_type"]),
                         ("import:1005", "exact_product"))
        processed = next(item for item in corn if item["id"] == "import:1904")
        self.assertEqual(processed["match_type"], "related_candidate")
        with self.assertRaisesRegex(ValueError, "相关商品"):
            tools.query_trade("import:1904", "import", "all", {"type": "latest_contiguous"})
        tea = tools.search_products("茶叶", "import")["candidates"]
        self.assertEqual((tea[0]["id"], tea[0]["match_type"]),
                         ("import:0902", "exact_product"))
        self.assertEqual(next(item for item in tea if item["id"] == "import:2101")
                         ["match_type"], "related_candidate")

    def test_english_corn_related_exclusion_and_explicit_code(self):
        tools = TradeAgentTools(DATA_ROOT, self.code_root, question="corn import")
        candidates = tools.search_products("corn", "import")["candidates"]
        self.assertEqual((candidates[0]["code"], candidates[0]["match_type"]),
                         ("1005", "exact_product"))
        self.assertEqual(next(item for item in candidates if item["code"] == "1904")
                         ["match_type"], "related_candidate")
        explicit = tools.search_products("1904", "import")["candidates"]
        self.assertEqual(explicit[0]["match_type"], "exact_product")
        with self.assertRaisesRegex(ValueError, "原问题不一致"):
            tools.query_trade("import:1904", "import", "all", {"type": "latest_contiguous"})
        specified = TradeAgentTools(DATA_ROOT, self.code_root, question="查 HS4 1904 的进口")
        specified.search_products("1904", "import")
        self.assertEqual(specified.candidates["import:1904"]["match_type"], "exact_product")

    def test_monthly_calendar_word_does_not_mean_latest_available(self):
        tools = TradeAgentTools(DATA_ROOT, self.code_root, today=date(2026, 9, 29),
                                question="上月美国大豆进口多少")
        tools.search_products("大豆", "import")
        with self.assertRaisesRegex(ValueError, "缺少 2026-08"):
            tools.query_trade("import:1201", "import", "all",
                              {"type": "calendar_relative", "unit": "month", "offset": -1})

    def test_unregistered_code_is_rejected(self):
        tools = TradeAgentTools(DATA_ROOT, self.code_root)
        with self.assertRaisesRegex(ValueError, "须先从本轮目录"):
            tools.query_trade("import:1201", "import", "all", {"type": "latest_contiguous"})

    def test_clarification_is_available_to_next_turn_without_trusting_old_model_text(self):
        class ClarifyingModel(ScriptedModel):
            def complete(self, *, messages, tools):
                if "本轮用户问题：美国大豆贸易" in messages[1]["content"]:
                    return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "ask_user",
                        {"question": "看进口还是出口？", "choices": ["进口", "出口"]}),))
                self_outer.assertIn("看进口还是出口？", messages[1]["content"])
                self_outer.assertIn("美国大豆贸易", messages[1]["content"])
                self_outer.assertIn("本轮用户问题：进口", messages[1]["content"])
                if messages[-1]["role"] == "user":
                    return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, "search_products",
                        {"term": "大豆", "flow": "import"}),))
                return super().complete(messages=messages, tools=tools)

        self_outer = self
        model = ClarifyingModel()
        agent = TradeResearchAgent(DATA_ROOT, self.code_root, model)
        first = agent.turn("美国大豆贸易", uuid.uuid4().hex)
        self.assertEqual(first["turns"][-1]["status"], "needs_clarification")
        second = agent.turn("进口", uuid.uuid4().hex, first["session_id"])
        self.assertEqual(second["turns"][-1]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
