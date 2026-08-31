import csv
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.build_causal_trade_panel import process_archive
from scripts.build_trade_panel import month_source
from scripts.inventory_census_import import EXPECTED_DETAIL_WIDTH


def detail_line(*, hts10: str, country_code: str, value: int) -> bytes:
    fields = [" "] * EXPECTED_DETAIL_WIDTH

    def put(start: int, end: int, text: str, *, right: bool = False) -> None:
        width = end - start
        fields[start:end] = text.rjust(width) if right else text.ljust(width)

    put(0, 10, hts10)
    put(10, 14, country_code)
    put(22, 26, "2018")
    put(26, 28, "07")
    put(73, 88, str(value), right=True)
    return "".join(fields).encode("latin-1") + b"\n"


class CausalTradePanelTests(unittest.TestCase):
    def test_process_archive_aggregates_all_origins_and_excludes_ambiguous_codes(self):
        source = month_source(2018, 7)
        mapping = {
            "8411991010": {
                "hs6_2017": "841199",
                "mapping_status": "same_hs6_prefix",
                "historical_validity_status": "valid",
            },
            "9999999999": {
                "hs6_2017": "",
                "mapping_status": "wco_partial_or_ambiguous",
                "historical_validity_status": "valid",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / source.filename
            output = root / "causal_trade_hs6_2018_07.csv"
            country_content = (
                "5700       CHINA                                             \n"
                "2010       MEXICO                                            \n"
            ).encode("latin-1")
            with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
                zip_file.writestr("COUNTRY.TXT", country_content)
                zip_file.writestr(
                    "IMP_DETL.TXT",
                    b"".join(
                        [
                            detail_line(
                                hts10="8411991010", country_code="5700", value=100
                            ),
                            detail_line(
                                hts10="8411991010", country_code="2010", value=50
                            ),
                            detail_line(
                                hts10="8411991010", country_code="5700", value=50
                            ),
                            detail_line(
                                hts10="9999999999", country_code="2010", value=999
                            ),
                        ]
                    ),
                )

            result = process_archive(
                archive,
                source,
                mapping,
                output,
                "2026-08-31T00:00:00+00:00",
            )

            self.assertEqual(result["raw_detail_rows"], 4)
            self.assertEqual(result["unique_hts10_count"], 2)
            self.assertEqual(result["raw_all_origin_value_usd"], 1199)
            self.assertEqual(result["raw_china_value_usd"], 150)
            self.assertEqual(result["mapped_all_origin_value_usd"], 200)
            self.assertEqual(result["mapped_china_value_usd"], 150)
            self.assertEqual(result["excluded_hts10_count_by_reason"]["wco_partial_or_ambiguous"], 1)
            self.assertAlmostEqual(result["china_mapping_coverage"], 1.0)

            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["hs6_2017"], "841199")
            self.assertEqual(rows[0]["china_import_value_consumption_usd"], "150")
            self.assertEqual(rows[0]["all_origin_import_value_consumption_usd"], "200")
            self.assertEqual(rows[0]["china_share"], "0.750000000000")

    def test_full_panel_manifest_and_report_cover_the_frozen_48_month_scope(self):
        root = Path(__file__).resolve().parents[1]
        report_path = root / "data/processed/causal/causal_trade_panel_report.json"
        manifest_path = root / "data/processed/causal/causal_trade_panel_manifest.json"
        self.assertTrue(report_path.exists())
        self.assertTrue(manifest_path.exists())

        report = json.loads(report_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "all_origin_hs6_panel_built")
        self.assertEqual(
            report["source_scope"],
            {
                "start": "2016-01",
                "end": "2019-12",
                "month_count": 48,
                "all_origins_read": True,
                "china_origin_code": "5700",
            },
        )
        self.assertEqual(report["outputs"]["combined_rows"], 245388)
        self.assertEqual(len(manifest["months"]), 48)
        self.assertEqual(
            len({(row["year"], row["month"]) for row in manifest["months"]}), 48
        )
        self.assertTrue(all(row["source_sha256"] for row in manifest["months"]))
        self.assertTrue(
            all(row["status"] == "processed" for row in manifest["months"])
        )


if __name__ == "__main__":
    unittest.main()
