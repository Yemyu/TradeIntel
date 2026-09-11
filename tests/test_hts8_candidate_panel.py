import csv
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_hts8_candidate_panel import observation_status


class Hts8MissingnessTests(unittest.TestCase):
    def test_missing_is_distinct_from_observed_zero(self):
        self.assertEqual(observation_status(True, True, 0), "observed_zero")
        self.assertEqual(observation_status(True, False, 0), "no_china_record")
        self.assertEqual(observation_status(False, False, 0), "no_all_origin_record")

    def test_real_v2_missing_values_are_empty_and_qualification_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        path = root / 'data/processed/trade_hts8/monthly/hts8_candidates_prepolicy_v2.csv'
        if not path.exists():
            self.skipTest('Local generated panel is absent')
        with path.open(newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), len({(r['year'],r['month'],r['hts8']) for r in rows}))
        for row in rows:
            if row['china_observed'] == '0':
                self.assertEqual(row['china_import_value_consumption_usd'], '')
            elif row['observation_status'] == 'observed_zero':
                self.assertEqual(row['china_import_value_consumption_usd'], '0')
        q = root / 'data/processed/causal'
        with (q/'hts8_candidate_qualification.csv').open() as a, (q/'hts8_candidate_qualification_v2.csv').open() as b:
            self.assertEqual(list(csv.DictReader(a)), list(csv.DictReader(b)))
