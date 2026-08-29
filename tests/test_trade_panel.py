import csv
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.build_trade_panel import month_range, month_source, process_archive
from scripts.inventory_census_import import EXPECTED_DETAIL_WIDTH


def detail_line(*, hts10: str, country_code: str, value: int) -> bytes:
    fields = [" "] * EXPECTED_DETAIL_WIDTH

    def put(start: int, end: int, text: str, *, right: bool = False) -> None:
        width = end - start
        fields[start:end] = (text.rjust(width) if right else text.ljust(width))

    put(0, 10, hts10)
    put(10, 14, country_code)
    put(22, 26, "2018")
    put(26, 28, "07")
    put(73, 88, str(value), right=True)
    return "".join(fields).encode("latin-1") + b"\n"


class TradePanelTests(unittest.TestCase):
    def test_month_range_and_url(self):
        sources = month_range((2018, 11), (2019, 2))
        self.assertEqual([(source.year, source.month) for source in sources], [
            (2018, 11),
            (2018, 12),
            (2019, 1),
            (2019, 2),
        ])
        self.assertEqual(
            month_source(2018, 7).url,
            "https://www.census.gov/trade/downloads/2018/Merch/im_m/IMDB1807.ZIP",
        )

    def test_process_archive_aggregates_to_product_origin_month(self):
        source = month_source(2018, 7)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / source.filename
            output = root / "trade_import_2018_07.csv"
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
                {"84119910"},
                output,
                "2026-08-29T00:00:00+00:00",
            )

            self.assertEqual(result["raw_detail_rows"], 3)
            self.assertEqual(result["matched_detail_rows"], 2)
            self.assertEqual(result["unique_product_origin_groups"], 1)
            self.assertEqual(result["total_consumption_value_usd"], 150)
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["import_value_consumption_usd"], "150")
            self.assertEqual(rows[0]["source_url"], source.url)
            self.assertEqual(rows[0]["source_file_name"], source.filename)
            self.assertTrue(rows[0]["source_sha256"])


if __name__ == "__main__":
    unittest.main()
