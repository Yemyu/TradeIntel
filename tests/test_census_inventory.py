import io
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from scripts.inventory_census_import import (
    EXPECTED_DETAIL_WIDTH,
    InventoryError,
    load_country_names,
    parse_detail_line,
)


def fixed_width_detail_line(
    *,
    hts10: str = "8411991010",
    country_code: str = "5700",
    year: str = "2018",
    month: str = "07",
    value: int = 12345,
) -> bytes:
    fields = [" "] * EXPECTED_DETAIL_WIDTH

    def put(start: int, end: int, value_text: str, *, right: bool = False) -> None:
        width = end - start
        if len(value_text) > width:
            raise ValueError(value_text)
        padded = value_text.rjust(width) if right else value_text.ljust(width)
        fields[start:end] = padded

    put(0, 10, hts10)
    put(10, 14, country_code)
    put(22, 26, year)
    put(26, 28, month)
    put(73, 88, str(value), right=True)
    return "".join(fields).encode("latin-1") + b"\n"


class CensusInventoryTests(unittest.TestCase):
    def test_parse_fixed_width_detail_line(self):
        record = parse_detail_line(
            fixed_width_detail_line(value=987654), line_number=1
        )
        self.assertEqual(record.hts10, "8411991010")
        self.assertEqual(record.hts8, "84119910")
        self.assertEqual(record.country_code, "5700")
        self.assertEqual(record.year, 2018)
        self.assertEqual(record.month, 7)
        self.assertEqual(record.consumption_value_usd, 987654)

    def test_rejects_wrong_record_width(self):
        with self.assertRaises(InventoryError):
            parse_detail_line(b"too short\n", line_number=4)

    def test_load_country_names_uses_fixed_width_fields(self):
        content = (
            "5700          CHINA                                             \n"
            "2010          MEXICO                                            \n"
        ).encode("latin-1")
        memory = io.BytesIO()
        with ZipFile(memory, "w", ZIP_DEFLATED) as zip_file:
            zip_file.writestr("COUNTRY.TXT", content)
        with ZipFile(io.BytesIO(memory.getvalue())) as zip_file:
            names = load_country_names(zip_file)
        self.assertEqual(names["5700"], "CHINA")
        self.assertEqual(names["2010"], "MEXICO")


if __name__ == "__main__":
    unittest.main()
