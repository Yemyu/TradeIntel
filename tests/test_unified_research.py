import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.unified_research import UnifiedResearchWorkflow, validate_plan


QUESTION = ('第一批关税何时生效，额外税率是多少？政策资料截止日是2018-07-06；'
            '请查询其他原产地整体2018-09和2018-10的美元消费进口额，只做描述性比较，不做因果分析；'
            '政策整体范围。')


def plan():
    quote = {
        'policy_question_quote': '第一批关税何时生效，额外税率是多少？',
        'policy_as_of_quote': '2018-07-06', 'trade.policy_id': '第一批关税',
        'trade.operation': '查询', 'trade.metric': '美元消费进口额',
        'trade.origin': '其他原产地整体', 'trade.granularity': '政策整体范围',
        'trade.months': '2018-09和2018-10', 'trade.hs6': '政策整体范围',
        'trade.causal_effect': '只做描述性比较，不做因果分析',
    }
    return {'status': 'plan', 'policy_question': quote['policy_question_quote'],
            'policy_as_of': '2018-07-06',
            'trade': {'policy_id': 'us_301_list1_2018', 'operation': 'read',
                      'metric': 'import_value_consumption_usd', 'origin': 'other_origins',
                      'granularity': 'policy_aggregate', 'months': ['2018-09', '2018-10'],
                      'hs6': None, 'causal_effect': False},
            'tasks': ['policy', 'trade'], 'evidence': quote, 'missing': []}


class UnifiedTests(unittest.TestCase):
    def model(self, payload):
        m = Mock()
        m.complete.return_value = ModelResponse(text=json.dumps(payload, ensure_ascii=False),
                                                 metadata={'finish_reason': 'stop'})
        return m

    def test_literal_plan_is_valid(self):
        self.assertTrue(validate_plan(plan(), QUESTION))

    def test_preview_does_not_read_amounts_and_confirm_runs_brief(self):
        planner = self.model(plan())
        workflow = UnifiedResearchWorkflow(planner)
        preview = workflow.prepare(QUESTION)
        self.assertEqual(preview['status'], 'needs_confirmation')
        self.assertEqual(preview['trade_assessment']['amounts_read'], False)
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            self.assertEqual(result['status'], 'research_draft')
            self.assertTrue(result['user_confirmed'])
            self.assertFalse(result['intent_verified'])
            self.assertTrue((Path(tmp) / 'run/research-plan.json').is_file())
            self.assertIn('research-plan-1', (Path(tmp) / 'run/report.zh-CN.md').read_text())
        planner.complete.assert_called_once()

    def test_bad_plan_is_stopped(self):
        payload = plan()
        payload['evidence']['trade.months'] = '2018-11'
        workflow = UnifiedResearchWorkflow(self.model(payload))
        result = workflow.prepare(QUESTION)
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(workflow._pending)

    def test_duplicate_json_key_is_stopped(self):
        model = Mock()
        model.complete.return_value = ModelResponse(
            text='{"status":"clarify","status":"plan"}',
            metadata={'finish_reason': 'stop'})
        result = UnifiedResearchWorkflow(model).prepare(QUESTION)
        self.assertEqual(result['status'], 'needs_review')

    def test_clarification_does_not_create_token(self):
        payload = {'status': 'clarify', 'policy_question': None, 'policy_as_of': None,
                   'trade': None, 'tasks': [], 'evidence': {}, 'missing': ['资料截止日']}
        workflow = UnifiedResearchWorkflow(self.model(payload))
        result = workflow.prepare('我想查政策和贸易')
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertNotIn('confirmation_token', result)

    def test_confirm_token_is_one_time(self):
        workflow = UnifiedResearchWorkflow(self.model(plan()))
        preview = workflow.prepare(QUESTION)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(workflow.confirm('bad', Path(tmp) / 'bad')['status'], 'confirmation_rejected')
            self.assertEqual(workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')['status'], 'research_draft')
            self.assertEqual(workflow.confirm(preview['confirmation_token'], Path(tmp) / 'again')['status'], 'confirmation_rejected')


if __name__ == '__main__':
    unittest.main()
