"""Exercise actual Request/opener capture with an in-memory HTTP response."""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.research_models import ResearchPolicyModel
from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, ProspectiveCallLedger, freeze_dependencies, digest
from tradeintel_ai.prospective_runner import (
    LedgerBoundModel, ProspectiveSyntheticRunner, default_cases, _policy_pair_packet,
    paired_policy_messages, PAIRED_POLICY_PROMPT,
)


class HttpPair0124Tests(unittest.TestCase):
    def test_live_planning_checks_frozen_configuration_and_actual_payload(self):
        from tradeintel_ai.live_development import runtime_configuration
        from tradeintel_ai.research_models import ResearchPlannerModel
        config = OpenAICompatibleConfig('https://offline.invalid/v4', 'fixture-model', api_key='fixture-secret')
        for mismatch in ('none', 'declared', 'actual'):
            with self.subTest(mismatch=mismatch), TemporaryDirectory() as tmp:
                sent = []
                def opener(request, timeout):
                    sent.append(request)
                    return BytesIO(json.dumps({'choices': [{'message': {'content': '{}'},
                        'finish_reason': 'stop'}], 'usage': {'total_tokens': 5}}).encode())
                class Model(ResearchPlannerModel):
                    def _payload(self, *, messages, tools):
                        payload = super()._payload(messages=messages, tools=tools)
                        if mismatch == 'actual' and messages:
                            payload['temperature'] = 0.9
                        return payload
                model_config = replace(config, model='different') if mismatch == 'declared' else config
                model = Model(model_config, opener=opener)
                snapshot = freeze_dependencies([Path(__file__)], configuration={
                    'runtime_configuration': runtime_configuration(config)})
                ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'run', frozen_snapshot=snapshot,
                    run_mode='live_development', external_calls=True, reviewer_type='ai_assisted')
                bound = LedgerBoundModel(model, ledger, 'q', 'planning', {})
                messages = [{'role': 'system', 'content': 'test system'}, {'role': 'user', 'content': 'question'}]
                if mismatch == 'none':
                    bound.complete(messages=messages, tools=[])
                    self.assertEqual(len(sent), 1)
                else:
                    with self.assertRaises(AcceptanceGuardError):
                        bound.complete(messages=messages, tools=[])
                    self.assertEqual(len(sent), 0 if mismatch == 'declared' else 1)
                    if mismatch == 'actual':
                        self.assertEqual(ledger.state['status'], 'stopped')

    def run_pair(self, root, mutation=None, both=False, wrong_endpoint=False, corrupt_record=False):
        case = default_cases()[2]
        config = OpenAICompatibleConfig('https://offline.invalid/v4', 'fixture-model', api_key='fixture-secret')
        sent = []
        def opener(request, timeout):
            sent.append(request)
            return BytesIO(json.dumps({'choices': [{'message': {'content': '{"claims":[]}'},
                'finish_reason': 'stop'}], 'usage': {'total_tokens': 5}}).encode())
        class AlteredModel(ResearchPolicyModel):
            def _payload(self, *, messages, tools):
                payload = super()._payload(messages=messages, tools=tools)
                if mutation:
                    mutation(payload)
                return payload
        models = [AlteredModel(config, opener=opener) if both else ResearchPolicyModel(config, opener=opener),
                  AlteredModel(config, opener=opener)]
        pair = _policy_pair_packet(case, {'request': {'policy_question': case.policy_reference['question'],
            'policy_as_of': case.policy_reference['as_of']}}, *models)
        pair['shared_prompt_sha256'] = digest(PAIRED_POLICY_PROMPT)
        if wrong_endpoint:
            models[1].config = replace(config, base_url='https://different.invalid/v4')
        ledger = ProspectiveCallLedger([case.id], root / 'run',
            frozen_snapshot=freeze_dependencies([Path(__file__)]))
        for index, stage in enumerate(('policy_with_evidence', 'policy_no_evidence')):
            model = LedgerBoundModel(models[index], ledger, case.id, stage, {})
            model.pair_context = {'question': pair['question'], 'as_of': pair['as_of']}
            model.complete(messages=paired_policy_messages(pair['question'], pair['as_of'],
                [{'id': 'fixture-source', 'text': 'fixture excerpt'}] if index == 0 else []), tools=[])
        if corrupt_record:
            artifact = ledger.state['calls'][0]['raw_response']
            path = ledger.output / artifact['path']
            path.write_text(path.read_text() + '\n')
        result = ProspectiveSyntheticRunner._actual_policy_pair_capture(ledger, case.id, pair)
        self.assertEqual(len(sent), 2)
        self.assertNotIn('fixture-secret', json.dumps(result))
        return result

    def test_actual_request_capture_positive(self):
        with TemporaryDirectory() as tmp:
            result = self.run_pair(Path(tmp))
            self.assertTrue(result['actual_payloads_verified'])
            self.assertTrue(result['evidence_only_ablation_verified'])

    def test_changed_http_message_is_rejected(self):
        def mutate(p):
            if p['messages']:
                p['messages'][0]['content'] += ' extra hidden instructions'
        with TemporaryDirectory() as tmp, self.assertRaises(AcceptanceGuardError):
            self.run_pair(Path(tmp), mutation=mutate)

    def test_different_endpoint_is_rejected(self):
        with TemporaryDirectory() as tmp, self.assertRaises(AcceptanceGuardError):
            self.run_pair(Path(tmp), wrong_endpoint=True)

    def test_same_undeclared_parameter_in_both_arms_is_rejected(self):
        with TemporaryDirectory() as tmp, self.assertRaises(AcceptanceGuardError):
            self.run_pair(Path(tmp), mutation=lambda p: p.update(seed=123), both=True)

    def test_modified_saved_capture_is_rejected(self):
        with TemporaryDirectory() as tmp, self.assertRaises(AcceptanceGuardError):
            self.run_pair(Path(tmp), corrupt_record=True)
