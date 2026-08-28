"""Acceptance checks for the stage 0 CSV example."""

import unittest

from src.phase_00_read_csv import (
    DATA_FILE,
    calculate_total_trade_value,
    load_trade_rows,
)


class Phase00CsvTests(unittest.TestCase):
    def test_sample_has_six_rows(self) -> None:
        rows = load_trade_rows(DATA_FILE)
        self.assertEqual(len(rows), 6)

    def test_sample_total_is_expected_value(self) -> None:
        rows = load_trade_rows(DATA_FILE)
        self.assertEqual(calculate_total_trade_value(rows), 605_000)


if __name__ == "__main__":
    unittest.main()
