"""Reviewed heading and direction contracts, real tools, no provider calls."""
from datetime import date
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_data_repository import TradeDataError
from tradeintel_ai.trade_report_store import get_state
from tradeintel_ai.trade_agent_report_view import build_reader_view
from scripts.score_us_agent_retest import check_saved_report

DATA = Path(__file__).resolve().parents[1] / "tmp/handoff-runs/trade-demo-data-20260925"
REFERENCE = DATA.parent / "us-agent-retest-20261001-v5/reference/trade.json"


@unittest.skipUnless(DATA.is_dir(), "local data absent")
class CatalogContractTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def tools(self, question=""):
        return TradeAgentTools(DATA, self.root, today=date(2026, 10, 1), question=question)

    def test_bilingual_reviewed_families_rank_first(self):
        tools = self.tools()
        for code, names in {"1801": ("可可豆", "cocoa beans"), "2204": ("葡萄酒", "wine"),
                            "4001": ("天然橡胶", "natural rubber"),
                            "8101": ("钨及其制品", "tungsten articles"),
                            "2611": ("钨矿砂", "tungsten ores"),
                            "2307": ("葡萄酒渣", "wine lees")}.items():
            for name in names:
                with self.subTest(name=name):
                    first = tools.search_products(name, "import")["candidates"][0]
                    self.assertEqual((first["code"], first["match_type"]), (code, "heading_family"))
                    self.assertTrue(first["scope_note_en"])

    def test_ambiguous_and_processed_discovery_not_promoted(self):
        for phrase in ("钨", "tungsten", "橡胶", "rubber", "天然橡胶轮胎", "natural rubber derivatives",
                       "wine vinegar", "葡萄酒瓶", "cocoa bean powder", "可可豆油"):
            with self.subTest(phrase=phrase):
                tools = self.tools(phrase)
                found = tools.search_products(phrase, "import")["candidates"]
                self.assertFalse(any(c["match_type"] != "related_candidate" for c in found))
        for phrase, selected in (("钨", "钨及其制品"), ("tungsten", "tungsten ores"),
                                 ("橡胶", "natural rubber"), ("天然橡胶轮胎", "天然橡胶"),
                                 ("葡萄酒渣", "wine"), ("葡萄酒瓶", "wine"), ("可可豆粉", "cocoa beans")):
            tools = self.tools(phrase)
            candidate = tools.search_products(selected, "import")["candidates"][0]
            with self.subTest(original=phrase), self.assertRaises(TradeDataError):
                tools.query_trade(candidate["id"], "import", "all", {"type": "latest_contiguous", "count": 1})

    def test_explicit_subsets_do_not_use_heading_total(self):
        for question, term in (("只统计天然橡胶，排除其他胶", "天然橡胶"),
                               ("natural rubber only", "natural rubber"),
                               ("钨及其制品，不含钨废料", "钨及其制品"),
                               ("tungsten articles excluding scrap", "tungsten articles")):
            tools = self.tools(question)
            candidate = tools.search_products(term, "import")["candidates"][0]
            with self.subTest(question=question), self.assertRaises(TradeDataError):
                tools.query_trade(candidate["id"], "import", "all", {"type": "latest_contiguous", "count": 1})

    def test_scope_notes_survive_real_query_save_reader_and_both(self):
        for flow, count in (("import", 1), ("export", 6), ("both", 3)):
            tools = self.tools("天然橡胶")
            c = tools.search_products("natural rubber", flow)["candidates"][0]
            result = tools.query_trade(c["id"], flow, "all", {"type": "latest_contiguous", "count": count})
            report = get_state(self.root, result["report_id"])
            view = build_reader_view("天然橡胶", [report])
            if not REFERENCE.is_file():
                self.fail("independent saved CSV reference absent")
            checked = check_saved_report(self.root, result["report_id"],
                {"expected_product": "4001", "flow": flow, "partner": "all"},
                json.loads(REFERENCE.read_text()))
            self.assertTrue(checked["passed"], checked)
            self.assertIn("其他天然胶", result["scope_note"])
            self.assertIn("other natural gums", result["scope_note_en"])
            for fact in view["facts"]:
                self.assertEqual(fact["scope"]["coverage_note"], result["scope_note"])
                self.assertEqual(fact["scope"]["coverage_note_en"], result["scope_note_en"])
            if flow != "import":
                self.assertIn("长期趋势", result["scope_note"])

    def test_both_projection_equals_real_single_direction_query(self):
        tools = self.tools("美国大豆进口和出口")
        found = tools.search_products("大豆", "both")["candidates"][0]
        self.assertEqual(found["supported_flows"], ["both", "import", "export"])
        reports = []
        for flow in ("import", "export"):
            period = {"type": "latest_contiguous", "count": 3}
            projected = tools.query_trade(found["id"], flow, "all", period)
            report = get_state(self.root, projected["report_id"])
            single = self.tools()
            c = single.search_products("大豆", flow)["candidates"][0]
            other = get_state(self.root, single.query_trade(c["id"], flow, "all", period)["report_id"])
            self.assertEqual(report["series"], other["series"])
            self.assertEqual(report["summary"], other["summary"])
            self.assertEqual(report["scope"]["dataset_version"], other["scope"]["dataset_version"])
            self.assertEqual(report["scope"]["selected_product_id"], f"{flow}:1201")
            self.assertEqual(report["scope"]["source_candidate_id"], "both:1201")
            reports.append(projected["report_id"])
        tools.validate_finish_period(reports)
        with self.assertRaises(TradeDataError):
            tools.validate_finish_period(reports[:1])

    def test_projection_retains_original_month_validation_and_version(self):
        tools = self.tools()
        c = tools.search_products("大豆", "both")["candidates"][0]
        period = {"type": "latest_contiguous", "count": 3}
        for reason in ("缺码", "描述变化", "月份缺失"):
            with patch.object(tools.catalog, "validate_choice", side_effect=TradeDataError(reason)) as validate:
                with self.assertRaises(TradeDataError):
                    tools.query_trade(c["id"], "export", "all", period)
                self.assertEqual(validate.call_args.args[0], "export:1201")
                self.assertEqual(len(validate.call_args.args[3]), 3)
        tools.candidates[c["id"]]["catalog_version"] = "stale"
        with self.assertRaises(TradeDataError):
            tools.query_trade(c["id"], "export", "all", period)

    def test_single_opposite_cross_turn_and_unknown_match_refused(self):
        tools = self.tools()
        c = tools.search_products("大豆", "import")["candidates"][0]
        for flow in ("export", "both"):
            with self.assertRaises(TradeDataError):
                tools.query_trade(c["id"], flow, "all", {"type": "latest_contiguous"})
        fresh = self.tools()
        with self.assertRaises(TradeDataError):
            fresh.query_trade(c["id"], "import", "all", {"type": "latest_contiguous"})
        tools.candidates[c["id"]]["match_type"] = "invented"
        with self.assertRaises(TradeDataError):
            tools.query_trade(c["id"], "import", "all", {"type": "latest_contiguous"})

    def test_explicit_heading_code_still_discloses_group(self):
        tools = self.tools("HS4 4001")
        c = tools.search_products("HS4 4001", "import")["candidates"][0]
        self.assertEqual(c["match_type"], "exact_product")
        self.assertIn("other natural gums", c["scope_note_en"])
