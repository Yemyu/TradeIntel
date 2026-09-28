"""Offline contract checks for the v4 development freeze (no model calls)."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.freeze_trade_model_v4 import (
    ROOT, _expected_files, _reference, _scenarios, freeze, verify_frozen,
)


def _report(question: str) -> dict:
    months = [f"2025-{month:02d}" for month in range(8, 13)] + [
        f"2026-{month:02d}" for month in range(1, 8)]
    rows = [{"month": month, "status": "observed", "value_usd": 100 + index}
            for index, month in enumerate(months)]
    values = [row["value_usd"] for row in rows]
    return {"kind": "trade-query-v1", "question": question,
            "scope": {"question": question, "flow": "import", "product_code": "5201",
                      "start_month": "2025-08", "end_month": "2026-07",
                      "metric": "import_value_consumption_usd", "partner": "ALL_ORIGINS",
                      "dataset_version": "fixture"},
            "series": rows,
            "summary": {"complete_window": True, "latest_month": "2026-07",
                        "latest_value_usd": values[-1],
                        "month_change_usd": values[-1] - values[-2],
                        "period_total_usd": sum(values)}}


class TradeModelV4FreezeTests(unittest.TestCase):
    def test_scenarios_are_four_declared_development_cases(self):
        cases = _scenarios(ROOT)
        self.assertEqual([case["id"] for case in cases], ["v4-1", "v4-2", "v4-3", "v4-4"])
        self.assertEqual(cases[2]["selected_product_id"], "both:4011")
        self.assertEqual(len(_expected_files()), 30)

    def test_reference_recomputes_rows_and_rejects_question_drift(self):
        case = _scenarios(ROOT)[0]
        report = _report(case["question"])
        reference = _reference(report, case)
        self.assertEqual(reference["directions"]["import"]["latest_change_usd"], 1)
        self.assertEqual(reference["directions"]["import"]["period_total_usd"],
                         sum(row["value_usd"] for row in report["series"]))
        report["scope"]["question"] = "另一道题"
        with self.assertRaisesRegex(ValueError, "原问题"):
            _reference(report, case)

    def test_reference_rejects_missing_or_changed_month_and_summary(self):
        case = _scenarios(ROOT)[0]
        report = _report(case["question"])
        report["series"].pop()
        with self.assertRaisesRegex(ValueError, "月份"):
            _reference(report, case)
        report = _report(case["question"])
        report["series"][4]["month"] = "2025-11"
        with self.assertRaisesRegex(ValueError, "逐月序列"):
            _reference(report, case)
        report = _report(case["question"])
        report["summary"]["period_total_usd"] += 1
        with self.assertRaisesRegex(ValueError, "复算"):
            _reference(report, case)

    def test_interrupted_or_existing_output_is_not_a_frozen_package(self):
        with TemporaryDirectory(prefix="trade-v4-test-") as directory:
            output = Path(directory) / "frozen"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "未就绪"):
                verify_frozen(ROOT, output)
            with self.assertRaises(FileExistsError):
                freeze(ROOT, output)


if __name__ == "__main__":
    unittest.main()
