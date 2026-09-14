import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_policy_exposure_report import build_report, render_markdown


class PolicyExposureReportTests(unittest.TestCase):
    def test_report_aggregates_target_share_and_top_origins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = root / "event.csv"
            event.write_text(
                "policy_id,policy_name,importer,target_origin,announcement_date,effective_date,source_url,implementation_source_url,scope_note\n"
                "p,Test policy,United States,China,2024-12-16,2025-01-01,https://example/p,https://example/i,scope\n",
                encoding="utf-8",
            )
            products = root / "products.csv"
            products.write_text(
                "policy_id,canonical_hts8,product_description,product_description_zh,additional_rate_percent\n"
                "p,12345678,Test product,测试商品,25\n",
                encoding="utf-8",
            )
            rows = root / "rows.csv"
            with rows.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "policy_id", "year", "month", "canonical_hts8", "hts10",
                        "origin_code", "origin_name", "import_value_consumption_usd",
                        "detail_row_count", "source_sha256",
                    ],
                )
                writer.writeheader()
                writer.writerows([
                    {"policy_id": "p", "year": 2026, "month": 7, "canonical_hts8": "12345678", "hts10": "1234567800", "origin_code": "5700", "origin_name": "CHINA", "import_value_consumption_usd": 20, "detail_row_count": 1, "source_sha256": "abc"},
                    {"policy_id": "p", "year": 2026, "month": 7, "canonical_hts8": "12345678", "hts10": "1234567800", "origin_code": "2010", "origin_name": "MEXICO", "import_value_consumption_usd": 80, "detail_row_count": 1, "source_sha256": "abc"},
                ])
            report = build_report(event, products, rows)
            self.assertEqual(report["overall"]["import_value_consumption_usd"], 100)
            self.assertEqual(report["overall"]["target_origin_value_usd"], 20)
            self.assertEqual(report["overall"]["target_origin_share_percent"], 20.0)
            self.assertEqual(report["products"][0]["top_origins"][0]["origin_name"], "MEXICO")
            self.assertIn("测试商品", render_markdown(report))

    def test_report_rejects_mixed_source_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = root / "event.csv"
            event.write_text(
                "policy_id,policy_name,importer,target_origin,announcement_date,effective_date,source_url,implementation_source_url,scope_note\n"
                "p,Test,United States,China,2024-12-16,2025-01-01,u,i,s\n",
                encoding="utf-8",
            )
            products = root / "products.csv"
            products.write_text(
                "policy_id,canonical_hts8,product_description,additional_rate_percent\n"
                "p,12345678,test,25\n", encoding="utf-8"
            )
            rows = root / "rows.csv"
            rows.write_text(
                "policy_id,year,month,canonical_hts8,origin_name,import_value_consumption_usd,source_sha256\n"
                "p,2026,7,12345678,CHINA,1,a\n"
                "p,2026,7,12345678,MEXICO,1,b\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                build_report(event, products, rows)


if __name__ == "__main__":
    unittest.main()
