"""The published export snapshot must drive the user question, not a demo code list."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
import threading

from tradeintel_ai.census_export_publish import publish_export_month
from tradeintel_ai.trade_data_repository import TradeDataError
from tradeintel_ai.trade_export_repository import ExportDataRepository, ExportTradeQuery
from tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question
from tradeintel_ai.web_app import create_server
from tests.test_census_export_audit import _archive
from tests.test_trade_query_flow import fixture as import_fixture


class TradeExportIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        import_fixture(self.root)
        archive = self.root / "EXDB2607.ZIP"
        _archive(archive)
        self.published = publish_export_month(self.root, archive, year=2026, month=7)

    def test_publisher_is_idempotent_and_checksums_all_products(self) -> None:
        first = self.published
        second = publish_export_month(self.root, self.root / "EXDB2607.ZIP", year=2026, month=7)
        self.assertEqual(first["dataset_version"], second["dataset_version"])
        self.assertEqual(first["record"]["processed_sha256"], second["record"]["processed_sha256"])
        self.assertEqual(first["record"]["processed_rows"], 3)
        catalog = ExportDataRepository(self.root).catalog()
        self.assertEqual(catalog["months"][0]["status"], "queryable_aggregate")

    def test_export_query_uses_destination_and_keeps_absence_distinct(self) -> None:
        version = self.published["dataset_version"]
        repo = ExportDataRepository(self.root)
        def query(code: str, destination: str) -> dict:
            return repo.query(ExportTradeQuery("US", "export", code, "2026-07", "2026-07",
                                               destination, version))["months"][0]
        self.assertEqual(query("1201", "ALL_DESTINATIONS")["value_usd"], 102)
        self.assertEqual(query("1201", "CHINA")["value_usd"], 100)
        self.assertEqual(query("1005", "ALL_DESTINATIONS")["value_usd"], 50)
        self.assertEqual(query("1005", "CHINA")["status"], "no_record")
        self.assertIsNone(query("1005", "CHINA")["value_usd"])

    def test_natural_question_export_and_both_are_separate(self) -> None:
        question = "最近美国大豆出口有什么变化"
        proposal = prepare_trade_question(self.root, question)
        self.assertEqual((proposal["status"], proposal["flow"], proposal["start_month"],
                          proposal["end_month"]), ("ready", "export", "2026-07", "2026-07"))
        report = generate_trade_report(self.root, question, selected_flow=None,
                                       dataset_version=proposal["dataset_version"])
        self.assertEqual(report["summary"]["latest_value_usd"], 102)
        self.assertIsNone(report["summary"]["month_change_usd"])
        self.assertEqual(report["scope"]["metric"], "total_export_fas_usd")
        self.assertEqual(report["ai_status"], "not_run")

        question = "最近美国大豆贸易有什么变化"
        self.assertEqual(prepare_trade_question(self.root, question)["status"], "needs_direction")
        both = prepare_trade_question(self.root, question, selected_flow="both")
        self.assertEqual((both["start_month"], both["end_month"]), ("2026-07", "2026-07"))
        report = generate_trade_report(self.root, question, selected_flow="both",
                                       dataset_version=both["dataset_version"])
        self.assertEqual(report["kind"], "trade-query-both-v1")
        self.assertEqual(report["import_report"]["summary"]["latest_value_usd"], 12)
        self.assertEqual(report["export_report"]["summary"]["latest_value_usd"], 102)
        self.assertEqual(report["import_report"]["scope"]["metric"], "import_value_consumption_usd")
        self.assertEqual(report["export_report"]["scope"]["metric"], "total_export_fas_usd")
        self.assertIn("不能直接相减", report["notes"][0])

        question = "最近美国大豆进口和出口有什么变化？"
        both = prepare_trade_question(self.root, question)
        self.assertEqual((both["status"], both["flow"]), ("ready", "both"))

        for question in ("最近美国大豆进出口有什么变化？",
                         "最近美国大豆进/出口有什么变化？"):
            with self.subTest(question=question):
                both = prepare_trade_question(self.root, question)
                self.assertEqual((both["status"], both["flow"]), ("ready", "both"))
                report = generate_trade_report(self.root, question, selected_flow=None,
                                               dataset_version=both["dataset_version"])
                self.assertEqual(report["kind"], "trade-query-both-v1")
                self.assertEqual(report["import_report"]["summary"]["latest_value_usd"], 12)
                self.assertEqual(report["export_report"]["summary"]["latest_value_usd"], 102)

    def test_precise_non_soy_schedule_b_code_is_queryable(self) -> None:
        question = "2026年7月美国出口1005902020多少"
        proposal = prepare_trade_question(self.root, question)
        self.assertEqual((proposal["status"], proposal["product_code"], proposal["flow"]),
                         ("ready", "1005902020", "export"))
        self.assertNotIn("HTS", proposal["product_label"])
        report = generate_trade_report(self.root, question, selected_flow=None,
                                       dataset_version=proposal["dataset_version"])
        self.assertEqual(report["summary"]["latest_value_usd"], 50)

    def test_present_but_corrupted_export_must_raise(self) -> None:
        manifest = self.root / "data/processed/trade_scheduleb10/manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["months"][0]["processed_sha256"] = "0" * 64
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(TradeDataError, "摘要不符"):
            prepare_trade_question(self.root, "美国大豆出口")

    def test_http_prepare_report_query(self) -> None:
        server = create_server(root=self.root, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(path: str, body: dict) -> dict:
            request = Request(f"http://127.0.0.1:{server.server_port}{path}",
                              json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urlopen(request) as response:
                return json.load(response)

        question = "最近美国大豆出口有什么变化"
        proposal = post("/api/trade/prepare", {"question": question})
        self.assertEqual(proposal["flow"], "export")
        report = post("/api/trade/report", {"question": question,
                                            "selected_flow": "export",
                                            "dataset_version": proposal["dataset_version"]})
        self.assertEqual(report["summary"]["latest_value_usd"], 102)
        facts = post("/api/trade/query", {"reporter": "US", "flow": "export",
                                            "product_code": "1201", "start_month": "2026-07",
                                            "end_month": "2026-07", "partner": "CHINA",
                                            "dataset_version": proposal["dataset_version"]})
        self.assertEqual(facts["months"][0]["value_usd"], 100)


if __name__ == "__main__":
    unittest.main()
