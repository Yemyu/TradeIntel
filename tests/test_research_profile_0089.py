"""Ordered quote alignment and effective wire settings, without network."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_request_coverage_0088 import candidate
from tests.test_unified_research import QUESTION
from tests.test_unified_research_v2 import planner
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.research_models import ResearchPlannerModel, ResearchPolicyModel
from tradeintel_ai.request_coverage import materialize_units
from tradeintel_ai.unified_research import UnifiedResearchWorkflow


def quoted_candidate():
    value = candidate()
    value['request_units'] = [{key: item[key] for key in ('quote', 'kind', 'target')}
                              for item in value['request_units']]
    return value


class ResearchProfileTests(unittest.TestCase):
    def test_ordered_quotes_produce_same_confirmable_plan(self):
        work = UnifiedResearchWorkflow(planner(quoted_candidate()), require_request_units=True,
                                       derive_request_offsets=True)
        preview = work.prepare(QUESTION)
        self.assertEqual(preview['status'], 'needs_confirmation')
        self.assertEqual([(u['start'], u['end']) for u in preview['request_units']],
                         [(u['start'], u['end']) for u in candidate()['request_units']])
        self.assertEqual(preview['plan']['request_unit_positions']['kind'], 'derived')
        with tempfile.TemporaryDirectory() as tmp:
            result = work.confirm(preview['confirmation_token'], Path(tmp) / 'run')
        self.assertFalse(result['semantic_coverage_verified'])
        self.assertEqual(len(result['request_results']), 3)

    def test_alignment_rejects_changed_reordered_and_omitted_quotes(self):
        units = quoted_candidate()['request_units']
        for bad in (units[1:], units[:-1], list(reversed(units)),
                    [{**units[0], 'quote': '第一批关税什么时候生效，'}] + units[1:]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                materialize_units(bad, QUESTION)

    def test_repeated_unicode_quotes_are_located_in_sequence(self):
        q = '🙂金额？ \n🙂金额？'
        item = dict(quote='🙂金额？', kind='request', target='trade_series')
        result = materialize_units([item, item], q)
        self.assertEqual([r['start'] for r in result], [0, 6])
        for row in result:
            self.assertEqual(q[row['start']:row['end']], row['quote'])

    def test_alignment_mode_change_invalidates_pending(self):
        work = UnifiedResearchWorkflow(planner(quoted_candidate()), require_request_units=True,
                                       derive_request_offsets=True)
        preview = work.prepare(QUESTION)
        work.derive_request_offsets = False
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(work.confirm(preview['confirmation_token'], Path(tmp) / 'run')['status'],
                             'confirmation_rejected')

    def test_actual_http_payload_matches_persisted_generation_settings(self):
        config = OpenAICompatibleConfig(base_url='https://example.test/v4', model='glm-4.7',
                                        api_key='fixture-key', timeout_seconds=60, temperature=0)
        for cls, limit in ((ResearchPlannerModel, 1536), (ResearchPolicyModel, 768)):
            with self.subTest(stage=cls.stage), tempfile.TemporaryDirectory() as tmp:
                audit_path = Path(tmp) / 'planning'
                captured = []
                def opener(request, timeout):
                    body = json.loads(request.data)
                    captured.append(body)
                    self.assertEqual(timeout, 60)
                    if cls is ResearchPlannerModel:
                        saved = json.loads((audit_path / 'audit.json').read_text())
                        self.assertEqual(saved['status'], 'attempt_reserved')
                        settings = saved['configuration']['effective_request_settings']
                        self.assertEqual(settings, {key: body[key] for key in settings})
                    content = json.dumps(quoted_candidate(), ensure_ascii=False)
                    return io.BytesIO(json.dumps({'choices': [{'message': {'content': content},
                                                              'finish_reason': 'stop'}]}).encode())
                model = cls(config, opener=opener)
                if cls is ResearchPlannerModel:
                    result = UnifiedResearchWorkflow(model, require_request_units=True,
                        derive_request_offsets=True).prepare(QUESTION, audit_output=audit_path,
                                                            secret=config.api_key)
                    self.assertEqual(result['status'], 'needs_confirmation')
                    for path in audit_path.iterdir():
                        self.assertNotIn('fixture-key', path.read_text())
                else:
                    model.complete(messages=[{'role': 'user', 'content': 'fixture'}], tools=[])
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0]['max_tokens'], limit)
                self.assertEqual(captured[0]['thinking'], {'type': 'disabled'})
                self.assertIs(captured[0]['stream'], False)
