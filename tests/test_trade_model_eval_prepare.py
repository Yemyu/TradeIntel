"""Offline checks for the candidate trade-model evaluation package."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.prepare_trade_model_eval import (
    _independent_reference,
    _scenarios,
    build_candidate,
    verify_candidate,
)


ROOT = Path(__file__).resolve().parents[1]


def _report() -> dict:
    rows = [
        {"month": f"2025-{month:02d}", "status": "observed", "value_usd": 100 + month}
        for month in range(8, 13)
    ] + [
        {"month": f"2026-{month:02d}", "status": "observed", "value_usd": 100 + month}
        for month in range(1, 8)
    ]
    values = [row["value_usd"] for row in rows]
    return {
        "kind": "trade-query-v1",
        "scope": {"flow": "import", "product_code": "0902",
                  "start_month": "2025-08", "end_month": "2026-07",
                  "metric": "value_usd", "partner": "all", "dataset_version": "test"},
        "series": rows,
        "summary": {"complete_window": True, "latest_month": "2026-07",
                    "latest_value_usd": values[-1],
                    "month_change_usd": values[-1] - values[-2],
                    "period_total_usd": sum(values)},
    }


class TradeModelEvalPreparationTests(unittest.TestCase):
    def test_four_realistic_scenarios_are_structurally_valid(self) -> None:
        cases = _scenarios(ROOT)
        self.assertEqual([case["id"] for case in cases], ["t1", "t2", "t3", "t4"])
        self.assertEqual(cases[2]["flow"], "both")

    def test_reference_recomputes_amounts_from_monthly_rows(self) -> None:
        case = _scenarios(ROOT)[0]
        report = _report()
        reference = _independent_reference(report, case)
        self.assertEqual(reference["directions"]["import"]["latest_value_usd"], 107)
        self.assertEqual(reference["directions"]["import"]["period_total_usd"],
                         sum(row["value_usd"] for row in report["series"]))

    def test_reference_rejects_incomplete_or_inconsistent_report(self) -> None:
        case = _scenarios(ROOT)[0]
        report = _report()
        report["series"].pop()
        with self.assertRaisesRegex(ValueError, "月份不完整"):
            _independent_reference(report, case)
        report = _report()
        report["summary"]["period_total_usd"] += 1
        with self.assertRaisesRegex(ValueError, "复算不一致"):
            _independent_reference(report, case)

    def test_incomplete_package_cannot_be_verified_or_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "candidate"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "未就绪"):
                verify_candidate(ROOT, output)
            with self.assertRaises(FileExistsError):
                build_candidate(ROOT, output)


if __name__ == "__main__":
    unittest.main()
