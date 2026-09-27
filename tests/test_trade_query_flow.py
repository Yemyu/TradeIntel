import csv
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from src.tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question


FIELDS = ["year", "month", "hts10", "hts8", "china_import_value_consumption_usd",
          "all_origin_import_value_consumption_usd", "china_observed", "all_origin_observed",
          "source_sha256"]


def fixture(root: Path) -> None:
    folder = root / "data/processed/trade_hts10/monthly"
    folder.mkdir(parents=True)
    months = []
    for index in range(12):
        year, month = (2025, index + 8) if index < 5 else (2026, index - 4)
        output = f"data/processed/trade_hts10/monthly/trade_hts10_{year}_{month:02d}.csv"
        with (root / output).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            for code, value in (("1201100000", 2), ("1201900005", 10), ("1005100010", 7)):
                writer.writerow(dict(year=year, month=month, hts10=code, hts8=code[:8],
                                     china_import_value_consumption_usd=value // 2,
                                     all_origin_import_value_consumption_usd=value,
                                     china_observed=1, all_origin_observed=1,
                                     source_sha256="a" * 64))
        months.append(dict(year=year, month=month, status="processed", monthly_output=output,
                           source_sha256="a" * 64,
                           source_url=f"https://www.census.gov/fixture/{year}-{month:02d}"))
    (folder.parent / "manifest.json").write_text(json.dumps({"months": months}))


class TradeQueryFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        fixture(self.root)

    def test_ambiguous_trade_requires_direction(self):
        question = "最近美国大豆贸易有什么变化"
        clarification = prepare_trade_question(self.root, question)
        self.assertEqual(clarification["status"], "needs_direction")
        self.assertNotIn("一个核验月份", clarification["message"])
        proposal = prepare_trade_question(self.root, question, selected_flow="import")
        self.assertEqual((proposal["product_code"], proposal["start_month"], proposal["end_month"]),
                         ("1201", "2025-08", "2026-07"))

    def test_soybean_group_includes_seed_and_other_but_not_corn(self):
        question = "最近美国大豆进口有什么变化"
        proposal = prepare_trade_question(self.root, question)
        report = generate_trade_report(self.root, question, selected_flow="import",
                                       dataset_version=proposal["dataset_version"])
        self.assertEqual(report["summary"]["latest_value_usd"], 12)
        self.assertEqual(report["summary"]["period_total_usd"], 144)
        self.assertEqual(report["series"][-1]["matched_hts10"], 2)
        self.assertEqual(report["ai_status"], "not_run")
        corn = prepare_trade_question(self.root, "最近美国玉米进口怎么样")
        corn_report = generate_trade_report(self.root, corn["question"], selected_flow="import",
                                            dataset_version=corn["dataset_version"])
        self.assertEqual(corn_report["summary"]["latest_value_usd"], 7)

    def test_explicit_month_china_and_stale_version(self):
        question = "2026年7月美国从中国进口大豆多少"
        proposal = prepare_trade_question(self.root, question)
        self.assertEqual((proposal["start_month"], proposal["end_month"], proposal["partner"]),
                         ("2026-07", "2026-07", "CHINA"))
        report = generate_trade_report(self.root, question, selected_flow=None,
                                       dataset_version=proposal["dataset_version"])
        self.assertEqual(report["summary"]["latest_value_usd"], 6)
        with self.assertRaisesRegex(ValueError, "数据版本已变化"):
            generate_trade_report(self.root, question, selected_flow=None,
                                  dataset_version="0" * 64)

    def test_unsupported_direction_comparison_and_derivative_are_not_silent(self):
        for question in ("美国大豆出口", "美国大豆进出口", "美国大豆进口同比",
                         "美国豆粕进口", "美国大豆进口来自巴西", "今年美国大豆进口",
                         "近两年美国大豆进口"):
            with self.subTest(question=question):
                self.assertNotEqual(prepare_trade_question(self.root, question)["status"], "ready")

    def test_unknown_second_product_cannot_be_silently_dropped(self):
        for question in ("最近美国大豆和小麦出口有什么变化？",
                         "最近美国大豆和咖啡出口有什么变化？",
                         "美国小麦和大豆出口有什么变化？"):
            with self.subTest(question=question):
                result = prepare_trade_question(self.root, question)
                self.assertEqual(result["status"], "needs_product")

    def test_commodity_group_and_specific_code_require_scope_choice(self):
        result = prepare_trade_question(self.root, "美国大豆和1201900005进口有什么变化？")
        self.assertEqual(result["status"], "needs_product")
        self.assertIn("范围不同", result["message"])

    def test_calendar_month_ambiguity_requires_clarification(self):
        for question in ("2026年5月和7月美国大豆出口有什么变化？",
                         "美国大豆出口7月有什么变化？"):
            with self.subTest(question=question):
                self.assertEqual(prepare_trade_question(self.root, question)["status"], "needs_period")

    def test_explicit_month_range_and_recent_twelve_months_are_preserved(self):
        question = "2026年5月至7月美国大豆进口有什么变化？"
        proposal = prepare_trade_question(self.root, question)
        self.assertEqual((proposal["status"], proposal["start_month"], proposal["end_month"]),
                         ("ready", "2026-05", "2026-07"))

        recent = prepare_trade_question(self.root, "最近12个月美国大豆进口有什么变化？")
        self.assertEqual((recent["status"], recent["start_month"], recent["end_month"]),
                         ("ready", "2025-08", "2026-07"))

    def test_direction_pair_is_not_mistaken_for_two_products(self):
        question = "最近美国大豆进口和出口有什么变化？"
        result = prepare_trade_question(self.root, question)
        # This fixture has no export snapshot, but parsing must reach the
        # availability check instead of treating “进口和出口” as two goods.
        self.assertEqual(result["status"], "not_available")
        self.assertIn("出口版本尚未接入", result["message"])

    def test_http_prepare_and_report_use_same_version(self):
        from src.tradeintel_ai.web_app import create_server
        server = create_server(root=self.root, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def post(path, body):
            req = Request(f"http://127.0.0.1:{server.server_port}{path}",
                          json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urlopen(req) as response:
                return json.load(response)
        proposal = post("/api/trade/prepare", {"question": "美国大豆进口"})
        report = post("/api/trade/report", {"question": "美国大豆进口",
                                           "selected_flow": "import",
                                           "dataset_version": proposal["dataset_version"]})
        self.assertEqual(report["summary"]["latest_value_usd"], 12)


if __name__ == "__main__":
    unittest.main()
