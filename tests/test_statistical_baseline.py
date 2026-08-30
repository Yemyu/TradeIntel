import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_statistical_baseline import (
    StatisticalBaselineError,
    build_statistical_baseline,
    classify_analysis_phase,
    load_monthly,
)


class StatisticalBaselineTests(unittest.TestCase):
    def _write_monthly(
        self,
        path: Path,
        *,
        skip: tuple[int, int] | None = None,
        coverage_2016: int = 818,
    ) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "year",
                    "month",
                    "target_origin",
                    "target_origin_code",
                    "target_import_value_consumption_usd",
                    "other_origins_import_value_consumption_usd",
                    "all_origins_import_value_consumption_usd",
                    "unique_policy_hts8_count",
                ],
                lineterminator="\n",
            )
            writer.writeheader()
            for year in range(2016, 2020):
                for month in range(1, 13):
                    if (year, month) == skip:
                        continue
                    target = {2016: 100, 2017: 120, 2018: 90, 2019: 81}[year]
                    others = {2016: 100, 2017: 110, 2018: 121, 2019: 133}[year]
                    writer.writerow(
                        {
                            "year": year,
                            "month": month,
                            "target_origin": "CHINA",
                            "target_origin_code": "5700",
                            "target_import_value_consumption_usd": target,
                            "other_origins_import_value_consumption_usd": others,
                            "all_origins_import_value_consumption_usd": target + others,
                            "unique_policy_hts8_count": (
                                coverage_2016 if year == 2016 else 818
                            ),
                        }
                    )

    def test_announcement_and_effective_month_are_not_clean_pre_or_post(self):
        self.assertEqual(classify_analysis_phase((2018, 5)), "clean_pre")
        self.assertEqual(
            classify_analysis_phase((2018, 6)), "announcement_anticipation"
        )
        self.assertEqual(
            classify_analysis_phase((2018, 7)), "effective_month_transition"
        )
        self.assertEqual(classify_analysis_phase((2018, 8)), "immediate_post")

    def test_equal_calendar_window_baseline_and_causal_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            monthly = root / "monthly.csv"
            self._write_monthly(monthly)
            summary = build_statistical_baseline(monthly, root / "out")
            result = summary["comparisons"]["immediate_post_same_months"]

            self.assertAlmostEqual(result["target_change_pct"], -0.25)
            self.assertAlmostEqual(result["other_origins_change_pct"], 0.1)
            self.assertEqual(result["months_per_window"], 5)
            self.assertEqual(
                result["coverage_comparability_status"], "pass_count_gap_le_1pct"
            )
            self.assertFalse(summary["causal_claim"])
            self.assertEqual(summary["adoption"]["causal_event_study"], "blocked")
            self.assertTrue((root / "out/statistical_baseline_report.md").exists())

    def test_large_hts_count_gap_marks_comparison_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            monthly = root / "monthly.csv"
            self._write_monthly(monthly, coverage_2016=770)
            summary = build_statistical_baseline(monthly, root / "out")
            placebo = summary["comparisons"]["pre_policy_placebo_same_months"]
            self.assertEqual(
                placebo["coverage_comparability_status"],
                "review_count_gap_gt_1pct",
            )

    def test_missing_month_blocks_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            monthly = Path(directory) / "monthly.csv"
            self._write_monthly(monthly, skip=(2018, 7))
            with self.assertRaisesRegex(StatisticalBaselineError, "Expected 48 months"):
                load_monthly(monthly)


if __name__ == "__main__":
    unittest.main()
