from copy import deepcopy
from pathlib import Path
import unittest
from tradeintel_ai.solar_policy import build_corpus
from tradeintel_ai.solar_fact_sheet import build_fact_sheet, render_fact_sheet, inspect_clock_conflicts

class FactSheetTests(unittest.TestCase):
    def evidence(self):
        corpus=build_corpus(Path(__file__).resolve().parents[1])
        return {'policy_id':corpus['policy_id'],'hits':corpus['chunks']}
    def test_source_and_render(self):
        sheet=build_fact_sheet(self.evidence(),'test-version')
        self.assertEqual(sheet['clock_24h'],'00:01')
        self.assertFalse(sheet['model_generated'])
        self.assertIn('不代表综合税率','\n'.join(render_fact_sheet(sheet)))
    def test_source_changes_rejected(self):
        for old,new in [('2024','2023'),('50%.','60%.')]:
            evidence=deepcopy(self.evidence())
            for hit in evidence['hits']: hit['text']=hit['text'].replace(old,new)
            with self.assertRaises(ValueError): build_fact_sheet(evidence,'v')
        with self.assertRaises(ValueError): build_fact_sheet(self.evidence(),None)
    def test_conflicts_do_not_rewrite(self):
        sheet=build_fact_sheet(self.evidence(),'v')
        claims=[{'text':'美国东部夏令时上午12:01起'}, {'text':'时间为01:01'}]
        original=deepcopy(claims)
        self.assertEqual(len(inspect_clock_conflicts(claims,sheet)['conflicts']),2)
        self.assertEqual(claims,original)
        result=inspect_clock_conflicts([{'text':'美国东部夏令时00:01'}],sheet)
        self.assertFalse(result['semantic_approval'])
        self.assertEqual(result['status'],'manual_review_required')
