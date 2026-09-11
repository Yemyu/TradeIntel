"""Pre-live integrity review; all models are offline fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tests.test_answer_checklist_0093 import packet, submission
from tests.test_development_smoke_0090 import config
from tests.test_unified_research_v2 import policy_plan
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.answer_checklist import validate_review
from tradeintel_ai.development_smoke import run_batch


class ChecklistAuditTests(unittest.TestCase):
    def test_validation_does_not_modify_submitted_evidence(self):
        p = packet()
        value = submission(p)
        original = deepcopy(value)
        result = validate_review(p, value, 'fixture')
        self.assertEqual(value, original)
        self.assertIn('evidence_sha256', result['items'][0]['witnesses'][0])

    def test_unknown_review_stage_cannot_skip_evidence_checks(self):
        p = packet('unexpected')
        value = submission(p)
        for row in value['items']:
            row['status'] = 'supported'
            row['witnesses'] = []
        with self.assertRaises(ValueError): validate_review(p, value, 'fixture')

    def test_empty_reviewer_is_not_an_approval(self):
        p = packet()
        with self.assertRaises(ValueError): validate_review(p, submission(p), ' ')

    def test_changed_manifest_or_review_packet_stops_before_second_call(self):
        for target in ('manifest.json', 'D89-1-plan-review-packet.json'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / 'run'
                candidate = policy_plan()
                candidate.update(comparison=None, policy_search_query='Section 301 effective date rate', request_units=[
                    {'quote': '第一批关税何时生效，额外税率是多少？', 'kind': 'request', 'target': 'policy'},
                    {'quote': '政策资料截止日是2018-07-06。', 'kind': 'constraint', 'target': 'none'}])
                model = Mock()
                model.complete.return_value = ModelResponse(text=json.dumps(candidate), metadata={'finish_reason': 'stop'})
                def review(p):
                    (out / target).write_text('{"changed":true}')
                    return submission(p)
                result = run_batch(config(), out, reviewer=review, reviewer_id='fixture', source_kind='fixture',
                                   model_factory=lambda s: model, checklist_review=True)
                self.assertEqual(result['status'], 'stopped')
                self.assertEqual(len(result['calls']), 1)
                self.assertFalse((out / 'D89-1/delivery').exists())
                self.assertFalse((out / 'D89-1-plan-review.json').exists())


if __name__ == '__main__': unittest.main()
