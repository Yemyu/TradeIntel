import copy
import unittest

from src.tradeintel_ai.policy_review_report import render_policy_review


class PolicyReviewReportTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {'hits': [
            {'id': 'fixture:p2', 'text': 'Entered at 12:07 a.m. eastern standard time.\nExcept widgets.',
             'citation_url': 'https://example.test/notice', 'published': '2025-02-03'},
            {'id': 'fixture:p8', 'text': 'Additional conditions.',
             'citation_url': 'https://example.test/notice'}], 'as_of': '2026-01-01'}
        self.claims = [{'text': '待核查的模型说明。', 'citations': ['fixture:p2']}]

    def test_original_conditions_and_clock_are_visible_without_mutation(self):
        before = copy.deepcopy(self.evidence)
        report = '\n'.join(render_policy_review(self.claims, self.evidence))
        self.assertIn('> Except widgets.', report)
        self.assertIn('`00:07`', report)
        self.assertIn('eastern standard time', report)
        self.assertIn('2025-02-03', report)
        self.assertIn('fixture:p8', report)
        self.assertIn('尚未完成语义审阅', report)
        self.assertEqual(before, self.evidence)

    def test_missing_and_duplicate_sources_fail(self):
        with self.assertRaises(KeyError):
            render_policy_review([{'text': 'x', 'citations': ['missing']}], self.evidence)
        self.evidence['hits'].append(self.evidence['hits'][0])
        with self.assertRaises(ValueError):
            render_policy_review(self.claims, self.evidence)

    def test_supplied_clock_annotations_are_not_trusted(self):
        self.evidence['hits'][0]['derived_clock_hints'] = [{'clock_24h': '19:99'}]
        report = '\n'.join(render_policy_review(self.claims, self.evidence))
        self.assertNotIn('19:99', report)
        self.assertIn('00:07', report)
