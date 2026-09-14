from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradeintel_ai.live_development import (
    live_preflight, build_live_runner, run_live_development, pending_reviews, review_store,
)
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.prospective_acceptance import AcceptanceGuardError
from tradeintel_ai.prospective_runner import fixture_review
from tradeintel_ai.research_models import ResearchPlannerModel
from tests.test_trade_mapping_proposal_0105 import candidate


class LiveEntryTests(unittest.TestCase):
    def test_policy_followup_scope_and_budgets_are_frozen(self):
        config = OpenAICompatibleConfig('https://offline.invalid/v4', 'test-model', api_key='secret')
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'batch'
            preflight = live_preflight(out, config, persist=True, profile='policy-followup')
            self.assertEqual([case['id'] for case in preflight['cases']],
                             ['SYN-POLICY-01', 'SYN-COMBINED-01'])
            self.assertEqual(preflight['stage_budgets'],
                             {'planning': 2, 'policy_with_evidence': 2, 'policy_no_evidence': 2})
            runner = build_live_runner(out, config)
            self.assertEqual(len(runner.cases), 2)
            self.assertEqual(runner.runtime_configuration['profile'], 'policy-followup')
            with self.assertRaises(AcceptanceGuardError):
                live_preflight(out, config, persist=True, profile='four-scenes')
            with self.assertRaises(AcceptanceGuardError):
                live_preflight(Path(tmp) / 'invalid', config, profile='invalid')

    def test_freeze_execute_review_resume_uses_one_http_call(self):
        config = OpenAICompatibleConfig('https://offline.invalid/v4', 'test-model', api_key='test-secret')
        sent = []
        def opener(request, timeout):
            sent.append(request)
            return BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(candidate())},
                'finish_reason': 'stop'}], 'usage': {'total_tokens': 10}}).encode())
        def planner(cfg):
            return ResearchPlannerModel(cfg, opener=opener)
        with TemporaryDirectory() as tmp, patch('tradeintel_ai.live_development.ResearchPlannerModel', planner):
            out = Path(tmp) / 'batch'
            preflight = live_preflight(out, config, persist=True)
            self.assertTrue(preflight['snapshot_persisted'])
            self.assertFalse(preflight['credentials_verified'])
            self.assertEqual(sent, [])
            with self.assertRaises(AcceptanceGuardError):
                build_live_runner(out, replace(config, model='changed'))
            result = run_live_development(out, config)
            self.assertEqual(result['status'], 'waiting_review', result)
            pending = pending_reviews(out)['pending']
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]['kind'], 'plan')
            # Fixture judgement is test-only; production requires the host to read it.
            review_store(out).submit(pending[0]['slot'], fixture_review(pending[0]['packet']))
            result = run_live_development(out, config, resume=True)
            self.assertEqual(result['status'], 'waiting_review', result)
            self.assertEqual(pending_reviews(out)['pending'][0]['kind'], 'answer')
            self.assertEqual(len(sent), 1)
            self.assertNotIn('test-secret', (Path(tmp) / 'batch.preflight.json').read_text())

    def test_missing_key_and_query_credentials_cannot_freeze(self):
        with TemporaryDirectory() as tmp:
            for config in (
                OpenAICompatibleConfig('https://offline.invalid/v4', 'test-model'),
                OpenAICompatibleConfig('https://offline.invalid/v4?key=secret', 'test-model', api_key='secret'),
            ):
                with self.assertRaises(AcceptanceGuardError):
                    live_preflight(Path(tmp) / 'batch', config, persist=True)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
