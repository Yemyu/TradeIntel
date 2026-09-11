import sys
import unittest
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from tradeintel_ai.policy_context_window import expand_context


class ContextTests(unittest.TestCase):
    def fixture(self):
        text='x'*4000
        c={'id':'a','page_id':'p','start':1000,'end':2200,'text':text[1000:2200]}
        d={'id':'b','page_id':'p','start':1850,'end':3050,'text':text[1850:3050]}
        return {'hits':[deepcopy(c)],'status':'candidate_evidence'},{'pages':[{'id':'p','text':text}],'chunks':[c,d]}
    def test_clamp_to_indexed_text_and_preserve_original(self):
        r,c=self.fixture();new=expand_context(r,c)
        self.assertEqual(new['hits'][0]['start'],1000)
        self.assertEqual(new['hits'][0]['end'],2800)
        self.assertEqual(r['hits'][0]['end'],2200)
    def test_tampered_source_rejected(self):
        r,c=self.fixture();r['hits'][0]['text']='bad'
        with self.assertRaises(ValueError):expand_context(r,c)
    def test_no_hits_stays_empty(self):
        r,c=self.fixture();r['hits']=[]
        self.assertEqual(expand_context(r,c)['hits'],[])
    def test_budget_and_no_extra_hits(self):
        r,c=self.fixture();r['hits']*=4
        with self.assertRaises(ValueError):expand_context(r,c)
