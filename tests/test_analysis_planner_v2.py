import json
import unittest
from unittest.mock import Mock,patch
from src.tradeintel_ai.analysis_planner_v2 import AnalysisPlannerV2, PLAN_PROMPT_V2
from tests.test_analysis_planner import step


def build(text, **extras):
    m=Mock(complete=Mock(return_value={'text':text,'metadata':{'finish_reason':'stop'},**extras}))
    return AnalysisPlannerV2(m),m


class PlannerV2Tests(unittest.TestCase):
    def test_whole_fence_and_confirmation(self):
        text=json.dumps(dict(status='plan',steps=[step('policy'),step('quality')],missing=[]))
        f,m=build('```json\n'+text+'\n```')
        with patch('src.tradeintel_ai.analysis_planner.execute_request',return_value={'status':'evidence_ready','response':'test'}) as ex:
            p=f.propose('政策与质量');ex.assert_not_called()
            self.assertEqual(p['status'],'needs_confirmation')
            self.assertEqual(p['format_transformations'],['whole_json_fence_removed'])
            p['steps'][0]['request']['task']='counts'
            r=f.confirm(p['confirmation_token']);self.assertEqual(r['status'],'evidence_ready')
            self.assertEqual(ex.call_args_list[0].args[0],{'task':'policy'})
            self.assertEqual(f.confirm(p['confirmation_token'])['status'],'confirmation_rejected')
        m.complete.assert_called_once()
        self.assertEqual(m.complete.call_args.kwargs['messages'][0]['content'],PLAN_PROMPT_V2)
        self.assertEqual(m.complete.call_args.kwargs['tools'],[])

    def test_missing_and_forged_evidence_never_filled(self):
        for evidence in ({},{'task':'不存在'}):
            s=step('policy');s['evidence']=evidence
            f,_=build(json.dumps(dict(status='plan',steps=[s],missing=[])))
            self.assertEqual(f.propose('政策与质量')['status'],'needs_review')

    def test_only_top_level_clarification(self):
        c=dict(status='clarify',request=None,evidence={},missing=['months'])
        f,_=build(json.dumps(dict(status='plan',steps=[c],missing=[])))
        self.assertEqual(f.propose('政策与质量')['status'],'needs_review')
        f,_=build(json.dumps(dict(status='clarify',steps=[],missing=['months'])))
        self.assertEqual(f.propose('政策与质量')['status'],'needs_clarification')

    def test_invalid_json_and_extra_commentary_rejected(self):
        text=json.dumps(dict(status='plan',steps=[step('policy')],missing=[]))
        for raw in ['解释\n```json\n'+text+'\n```',text.replace('"plan"','"plan", "status":"plan"'),
                    '{"status":"clarify","steps":[],"missing":[NaN]}']:
            f,_=build(raw);self.assertEqual(f.propose('政策与质量')['status'],'needs_review')

    def test_extra_tool_and_truncated_response_rejected(self):
        text=json.dumps(dict(status='plan',steps=[step('policy')],missing=[]))
        for extras in ({'metadata':{'finish_reason':'length'}},{'tool_calls':[{'name':'delete','arguments':{}}]}):
            f,_=build(text,**extras)
            self.assertEqual(f.propose('政策与质量')['status'],'needs_review')

    def test_cancel_invalidates_token(self):
        f,_=build(json.dumps(dict(status='plan',steps=[step('policy')],missing=[])))
        p=f.propose('政策与质量');f.cancel()
        self.assertEqual(f.confirm(p['confirmation_token'])['status'],'confirmation_rejected')
