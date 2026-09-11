import json
import unittest
from unittest.mock import Mock,patch
from src.tradeintel_ai.analysis_planner import AnalysisPlanner


def step(task):
    return dict(status='proposal',request={'task':task},evidence={'task':'政策与质量'},missing=[])


def planner(steps):
    m=Mock(complete=Mock(return_value={'text':json.dumps(dict(status='plan',steps=steps,missing=[])),
                                     'metadata':{'finish_reason':'stop'}}))
    return AnalysisPlanner(m)


class PlannerTests(unittest.TestCase):
    def test_two_tasks_real_evidence_and_one_model_call(self):
        f=planner([step('policy'),step('quality')]);p=f.propose('政策与质量')
        self.assertEqual(p['status'],'needs_confirmation')
        p['steps'][0]['request']['task']='counts'
        r=f.confirm(p['confirmation_token'])
        self.assertEqual(r['status'],'evidence_ready');self.assertEqual(len(r['results']),2)
        self.assertFalse(r['intent_verified']);f.model.complete.assert_called_once()
        self.assertEqual(f.confirm(p['confirmation_token'])['status'],'confirmation_rejected')

    def test_bounds_duplicates_and_extra_fields(self):
        for steps in [[],[step('policy')]*4,[step('policy')]*2,
                      [{**step('policy'),'sql':'DELETE'}]]:
            p=planner(steps).propose('政策与质量')
            self.assertEqual(p['status'],'needs_review')
            self.assertNotIn('confirmation_token',p)

    def test_replacing_and_cancelling_plan(self):
        f=planner([step('policy')]);p=f.propose('政策与质量');f.propose('政策与质量')
        self.assertEqual(f.confirm(p['confirmation_token'])['status'],'confirmation_rejected')
        p=f.propose('政策与质量');f.cancel()
        self.assertEqual(f.confirm(p['confirmation_token'])['status'],'confirmation_rejected')

    def test_failed_step_stops_remaining_reports(self):
        f=planner([step('policy'),step('quality')]);p=f.propose('政策与质量')
        with patch('src.tradeintel_ai.analysis_planner.execute_request',return_value={'status':'execution_failed'}) as ex:
            r=f.confirm(p['confirmation_token'])
            self.assertEqual(r['status'],'incomplete');ex.assert_called_once()

    def test_forged_evidence_blocks_whole_plan(self):
        steps=[step('policy'),step('quality')];steps[1]['evidence']['task']='fake'
        self.assertEqual(planner(steps).propose('政策与质量')['status'],'needs_review')
