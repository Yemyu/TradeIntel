import unittest
from src.tradeintel_ai.analysis_planner_v4 import AnalysisPlannerV4
from tests.test_analysis_planner_v3 import model
from tests.test_analysis_planner import step


class V4Tests(unittest.TestCase):
    def test_specific_fields_and_no_confirmation(self):
        q='政策与质量，月份和基准未定'
        f=AnalysisPlannerV4(model(dict(status='plan',steps=[step('policy')],missing=[])),model(
            dict(verdict='clarify',issue='scope',quote='月份和基准未定',missing=[
                {'field':'months','quote':'月份和基准未定'},{'field':'comparison_id','quote':'月份和基准未定'}])))
        r=f.propose(q)
        self.assertEqual(r['clarification_fields'],['months','comparison_id'])
        self.assertIn('年份和月份',r['response']);self.assertIn('比较基准',r['response'])
        self.assertNotIn('confirmation_token',r);self.assertFalse(r['executed'])

    def test_planner_clarification_is_also_reviewed(self):
        f=AnalysisPlannerV4(model(dict(status='clarify',steps=[],missing=['origin'])),model(
            dict(verdict='clarify',issue='scope',quote='国家还没选',missing=[{'field':'origin','quote':'国家还没选'}])))
        r=f.propose('国家还没选');self.assertEqual(r['clarification_fields'],['origin'])
        self.assertEqual(r['model_calls'],2)

    def test_unknown_duplicate_forged_fields_rejected(self):
        for entries in [[{'field':'sql','quote':'政策与质量'}],[{'field':'months','quote':'不存在'}],
                        [{'field':'months','quote':'政策与质量'}]*2]:
            f=AnalysisPlannerV4(model(dict(status='plan',steps=[step('policy')],missing=[])),model(
                dict(verdict='clarify',issue='scope',quote='政策与质量',missing=entries)))
            r=f.propose('政策与质量');self.assertEqual(r['status'],'needs_review');self.assertNotIn('confirmation_token',r)

    def test_reviewer_cannot_accept_empty_plan(self):
        f=AnalysisPlannerV4(model(dict(status='clarify',steps=[],missing=['origin'])),model(
            dict(verdict='accept',issue='none',quote='',missing=[])))
        self.assertEqual(f.propose('查询')['status'],'needs_review')
