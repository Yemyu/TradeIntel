import unittest
from scripts.audit_proposal_scope import code_rows,validate_codes,correction_events


class ProposalScopeTests(unittest.TestCase):
    def test_strict_lines_do_not_swallow_attached_digits(self):
        rows=code_rows(['84223091..... text\n8422309100000000 text\nnot a code'],0,1)
        self.assertEqual([r['hts8'] for r in rows],['84223091'])

    def test_requires_full_unique_list(self):
        with self.assertRaises(ValueError):validate_codes([{'hts8':'12345678'}]*1333,set())

    def test_requires_final_subset(self):
        rows=[{'hts8':f'{i:08d}'} for i in range(1333)]
        with self.assertRaises(ValueError):validate_codes(rows,{f'{i:08d}' for i in range(818)}-{'00000001'}|{'99999999'})
        self.assertEqual(len(validate_codes(rows,{f'{i:08d}' for i in range(818)})),1333)

    def test_corrections_keep_publication_separate(self):
        text=' '.join(f'U.S. note 20(m)({n}) is modified by deleting “{old}” and inserting “8504.40.4000”' for n,old in [('53','8404.40.4000'),('54','8504.40.0000')])
        events=correction_events(text)
        self.assertEqual(len(events),2)
        self.assertNotEqual(events[0]['publication_date'],events[0]['retroactive_effective_date'])
        self.assertTrue(events[0]['description_conditions_still_required'])

    def test_cannot_infer_correction_from_code_mentions(self):
        with self.assertRaises(ValueError):correction_events('8404.40.4000 8504.40.0000 8504.40.4000')
