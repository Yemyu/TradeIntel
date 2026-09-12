"""Offline counterexamples: lossless audit is not semantic acceptance."""
from copy import deepcopy
import unittest

from tradeintel_ai.quote_gap_audit import audit_quote_gaps
from tradeintel_ai.request_coverage import materialize_units


def units(*quotes):
    return [dict(quote=q, kind='request', target='policy') for q in quotes]


class QuoteGapAuditTests(unittest.TestCase):
    def test_host_gaps_are_lossless_unclassified_non_executable(self):
        q = '查日期；查税率，不做因果。'
        source = units('查日期', '查税率', '不做因果')
        before = deepcopy(source)
        result = audit_quote_gaps(source, q)
        self.assertEqual(''.join(s['quote'] for s in result['segments']), q)
        self.assertEqual(source, before)
        self.assertEqual(result['status'], 'review_required')
        self.assertFalse(result['executable'])
        self.assertFalse(result['semantic_coverage_verified'])
        self.assertFalse(result['model_literal_coverage_complete'])
        cursor = 0
        for segment in result['segments']:
            self.assertEqual(segment['start'], cursor)
            self.assertEqual(q[segment['start']:segment['end']], segment['quote'])
            cursor = segment['end']
            if segment['source'] == 'host_gap':
                self.assertNotIn('kind', segment)
                self.assertNotIn('target', segment)
                self.assertEqual(segment['semantic_disposition'], 'unreviewed')
        self.assertEqual(cursor, len(q))
        result['model_units'][0]['quote'] = 'mutated'
        self.assertEqual(source, before)
        with self.assertRaises(ValueError):
            materialize_units(source, q)  # The existing execution gate is unchanged.

    def test_separators_whitespace_and_exact_original_are_reconstructible(self):
        for separator in ['，', '；', '。', '；\n ', ' ，； ', '\t', '\n', '']:
            for tail in ['', '。', ' \n']:
                with self.subTest(separator=separator, tail=tail):
                    q = '查日期' + separator + '查税率' + tail
                    result = audit_quote_gaps(units('查日期', '查税率'), q)
                    self.assertEqual(''.join(s['quote'] for s in result['segments']), q)
                    self.assertFalse(result['executable'])

    def test_missing_content_and_unsafe_punctuation_rejected(self):
        cases = [
            ('查询；不要估计因果', ('查询', '要估计因果')),
            ('查询；另列中国份额', ('查询',)),
            ('金额1.5', ('金额1', '5')),
            ('年份2018-2019', ('年份2018', '2019')),
            ('金额1,000', ('金额1', '000')),
            ('金额1，000', ('金额1', '000')),
            ('金额一，五', ('金额一', '五')),
            ('查日期？查税率', ('查日期', '查税率')),
            ('“中国；其他”', ('中国', '其他')),
            ('查询（中国）；日期', ('查询（中国）', '日期')),
            ('；查询', ('查询',)),
            ('查询\u200b；日期', ('查询', '日期')),
            ('先查日期再查日期', ('查日期', '查日期')),
            ('日期；税率', ('税率', '日期')),
        ]
        for q, quotes in cases:
            with self.subTest(q=q), self.assertRaises(ValueError):
                audit_quote_gaps(units(*quotes), q)

    def test_semantic_misclassification_is_not_declared_correct(self):
        source = [dict(quote='不做因果。', kind='context', target='none')]
        result = audit_quote_gaps(source, '不做因果。')
        self.assertEqual(result['status'], 'literal_complete')
        self.assertFalse(result['semantic_coverage_verified'])
        self.assertFalse(result['executable'])

    def test_invalid_types_labels_and_added_provenance_rejected(self):
        for source in [None, [], [None], units('日期') * 101,
                       [dict(quote='日期', kind='request', target='none')],
                       [dict(quote='日期', kind='unknown', target='policy')],
                       [dict(quote='日期', kind='request', target='policy', source='host_gap')]]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                audit_quote_gaps(source, '日期')


if __name__ == '__main__':
    unittest.main()
