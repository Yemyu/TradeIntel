"""Deterministic English summaries: same data, no model translation."""
import unittest
from copy import deepcopy

from tradeintel_ai.trade_agent import _program_summary_en


def part(flow, partner="ALL", value=123):
    return {"scope": {"flow": flow, "partner": partner, "product_code": "1201",
                      "product_label": "中文商品", "start_month": "2026-06", "end_month": "2026-07"},
            "summary": {"latest_month": "2026-07", "latest_value_usd": value}}


class ProgramSummaryLanguageTests(unittest.TestCase):
    def test_multiple_reports_keep_partner_and_null_value(self):
        reports = [part("export"), part("export", "CHINA", None)]
        reports[0]["scope"]["official_product_en"] = "SOYBEANS"
        before = deepcopy(reports)
        text = _program_summary_en(reports, 2)
        self.assertIn("SOYBEANS (1201)", text)
        self.assertIn("total exports (FAS) to all destinations were 123 USD", text)
        self.assertIn("No published value is available for 2026-07 total exports (FAS) to China", text)
        self.assertIn("2 registered policy passages", text)
        self.assertNotIn("中文商品", text)
        self.assertEqual(reports, before)

    def test_both_directions_preserve_distinct_bases(self):
        report = {"scope": {**part("import")["scope"], "flow": "both"},
                  "import_report": part("import", "CHINA"), "export_report": part("export", "CHINA", 456)}
        text = _program_summary_en([report], 0)
        self.assertIn("imports for consumption from China were 123 USD", text)
        self.assertIn("total exports (FAS) to China were 456 USD", text)
        self.assertIn("do not subtract them as a trade balance", text)
        self.assertNotIn("registered policy passages", text)
