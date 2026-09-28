"""Offline HTTP coverage of the new product path; no provider network call."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.local_provider_config import save_product_config
from tradeintel_ai.model_adapter import ModelAdapterError
from tradeintel_ai.web_app import create_server
from tradeintel_ai.trade_explanation import PROTOCOL
from tradeintel_ai.trade_explanation_v4 import PROTOCOL as V4_PROTOCOL
from tests.test_trade_query_flow import fixture as import_fixture


class FakeModel:
    def __init__(self, owner):
        self.owner = owner

    def complete(self, *, messages, tools):
        self.owner.calls += 1
        self.owner.last_messages = messages
        if self.owner.error:
            raise self.owner.error
        payload = json.loads(messages[-1]["content"])
        if payload["schema_version"] == V4_PROTOCOL:
            relation = payload["eligible_card_ids"][0]
            answer = {"schema_version": V4_PROTOCOL,
                      "report_sha256": payload["report_sha256"],
                      "relation_snapshot_sha256": payload["relation_snapshot_sha256"],
                      "interpretations": [{"observation_ids": [relation],
                                           "text": "最近几个月进口金额接连增加，但这不代表整个查询期间一直上涨。"}]}
            return ModelResponse(text=json.dumps(answer, ensure_ascii=False),
                                 metadata={"model": "fake-model", "usage": {"total_tokens": 23}})
        interpretations = []
        for group in payload["required_by_direction"]:
            ids = group["required_observation_ids"]
            selected = [item for item in payload["observations"] if item["id"] in ids]
            trend = next((item for item in selected if item["id"].endswith(".trend")), None)
            if trend and trend["direction"] == "资料不足":
                text = "近期走势资料不足，无法判断方向，需要等待连续观测。"
            elif trend:
                text = f"近来的金额走势呈{trend['direction']}，但仅凭金额无法判断具体变化原因。"
            elif any(item["id"].endswith(".period_total") for item in selected):
                text = "所选期间合计反映贸易金额规模，不能直接说明实际贸易数量或变化原因。"
            else:
                text = "最新月金额反映所选期间的贸易规模，还需结合数量和价格资料理解。"
            interpretations.append({"observation_ids": ids, "text": text})
        answer = {"schema_version": PROTOCOL,
                  "report_sha256": payload["report_sha256"],
                  "interpretations": interpretations}
        return ModelResponse(text=json.dumps(answer, ensure_ascii=False),
                             metadata={"model": "fake-model", "usage": {"total_tokens": 23}})


class TradeExplanationHttpTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        import_fixture(self.root)
        self.calls = 0
        self.error = None
        self.last_messages = None
        import tradeintel_ai.local_provider_config as settings
        self.config_patch = patch.object(settings, "PRODUCT_CONFIG_PATH", self.root / ".local/product-model.json")
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        save_product_config("deepseek", "deepseek-flash", "x" * 24, reasoning="none")
        self.server = create_server(root=self.root, host="127.0.0.1", port=0,
                                    trade_model_factory=lambda config, params: FakeModel(self))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, body):
        request = Request(f"http://127.0.0.1:{self.server.server_port}{path}",
                          json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urlopen(request) as response:
            return json.load(response)

    def get(self, path):
        with urlopen(f"http://127.0.0.1:{self.server.server_port}{path}") as response:
            return json.load(response)

    def report(self):
        # Legacy v3 records keep their original interpretation contract.
        from tradeintel_ai.trade_query_flow import generate_trade_report
        from tradeintel_ai.trade_report_store import create_record
        question = "最近美国大豆进口有什么变化"
        proposal = self.post("/api/trade/prepare", {"question": question})
        report = generate_trade_report(self.root, question, selected_flow="import",
                                       dataset_version=proposal["dataset_version"])
        return create_record(self.root, report)

    def test_report_call_review_restore_and_duplicate_block(self):
        report = self.report()
        self.assertEqual(report["ai_status"], "not_requested")
        self.assertEqual(self.calls, 0)
        body = {"report_id": report["report_id"], "report_sha256": report["report_sha256"]}
        drafted = self.post("/api/trade/explanation/call", body)
        self.assertEqual(drafted["explanation"]["status"], "needs_review")
        self.assertEqual(self.calls, 1)
        sent = json.loads(self.last_messages[1]["content"])
        self.assertEqual(sent["required_observation_ids"], ["import.trend"])
        self.assertNotIn("monthly_rows", sent)
        with self.assertRaises(HTTPError):
            self.post("/api/trade/explanation/call", body)
        self.assertEqual(self.calls, 1)
        draft = drafted["explanation"]
        saved = self.post("/api/trade/explanation/review", {
            **body, "raw_sha256": draft["raw_sha256"], "revision": draft["revision"],
            "reviewer": "tester", "facts_checked": True,
            "decisions": [{"index": 0, "verdict": "accept", "reason": "已核对来源"}]})
        self.assertEqual(saved["explanation"]["status"], "reviewed")
        restored = self.get(f"/api/trade/report-state?report_id={report['report_id']}")
        self.assertEqual(restored["explanation"]["status"], "reviewed")
        self.assertEqual(restored["report_sha256"], report["report_sha256"])
        self.assertNotIn("raw_text", restored["explanation"])

    def test_wrong_digest_and_known_or_unknown_failure_do_not_repeat(self):
        report = self.report()
        body = {"report_id": report["report_id"], "report_sha256": "0" * 64}
        with self.assertRaises(HTTPError):
            self.post("/api/trade/explanation/call", body)
        self.assertEqual(self.calls, 0)
        body["report_sha256"] = report["report_sha256"]
        self.error = ModelAdapterError("HTTP 400", details={"http_status": 400})
        result = self.post("/api/trade/explanation/call", body)
        self.assertEqual(result["explanation"]["status"], "failed")
        self.assertEqual(self.calls, 1)
        self.error = None
        with self.assertRaises(HTTPError):
            self.post("/api/trade/explanation/call", body)
        self.assertEqual(self.calls, 1)
        second = self.report()
        self.error = ModelAdapterError("timed out", details={"category": "timeout"})
        result = self.post("/api/trade/explanation/call", {
            "report_id": second["report_id"], "report_sha256": second["report_sha256"]})
        self.assertEqual(result["explanation"]["status"], "unknown_outcome")

    def test_new_report_without_substantive_relation_does_not_call_model(self):
        question = "最近美国大豆进口有什么变化"
        proposal = self.post("/api/trade/prepare", {"question": question})
        report = self.post("/api/trade/report", {"question": question,
                                                 "selected_flow": "import",
                                                 "dataset_version": proposal["dataset_version"]})
        self.assertEqual(report["explanation"]["protocol"], V4_PROTOCOL)
        self.assertFalse(report["explanation"]["available"])
        with self.assertRaises(HTTPError):
            self.post("/api/trade/explanation/call", {"report_id": report["report_id"],
                                                        "report_sha256": report["report_sha256"]})
        self.assertEqual(self.calls, 0)

    def test_v4_relation_runs_through_existing_call_and_review_store(self):
        from tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question
        from tradeintel_ai.trade_report_store import create_record
        question = "最近美国大豆进口有什么变化"
        proposal = prepare_trade_question(self.root, question)
        report = generate_trade_report(self.root, question, selected_flow="import",
                                       dataset_version=proposal["dataset_version"])
        report["series"][-3]["value_usd"] = 10
        report["series"][-2]["value_usd"] = 11
        report["series"][-1]["value_usd"] = 12
        report["summary"]["month_change_usd"] = 1
        report["summary"]["period_total_usd"] = sum(r["value_usd"] for r in report["series"])
        saved = create_record(self.root, report, explanation_protocol=V4_PROTOCOL)
        self.assertTrue(saved["explanation"]["available"])
        body = {"report_id": saved["report_id"], "report_sha256": saved["report_sha256"]}
        drafted = self.post("/api/trade/explanation/call", body)
        self.assertEqual(drafted["explanation"]["status"], "needs_review")
        self.assertEqual(self.calls, 1)
        self.assertEqual(json.loads(self.last_messages[-1]["content"])["schema_version"], V4_PROTOCOL)
        with self.assertRaises(HTTPError):
            self.post("/api/trade/explanation/call", body)
        reviewed = self.post("/api/trade/explanation/review", {
            **body, "raw_sha256": drafted["explanation"]["raw_sha256"], "revision": 0,
            "reviewer": "tester", "facts_checked": True,
            "decisions": [{"index": 0, "verdict": "accept", "reason": "已核对关系卡"}]})
        self.assertEqual(reviewed["explanation"]["status"], "reviewed")


if __name__ == "__main__":
    unittest.main()
