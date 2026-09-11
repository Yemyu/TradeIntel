import csv
from pathlib import Path
import tempfile
import unittest
from scripts.prepare_preannouncement_candidates import MONTHS, read_panel, build_features, compare_rows, prepare


class PreannouncementTests(unittest.TestCase):
    def fixture(self, path, *, extra=None, blank=False):
        with path.open('w', newline='') as handle:
            w = csv.writer(handle)
            w.writerow(['year','month','hs6_2017','china_import_value_consumption_usd','all_origin_import_value_consumption_usd'])
            for y,m in MONTHS:
                w.writerow([y,m,'123456','' if blank else 10,20])
            if extra:
                w.writerow(extra)

    def test_announcement_amounts_never_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'input.csv'; self.fixture(p,extra=[2018,3,'123456','INVALID','INVALID'])
            panel, totals, positive = read_panel(p)
            self.assertEqual(totals['123456'],260)
            self.assertEqual(len(positive['123456']),26)
            self.assertEqual(len(panel['123456']),26)

    def test_missing_not_zero_filled(self):
        row = {'hs6_2017':'123456','primary_role':'control_candidate','naics3_candidates':'333'}
        values = {m:(0,2) for m in MONTHS[1:]}
        result = build_features(row,values)
        self.assertEqual(result['feature_status'],'blocked_missing_months')
        self.assertNotIn('pretrend_slope',result)

    def test_complete_zero_series_preserved(self):
        row = {'hs6_2017':'123456','primary_role':'control_candidate','naics3_candidates':'333'}
        result = build_features(row,{m:(0,2) for m in MONTHS})
        self.assertEqual(result['feature_status'],'computed')
        self.assertEqual(result['mean_china_import_value_usd'],0)
        self.assertFalse(result['causal_adopted'])

    def test_blank_and_duplicate_fail(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'input.csv'
            self.fixture(p,blank=True)
            with self.assertRaises(ValueError):read_panel(p)
            self.fixture(p,extra=[2016,1,'123456',10,20])
            with self.assertRaises(ValueError):read_panel(p)

    def test_old_new_union_keeps_removed_candidates(self):
        diff = compare_rows([{'hs6_2017':'b','primary_role':'treated_candidate'}],{'a':{'primary_role':'control_candidate'}})
        self.assertEqual([r['hs6_2017'] for r in diff],['a','b'])
        self.assertTrue(all(r['role_changed'] for r in diff))

    def test_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):prepare(Path(d))
