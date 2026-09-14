import unittest
from scripts.review_exposure_code_transition import check_transition


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.before = {'3818000010': 10, '3818000020': 20, '3818000030': 30, '3818000095': 40}
        self.after = {'3818000010': 10, '3818000020': 20, '3818000030': 30, '3818000095': 0,
                      '3818000040': 10, '3818000045': 10, '3818000050': 10, '3818000091': 10}

    def test_split_does_not_create_growth(self):
        self.assertEqual(check_transition(self.before, self.after)['change_percent'], 0)

    def test_missing_successor_or_nonzero_retired_code_stops(self):
        missing = dict(self.after)
        del missing['3818000040']
        for bad in (missing, {**self.after, '3818000095': 2}):
            with self.assertRaises(ValueError):
                check_transition(self.before, bad)
