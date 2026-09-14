import csv
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_trade_panel import month_source
from extract_policy_case_monthly import FIELDS, load_policy_scope, process_archive


def detail_line(hts10, country, year, month, value):
    chars = [" "] * 688
    chars[0:10] = list(hts10)
    chars[10:14] = list(country)
    chars[22:26] = list(str(year))
    chars[26:28] = list(f"{month:02d}")
    chars[73:88] = list(f"{value:15d}")
    return "".join(chars) + "\n"


class PolicyCaseExtractionTests(unittest.TestCase):
    def test_scope_rejects_duplicate_or_bad_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "products.csv"
            path.write_text(
                "policy_id,canonical_hts8,product_description,effective_date\n"
                "p,1234567,bad,2025-01-01\n", encoding="utf-8"
            )
            with self.assertRaises(Exception):
                load_policy_scope(path)

    def test_process_keeps_each_origin_and_ignores_out_of_scope(self):
        source = month_source(2026, 7)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / source.filename
            with ZipFile(archive, "w", ZIP_DEFLATED) as z:
                z.writestr("COUNTRY.TXT", "5700       CHINA                                             \n2010       MEXICO                                            \n")
                z.writestr("IMP_DETL.TXT", "".join([
                    detail_line("2804610000", "5700", 2026, 7, 100),
                    detail_line("2804610000", "2010", 2026, 7, 50),
                    detail_line("3818000010", "2010", 2026, 7, 9),
                    detail_line("9999999999", "5700", 2026, 7, 999),
                ]))
            output = root / "out.csv"
            result = process_archive(
                archive, source, policy_id="p", policy_codes={"28046100", "38180000"},
                output_path=output, retrieved_at_utc="test",
            )
            self.assertEqual(result["matched_detail_rows"], 3)
            self.assertEqual(result["unique_origin_count"], 2)
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(list(rows[0]), FIELDS)
            self.assertEqual(sum(int(row["import_value_consumption_usd"]) for row in rows), 159)
            self.assertEqual({row["origin_name"] for row in rows}, {"CHINA", "MEXICO"})


if __name__ == "__main__":
    unittest.main()
