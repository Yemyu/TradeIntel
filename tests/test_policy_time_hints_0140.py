import unittest
from copy import deepcopy
from tradeintel_ai.policy_time_hints import annotate_clock_times


class ClockHintTests(unittest.TestCase):
    def test_midnight_noon_and_other_hours_preserve_source(self):
        for text, expected in [('12:01 a.m.', '00:01'), ('12:00 p.m.', '12:00'),
                               ('1:09 PM', '13:09'), ('11:59 am', '11:59'),
                               ('12:00\na.m.', '00:00')]:
            with self.subTest(text=text):
                original = [{'id': 's', 'text': 'Before ' + text + ' eastern daylight time.'}]
                saved = deepcopy(original)
                out = annotate_clock_times(original)
                hint = out[0]['derived_clock_hints'][0]
                self.assertEqual(hint['clock_24h'], expected)
                self.assertEqual(hint['source_quote'], out[0]['text'][hint['start']:hint['end']])
                self.assertEqual(hint['source_id'], 's')
                self.assertFalse(hint['timezone_conversion'])
                self.assertEqual(original, saved)
                self.assertEqual(out[0]['text'], saved[0]['text'])

    def test_no_invented_times_and_untrusted_hints_removed(self):
        for text in ('13:01 a.m.', '00:01 a.m.', '12:61 pm', '112:01 am',
                     '12:01', '12:01 amount', 'July 6, 2018', ''):
            with self.subTest(text=text):
                out = annotate_clock_times([{'id': 's', 'text': text,
                                              'derived_clock_hints': ['untrusted']}])
                self.assertNotIn('derived_clock_hints', out[0])
        self.assertEqual(annotate_clock_times([]), [])

    def test_repeat_occurrences_have_distinct_spans(self):
        text = '12:01 a.m. and 12:01 a.m.'
        hints = annotate_clock_times([{'id': 's', 'text': text}])[0]['derived_clock_hints']
        self.assertEqual(len(hints), 2)
        self.assertNotEqual(hints[0]['start'], hints[1]['start'])
