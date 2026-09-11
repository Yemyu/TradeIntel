"""Regression checks for review findings; all model responses are fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_unified_research import QUESTION, plan
from tradeintel_ai.unified_research import UnifiedResearchWorkflow
from scripts import run_research_plan_acceptance as runner


class ReviewGuards(unittest.TestCase):
    def workflow(self):
        model = Mock()
        model.complete.return_value = {'text': json.dumps(plan()), 'metadata': {'finish_reason': 'stop'}}
        return UnifiedResearchWorkflow(model)

    def test_retired_batch_cannot_reach_provider_or_create_output(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'BoundedModel') as model:
            output = Path(tmp)/'run'
            with self.assertRaisesRegex(ValueError, 'retired'):
                runner.run(execute=True, output=output, config=Mock())
            model.assert_not_called()
            self.assertFalse(output.exists())

    def test_oversize_revokes_both_confirmations_before_model(self):
        work = self.workflow()
        preview = work.prepare(QUESTION)
        work.planner_model.complete.reset_mock()
        result = work.prepare('问'*2001)
        self.assertEqual(result['model_calls'], 0)
        work.planner_model.complete.assert_not_called()
        self.assertIsNone(work._pending)
        self.assertIsNone(work.brief._pending)
        self.assertEqual(work.confirm(preview['confirmation_token'], '/unused')['status'], 'confirmation_rejected')

    def test_preview_mutation_does_not_change_saved_plan(self):
        work = self.workflow()
        preview = work.prepare(QUESTION)
        preview['plan']['trade']['origin'] = 'China'
        preview['request']['trade']['months'] = ['2019-01']
        with tempfile.TemporaryDirectory() as tmp:
            result = work.confirm(preview['confirmation_token'], Path(tmp)/'run')
            self.assertEqual(result['plan']['trade']['origin'], 'other_origins')
            self.assertEqual(result['plan']['trade']['months'], ['2018-09','2018-10'])
            self.assertEqual(result['summary']['total_usd'], 77600543957)
            self.assertFalse(result['intent_verified'])

    def test_local_preflight_exception_clears_inner_pending(self):
        work = self.workflow()
        def fail(request):
            work.brief._pending = ('stale', request)
            raise ValueError('fixture failure')
        with patch.object(work.brief, 'prepare', side_effect=fail):
            self.assertEqual(work.prepare(QUESTION)['status'], 'needs_review')
        self.assertIsNone(work.brief._pending)
