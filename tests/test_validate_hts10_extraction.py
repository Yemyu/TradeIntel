import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_hts10_extraction import check_rows


class RowValidationTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(source_url="example", source_file_name="example.zip", source_sha256="hash")
        self.row = dict(self.source, hts10="0123456789", hts8="01234567", year="2016", month="1",
                        china_import_value_consumption_usd="0", all_origin_import_value_consumption_usd="5",
                        china_detail_row_count="1", all_origin_detail_row_count="2",
                        china_observed="1", all_origin_observed="1")

    def test_observed_zero_valid(self):
        check_rows([self.row], (2016, 1), self.source)

    def test_duplicate_rejected_even_if_totals_match_elsewhere(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            check_rows([self.row, self.row], (2016, 1), self.source)

    def test_bad_date_source_and_observation_rejected(self):
        for field, value in [("month", "2"), ("source_sha256", "changed"), ("china_observed", "0")]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_rows([dict(self.row, **{field:value})], (2016, 1), self.source)
