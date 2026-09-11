import json
import unittest
from unittest.mock import Mock
from src.tradeintel_ai.analysis_planner_v3 import AnalysisPlannerV3,normalize_aliases
from tests.test_analysis_planner import step


def model(obj):return Mock(complete=Mock(return_value={'text':json.dumps(obj),'metadata':{'finish_reason':'stop'}}))

class V3Tests(unittest.TestCase):
    def test_accept_requires_confirmation(self):
        f=AnalysisPlannerV3(model(dict(status='plan',steps=[step('policy')],missing=[])),
                           model(dict(verdict='accept',issue='none',quote='')))
        p=f.propose('政策与质量')
        self.assertEqual(p['status'],'needs_confirmation');self.assertFalse(p['coverage_verified'])
        self.assertEqual(p['model_calls'],2)

    def test_reviewer_can_cancel_but_never_rewrite(self):
        for verdict in ('clarify','reject'):
            f=AnalysisPlannerV3(model(dict(status='plan',steps=[step('policy')],missing=[])),
                               model(dict(verdict=verdict,issue='coverage',quote='政策与质量')))
            p=f.propose('政策与质量')
            self.assertNotIn('confirmation_token',p);self.assertNotIn('steps',p)
            self.assertEqual(f.confirm('anything')['status'],'confirmation_rejected')

    def test_malformed_review_fails_closed(self):
        f=AnalysisPlannerV3(model(dict(status='plan',steps=[step('policy')],missing=[])),
                           model(dict(verdict='accept',issue='none',quote='',request={'task':'delete'})))
        self.assertEqual(f.propose('政策与质量')['status'],'needs_review')

    def test_alias_never_changes_unknown_or_forged_evidence(self):
        for value,quote,expected in [('只读查询','只读查询','read'),('删除','删除','删除'),
                                     ('只读查询','不存在','只读查询')]:
            obj={'steps':[{'request':{'task':'trade','request':{'operation':value,'origin':'Germany'}},
                           'evidence':{'request.operation':quote}}]}
            raw={'text':json.dumps(obj),'metadata':{'finish_reason':'stop'}}
            r,_=normalize_aliases(raw,'只读查询或者删除')
            fields=json.loads(r.text)['steps'][0]['request']['request']
            self.assertEqual(fields['operation'],expected);self.assertEqual(fields['origin'],'Germany')
