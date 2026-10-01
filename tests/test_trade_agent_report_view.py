from copy import deepcopy
import unittest
from tradeintel_ai.trade_agent_report_view import build_reader_view


class ReaderViewTests(unittest.TestCase):
    def report(self, value=100, change=-5):
        return {"report_id": "saved", "scope": {"flow": "import", "partner": "ALL_ORIGINS"},
                "summary": {"latest_month": "2026-07", "latest_value_usd": value,
                            "month_change_usd": change}}

    def test_data_only_has_no_policy_or_causal_warning_and_does_not_mutate(self):
        report = self.report()
        original = deepcopy(report)
        view = build_reader_view("进口额多少", [report], {"status": "no_evidence"})
        self.assertIsNone(view["policy"])
        self.assertEqual(view["unanswered"], [])
        self.assertIn("减少 5", view["facts"][0]["text"])
        self.assertIn("Decreased by 5", view["facts"][0]["text_en"])
        self.assertEqual(report, original)

    def test_missing_not_zero_and_no_invented_comparison(self):
        view = build_reader_view("进口", [self.report(None, None)])
        self.assertIn("没有可用", view["facts"][0]["text"])
        self.assertNotIn("前月", view["facts"][0]["text"])

    def test_policy_and_causal_boundaries_preserved(self):
        evidence = {"status": "partial", "evidence_bundles": []}
        view = build_reader_view("关税为什么奏效", [self.report()], evidence)
        self.assertEqual(view["policy"], evidence)
        self.assertEqual(len(view["unanswered"]), 1)
        evidence["status"] = "changed"
        self.assertEqual(view["policy"]["status"], "partial")

    def test_both_preserves_distinct_scopes(self):
        imports = self.report()
        exports = deepcopy(imports)
        exports["scope"] = {"flow": "export", "partner": "CHINA"}
        combined = {"report_id": "both", "scope": {"flow": "both"},
                    "import_report": imports, "export_report": exports}
        view = build_reader_view("进出口", [combined])
        self.assertEqual(len(view["facts"]), 2)
        self.assertIn("中国目的地", view["facts"][1]["text"])
        self.assertIn("FAS", view["facts"][1]["text_en"])

