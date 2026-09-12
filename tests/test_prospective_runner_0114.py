import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.prospective_runner import (
    SyntheticCase,
    fixture_review,
    run_synthetic_batch,
)
from tests.test_trade_mapping_proposal_0105 import QUESTION as TRADE_QUESTION, candidate


class StaticModel:
    def __init__(self, payload=None, *, callback=None):
        self.payload = payload
        self.callback = callback
        self.calls = []

    def complete(self, *, messages, tools):
        self.calls.append({'messages': messages, 'tools': tools})
        if self.callback is not None:
            return self.callback(messages, tools)
        return ModelResponse(
            text=json.dumps(self.payload, ensure_ascii=False),
            metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 5}},
        )


def trade_case():
    return SyntheticCase(
        id='RUN-TRADE-01', question=TRADE_QUESTION, expected_kind='support',
        expected_tasks=('trade',), checklist=({'id': 'scope', 'kind': 'fact'},),
        reference={'gold_marker': 'trade-reference-never-in-messages'},
    )


def policy_case():
    question = '第一批关税何时生效，额外税率是多少？政策资料截止日是2018-07-06。'
    payload = {
        'status': 'plan',
        'policy_question': '第一批关税何时生效，额外税率是多少？',
        'policy_as_of': '2018-07-06',
        'trade': None,
        'comparison': None,
        'policy_search_query': 'initial Section 301 List 1 effective date additional duty rate',
        'tasks': ['policy'],
        'evidence': {
            'policy_question_quote': '第一批关税何时生效，额外税率是多少？',
            'policy_as_of_quote': '2018-07-06',
        },
        'missing': [],
        'request_units': [
            {'quote': '第一批关税何时生效，额外税率是多少？', 'kind': 'request', 'target': 'policy'},
            {'quote': '政策资料截止日是2018-07-06。', 'kind': 'constraint', 'target': 'none'},
        ],
    }
    return SyntheticCase(
        id='RUN-POLICY-01', question=question, expected_kind='support',
        expected_tasks=('policy',), checklist=({'id': 'policy_claim', 'kind': 'policy'},),
        reference={'gold_marker': 'policy-reference-never-in-messages'}, run_controls=True,
    ), payload


class ProspectiveRunner0114Tests(unittest.TestCase):
    def test_real_product_workflow_trade_path_closes_only_after_delivery_review(self):
        case = trade_case()
        payload = candidate()

        def factory(stage, _case):
            return StaticModel(payload)

        with TemporaryDirectory() as tmp:
            summary = run_synthetic_batch(Path(tmp) / 'run', cases=[case], model_factory=factory)
            self.assertEqual(summary['status'], 'stopped')
            self.assertEqual(summary['stop_reason'], 'acceptance_integration_incomplete_0116')
            self.assertEqual(summary['question_status_counts'], {'accepted': 1})
            self.assertEqual(summary['call_count'], 1)
            ledger = json.loads((Path(tmp) / 'run' / 'ledger.json').read_text())
            self.assertEqual(ledger['status'], 'stopped')
            self.assertIn('RUN-TRADE-01/delivery-inspection.json', ledger['artifacts'])
            self.assertTrue((Path(tmp) / 'run' / 'run-summary.json').is_file())

    def test_policy_delivery_preserved_but_placeholder_controls_disabled(self):
        case, payload = policy_case()

        def factory(stage, _case):
            if stage == 'planning':
                return StaticModel(payload)
            if stage == 'policy_with_evidence':
                def policy(messages, _tools):
                    request = json.loads(messages[-1]['content'])
                    citation = request['evidence'][0]['id']
                    return ModelResponse(
                        text=json.dumps({'claims': [{'text': '仅作证据草稿', 'citations': [citation]}]},
                                         ensure_ascii=False),
                        metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 7}},
                    )
                return StaticModel(callback=policy)
            return StaticModel({'status': 'boundary'})

        with TemporaryDirectory() as tmp:
            summary = run_synthetic_batch(Path(tmp) / 'run', cases=[case], model_factory=factory)
            self.assertEqual(summary['status'], 'stopped')
            self.assertEqual(summary['stop_reason'], 'controls_not_implemented_0116')
            self.assertEqual(summary['stage_counts']['planning'], 1)
            self.assertEqual(summary['stage_counts']['policy_with_evidence'], 1)
            self.assertEqual(summary['stage_counts']['policy_no_evidence'], 0)
            self.assertEqual(summary['controls'], {})
            self.assertTrue((Path(tmp) / 'run' / case.id / 'delivery/report.zh-CN.md').is_file())

    def test_connection_failure_is_recorded_once_and_leaves_fixed_denominator(self):
        case = trade_case()

        class Failing:
            def complete(self, *, messages, tools):
                raise ConnectionError('fixture connection failure')

        with TemporaryDirectory() as tmp:
            summary = run_synthetic_batch(
                Path(tmp) / 'run', cases=[case, SyntheticCase(
                    id='RUN-NOT-RUN', question='later', expected_kind='clarification',
                    expected_tasks=(), checklist=({'id': 'x', 'kind': 'fact'},),
                    reference={'gold_marker': 'later'},)],
                model_factory=lambda _stage, _case: Failing(),
            )
            self.assertEqual(summary['status'], 'stopped')
            self.assertEqual(summary['call_count'], 1)
            self.assertEqual(summary['not_run'], ['RUN-NOT-RUN'])
            self.assertFalse(summary['automatic_retry'])

    def test_reference_marker_in_model_input_stops_before_reservation(self):
        marker = 'reference-only-marker-0114'
        case = SyntheticCase(
            id='RUN-LEAK-01', question=f'问题中不应携带 {marker}',
            expected_kind='clarification', expected_tasks=(),
            checklist=({'id': 'x', 'kind': 'fact'},),
            reference={'gold_marker': marker},
        )
        with TemporaryDirectory() as tmp:
            summary = run_synthetic_batch(
                Path(tmp) / 'run', cases=[case],
                model_factory=lambda _stage, _case: StaticModel({'status': 'clarify'}),
            )
            self.assertEqual(summary['status'], 'stopped')
            self.assertEqual(summary['call_count'], 0)
            self.assertEqual(summary['stop_reason'], 'plan_review_rejected')


if __name__ == '__main__':
    unittest.main()
