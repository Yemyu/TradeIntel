import csv
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_trade_panel import month_source
from extract_hts10_monthly import FIELDS, process_archive


def detail_line(hts10, country, year, month, value):
    chars = [" "] * 688
    chars[0:10] = list(hts10)
    chars[10:14] = list(country)
    chars[22:26] = list(str(year))
    chars[26:28] = list(f"{month:02d}")
    chars[73:88] = list(f"{value:15d}")
    return "".join(chars) + "\n"


def country_line(code, name):
    return code + "       " + name.ljust(50) + "\n"


class Hts10ExtractionTests(unittest.TestCase):
    def test_keeps_china_zero_when_code_only_other_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "IMDB1601.ZIP"
            with ZipFile(archive, "w", ZIP_DEFLATED) as z:
                z.writestr("COUNTRY.TXT", country_line("5700", "CHINA") + country_line("1000", "CANADA"))
                z.writestr("IMP_DETL.TXT", "".join([
                    detail_line("1234567890", "5700", 2016, 1, 7),
                    detail_line("1234567890", "1000", 2016, 1, 5),
                    detail_line("1234567891", "1000", 2016, 1, 3),
                ]))
            output = Path(tmp) / "out.csv"
            result = process_archive(archive, month_source(2016, 1), output, "test")
            self.assertTrue(result["raw_archive_retained_after_processing"] is True)
            with output.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(list(rows[0]), FIELDS)
            by_code = {row["hts10"]: row for row in rows}
            self.assertEqual(by_code["1234567890"]["china_import_value_consumption_usd"], "7")
            self.assertEqual(by_code["1234567891"]["china_import_value_consumption_usd"], "0")
            self.assertEqual(by_code["1234567891"]["china_observed"], "0")

    def test_rejects_wrong_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "IMDB1601.ZIP"
            with ZipFile(archive, "w", ZIP_DEFLATED) as z:
                z.writestr("COUNTRY.TXT", country_line("5700", "CHINA"))
                z.writestr("IMP_DETL.TXT", detail_line("1234567890", "5700", 2016, 2, 7))
            with self.assertRaises(Exception):
                process_archive(archive, month_source(2016, 1), Path(tmp) / "out.csv", "test")


if __name__ == "__main__":
    unittest.main()
