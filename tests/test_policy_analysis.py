import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.analyze_policy_case import analyse_policy_case, classify_month


class PolicyAnalysisTests(unittest.TestCase):
    def _write_fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        event = root / "event.csv"
        with event.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "policy_id",
                    "policy_name",
                    "importer",
                    "target_origin",
                    "announcement_date",
                    "effective_date",
                    "additional_rate",
                    "source_url",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "policy_id": "fixture",
                    "policy_name": "Fixture policy",
                    "importer": "United States",
                    "target_origin": "China",
                    "announcement_date": "2018-06-15",
                    "effective_date": "2018-07-06",
                    "additional_rate": "0.25",
                    "source_url": "https://example.test/policy.pdf",
                }
            )

        products = root / "products.csv"
        with products.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["canonical_hts8"])
            writer.writeheader()
            writer.writerows(
                [
                    {"canonical_hts8": "1111.11.11"},
                    {"canonical_hts8": "2222.22.22"},
                ]
            )

        panel = root / "panel.csv"
        with panel.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "year",
                    "month",
                    "origin_code",
                    "origin_name",
                    "hts8",
                    "import_value_consumption_usd",
                ],
            )
            writer.writeheader()
            for year in range(2016, 2020):
                for month in range(1, 13):
                    if (year, month) < (2018, 7):
                        china, mexico = 100, 50
                    elif (year, month) == (2018, 7):
                        china, mexico = 60, 50
                    else:
                        china, mexico = 80, 100
                    writer.writerow(
                        {
                            "year": year,
                            "month": month,
                            "origin_code": "5700",
                            "origin_name": "CHINA",
                            "hts8": "11111111",
                            "import_value_consumption_usd": china,
                        }
                    )
                    writer.writerow(
                        {
                            "year": year,
                            "month": month,
                            "origin_code": "2010",
                            "origin_name": "MEXICO",
                            "hts8": "11111111",
                            "import_value_consumption_usd": mexico,
                        }
                    )

        origins = root / "origin_dimension.csv"
        with origins.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "origin_code",
                    "canonical_origin_name",
                    "observed_origin_names",
                    "quality_status",
                ],
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "origin_code": "5700",
                        "canonical_origin_name": "CHINA",
                        "observed_origin_names": "CHINA",
                        "quality_status": "pass",
                    },
                    {
                        "origin_code": "2010",
                        "canonical_origin_name": "MEXICO",
                        "observed_origin_names": "MEXICO",
                        "quality_status": "pass",
                    },
                ]
            )

        policy_origins = root / "policy_origin_mapping.csv"
        with policy_origins.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["policy_id", "origin_code"],
            )
            writer.writeheader()
            writer.writerow({"policy_id": "fixture", "origin_code": "5700"})
        return event, products, panel, origins, policy_origins

    def test_month_classification_marks_effective_month_as_transition(self):
        effective = date(2018, 7, 6)
        self.assertEqual(classify_month(2018, 6, effective), "pre")
        self.assertEqual(classify_month(2018, 7, effective), "transition")
        self.assertEqual(classify_month(2018, 8, effective), "post")

    def test_analysis_joins_codes_and_computes_descriptive_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event, products, panel, origins, policy_origins = self._write_fixture(root)
            summary = analyse_policy_case(
                event_path=event,
                products_path=products,
                panel_path=panel,
                origin_dimension_path=origins,
                policy_origin_mapping_path=policy_origins,
                output_dir=root / "analysis",
            )

            self.assertEqual(summary["trade_panel"]["months"], 48)
            self.assertEqual(summary["target_origin"]["trade_origin_code"], "5700")
            self.assertEqual(
                summary["target_origin_summary"]["average_monthly_change_pct"],
                -0.2,
            )
            with (root / "analysis/policy_case_monthly.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                monthly = list(csv.DictReader(handle))
            self.assertEqual(monthly[29]["period"], "pre")
            self.assertEqual(monthly[30]["period"], "transition")
            self.assertEqual(monthly[31]["period"], "post")

            with (root / "analysis/policy_case_summary.json").open(
                encoding="utf-8"
            ) as handle:
                written_summary = json.load(handle)
            self.assertFalse(written_summary["causal_claim"])

    def test_analysis_groups_historical_origin_names_by_stable_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event, products, panel, origins, policy_origins = self._write_fixture(root)
            with origins.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "origin_code",
                        "canonical_origin_name",
                        "observed_origin_names",
                        "quality_status",
                    ],
                )
                writer.writerow(
                    {
                        "origin_code": "9999",
                        "canonical_origin_name": "NEWLAND",
                        "observed_origin_names": "OLDLAND | NEWLAND",
                        "quality_status": "review_name_change",
                    }
                )
            with panel.open(newline="", encoding="utf-8") as handle:
                existing = list(csv.DictReader(handle))
                fieldnames = list(existing[0])
            with panel.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                for year in range(2016, 2020):
                    for month in range(1, 13):
                        writer.writerow(
                            {
                                "year": year,
                                "month": month,
                                "origin_code": "9999",
                                "origin_name": "OLDLAND" if year < 2019 else "NEWLAND",
                                "hts8": "11111111",
                                "import_value_consumption_usd": 10,
                            }
                        )

            summary = analyse_policy_case(
                event_path=event,
                products_path=products,
                panel_path=panel,
                origin_dimension_path=origins,
                policy_origin_mapping_path=policy_origins,
                output_dir=root / "analysis",
            )
            self.assertEqual(summary["trade_panel"]["origins"], 3)
            with (root / "analysis/policy_case_country_change.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))
            matching = [row for row in rows if row["origin_code"] == "9999"]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["origin_name"], "NEWLAND")


if __name__ == "__main__":
    unittest.main()
