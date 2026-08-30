import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_data_quality import audit_data_quality, write_outputs
from scripts.load_quality_mysql import build_load_sql, sql_text


class DataQualityTests(unittest.TestCase):
    def _write_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        event = root / "event.csv"
        with event.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "policy_id",
                    "policy_name",
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
                    "target_origin": "Oldland",
                    "announcement_date": "2018-01-01",
                    "effective_date": "2018-01-15",
                    "additional_rate": "0.25",
                    "source_url": "https://example.test/policy.pdf",
                }
            )

        products = root / "products.csv"
        with products.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "policy_id",
                    "raw_hts",
                    "canonical_hts8",
                    "amended",
                    "amendment_source_url",
                    "source_url",
                ],
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "policy_id": "fixture",
                        "raw_hts": "9033.00",
                        "canonical_hts8": "9033.00.90",
                        "amended": "True",
                        "amendment_source_url": "https://example.test/amendment.pdf",
                        "source_url": "https://example.test/policy.pdf",
                    },
                    {
                        "policy_id": "fixture",
                        "raw_hts": "1111.11.11",
                        "canonical_hts8": "1111.11.11",
                        "amended": "False",
                        "amendment_source_url": "",
                        "source_url": "https://example.test/policy.pdf",
                    },
                ]
            )

        manifest = root / "manifest.csv"
        manifest_fields = [
            "year",
            "month",
            "source_url",
            "source_file_name",
            "source_sha256",
            "source_archive_bytes",
            "source_retrieved_at_utc",
            "status",
            "raw_archive_retained_after_processing",
        ]
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=manifest_fields)
            writer.writeheader()
            for month, source_hash in ((1, "a" * 64), (2, "b" * 64)):
                writer.writerow(
                    {
                        "year": 2018,
                        "month": month,
                        "source_url": f"https://example.test/2018-{month:02d}.zip",
                        "source_file_name": f"2018-{month:02d}.zip",
                        "source_sha256": source_hash,
                        "source_archive_bytes": 100,
                        "source_retrieved_at_utc": "2026-08-30T00:00:00+00:00",
                        "status": "processed",
                        "raw_archive_retained_after_processing": "False",
                    }
                )

        panel = root / "panel.csv"
        panel_fields = [
            "year",
            "month",
            "origin_code",
            "origin_name",
            "hts10",
            "hts8",
            "import_value_consumption_usd",
            "detail_row_count",
            "source_url",
            "source_file_name",
            "source_sha256",
        ]
        with panel.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=panel_fields)
            writer.writeheader()
            for month, origin_name, source_hash in (
                (1, "OLDLAND", "a" * 64),
                (2, "NEWLAND", "b" * 64),
            ):
                source_url = f"https://example.test/2018-{month:02d}.zip"
                source_file = f"2018-{month:02d}.zip"
                writer.writerow(
                    {
                        "year": 2018,
                        "month": month,
                        "origin_code": "9999",
                        "origin_name": origin_name,
                        "hts10": "9033009000",
                        "hts8": "90330090",
                        "import_value_consumption_usd": 100,
                        "detail_row_count": 1,
                        "source_url": source_url,
                        "source_file_name": source_file,
                        "source_sha256": source_hash,
                    }
                )
                writer.writerow(
                    {
                        "year": 2018,
                        "month": month,
                        "origin_code": "8888",
                        "origin_name": "OTHERLAND",
                        "hts10": "1111111100",
                        "hts8": "11111111",
                        "import_value_consumption_usd": 50,
                        "detail_row_count": 1,
                        "source_url": source_url,
                        "source_file_name": source_file,
                        "source_sha256": source_hash,
                    }
                )
        return event, products, manifest, panel

    def test_audit_separates_name_review_from_blocking_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event, products, manifest, panel = self._write_fixture(root)
            report, origins, policy_origins, coverage = audit_data_quality(
                event_path=event,
                products_path=products,
                manifest_path=manifest,
                panel_path=panel,
                expected_policy_count=2,
                expected_months=[(2018, 1), (2018, 2)],
            )

            self.assertEqual(report["overall_status"], "pass_with_review")
            self.assertEqual(report["summary"]["failed_rule_count"], 0)
            self.assertEqual(report["summary"]["review_rules"], ["ORIGIN-002"])
            origin = next(row for row in origins if row["origin_code"] == "9999")
            self.assertEqual(origin["canonical_origin_name"], "NEWLAND")
            self.assertEqual(policy_origins[0]["origin_code"], "9999")
            self.assertTrue(all(row["coverage_status"] == "observed" for row in coverage))

            output = root / "quality"
            write_outputs(output, report, origins, policy_origins, coverage)
            with (output / "data_quality_report.json").open(encoding="utf-8") as handle:
                written = json.load(handle)
            self.assertEqual(written["overall_status"], "pass_with_review")

    def test_duplicate_business_key_blocks_adoption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event, products, manifest, panel = self._write_fixture(root)
            with panel.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0])
            with panel.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writerow(rows[0])

            report, _, _, _ = audit_data_quality(
                event_path=event,
                products_path=products,
                manifest_path=manifest,
                panel_path=panel,
                expected_policy_count=2,
                expected_months=[(2018, 1), (2018, 2)],
            )
            self.assertEqual(report["overall_status"], "blocked")
            self.assertIn("KEY-001", report["summary"]["failed_rules"])

    def test_quality_mysql_sql_is_explicit_and_escapes_text(self):
        origins = [
            {
                "origin_code": "9999",
                "canonical_origin_name": "O'LAND",
                "observed_origin_names": "OLDLAND | O'LAND",
                "first_observed_month": "2018-01",
                "last_observed_month": "2018-02",
                "name_variant_count": "2",
                "canonical_name_method": "latest_observed_name",
                "quality_status": "review_name_change",
                "reference_url": "https://example.test/origins",
            }
        ]
        policy_origins = [
            {
                "policy_id": "fixture",
                "policy_target_origin_name": "Oldland",
                "origin_code": "9999",
                "canonical_origin_name": "O'LAND",
                "mapping_method": "fixture",
                "quality_status": "pass",
                "reference_url": "https://example.test/origins",
            }
        ]
        coverage = [
            {
                "policy_id": "fixture",
                "canonical_hts8": "90330090",
                "observed_trade_row_count": "2",
                "observed_month_count": "2",
                "first_observed_month": "2018-01",
                "last_observed_month": "2018-02",
                "total_import_value_consumption_usd": "200",
                "coverage_status": "observed",
                "policy_source_url": "https://example.test/policy",
                "classification_reference_url": "https://example.test/hts",
            }
        ]
        sql = build_load_sql(origins, policy_origins, coverage, replace=True)
        self.assertIn("DELETE FROM origin_dimension", sql)
        self.assertIn("INSERT INTO hts8_coverage", sql)
        self.assertIn(sql_text("O'LAND"), sql)
        self.assertTrue(sql.endswith("COMMIT;"))


if __name__ == "__main__":
    unittest.main()
