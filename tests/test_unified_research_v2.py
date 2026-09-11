import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tests.test_unified_research import plan
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.unified_research import UnifiedResearchWorkflow, validate_plan


def planner(payload):
    model = Mock()
    model.complete.return_value = ModelResponse(
        text=json.dumps(payload, ensure_ascii=False),
        metadata={'finish_reason': 'stop'},
    )
    return model


def policy_plan():
    return {
        'status': 'plan',
        'policy_question': '第一批关税何时生效，额外税率是多少？',
        'policy_as_of': '2018-07-06',
        'trade': None,
        'tasks': ['policy'],
        'evidence': {
            'policy_question_quote': '第一批关税何时生效，额外税率是多少？',
            'policy_as_of_quote': '2018-07-06',
        },
        'missing': [],
    }


def trade_plan():
    return {
        'status': 'plan', 'policy_question': None, 'policy_as_of': None,
        'trade': {
            'policy_id': 'us_301_list1_2018', 'operation': 'read',
            'metric': 'import_value_consumption_usd', 'origin': 'other_origins',
            'granularity': 'policy_aggregate', 'months': ['2018-09', '2018-10'],
            'hs6': None, 'causal_effect': False,
        },
        'tasks': ['trade'],
        'evidence': {
            'trade.policy_id': '第一批关税', 'trade.operation': '查询',
            'trade.metric': '美元消费进口额', 'trade.origin': '其他原产地整体',
            'trade.granularity': '政策整体范围', 'trade.months': '2018-09和2018-10',
            'trade.hs6': '政策整体范围', 'trade.causal_effect': '只做描述性比较，不做因果分析',
        },
        'missing': [],
    }


class UnifiedResearchV2Tests(unittest.TestCase):
    def test_validate_allows_policy_only_and_trade_only(self):
        self.assertTrue(validate_plan(policy_plan(), policy_plan()['policy_question'] + ' 资料截止日是2018-07-06'))
        q = '查询其他原产地整体2018-09和2018-10的美元消费进口额，只做描述性比较，不做因果分析；第一批关税，政策整体范围。'
        self.assertTrue(validate_plan(trade_plan(), q))

    def test_policy_only_executes_without_trade_amounts(self):
        model = planner(policy_plan())
        workflow = UnifiedResearchWorkflow(model)
        question = '第一批关税何时生效，额外税率是多少？资料截止日是2018-07-06'
        preview = workflow.prepare(question)
        self.assertEqual(preview['status'], 'needs_confirmation')
        self.assertEqual(preview['tasks'], ['policy'])
        self.assertEqual(preview['trade_assessment']['status'], 'not_requested')
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            self.assertIn(result['status'], {'policy_draft', 'policy_evidence_only'})
            self.assertEqual(result['new_api_calls'], 0)
            self.assertEqual(result['conversation_revision'], 1)
            self.assertTrue((Path(tmp) / 'run/research-plan.json').is_file())

    def test_trade_only_executes_and_keeps_policy_unrequested(self):
        model = planner(trade_plan())
        workflow = UnifiedResearchWorkflow(model)
        q = '查询其他原产地整体2018-09和2018-10的美元消费进口额，只做描述性比较，不做因果分析；第一批关税，政策整体范围。'
        preview = workflow.prepare(q)
        self.assertEqual(preview['status'], 'needs_confirmation')
        self.assertEqual(preview['tasks'], ['trade'])
        self.assertEqual(preview['policy_candidate_count'], 0)
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            self.assertEqual(result['status'], 'trade_draft')
            self.assertEqual(result['summary']['total_usd'], 77600543957)
            self.assertEqual(result['new_api_calls'], 0)
            self.assertEqual(result['policy']['generation']['status'], 'not_requested')

    def test_fingerprint_change_rejects_confirmation_before_execution(self):
        workflow = UnifiedResearchWorkflow(planner(trade_plan()))
        q = '查询其他原产地整体2018-09和2018-10的美元消费进口额，只做描述性比较，不做因果分析；第一批关税，政策整体范围。'
        preview = workflow.prepare(q)
        old = workflow._fingerprints
        workflow._fingerprints = lambda: {**old(), 'data': 'changed'}
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'run')
            self.assertEqual(result['status'], 'confirmation_rejected')
            self.assertFalse((Path(tmp) / 'run').exists())


if __name__ == '__main__':
    unittest.main()
