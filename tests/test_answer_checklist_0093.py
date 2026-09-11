from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tradeintel_ai.answer_checklist import digest, load_checklists, template, validate_review, file_hashes, unchanged
from tradeintel_ai.development_smoke import CASES, run_batch, preflight
from tradeintel_ai.agent import ModelResponse
from tests.test_development_smoke_0090 import config
from tests.test_unified_research_v2 import policy_plan


def packet(stage='answer'):
    return {'case': CASES[0], 'stage': stage, 'files': {},
            'checklist': load_checklists(CASES)['cases']['D89-1'],
            'artifact': {'policy': {'generation': {'claims': [
                {'text': 'fixture date and rate', 'citations': ['source:1']}]}},
                'policy_evidence': {'hits': [{'id': 'source:1', 'text': 'fixture evidence date and rate'}]}}}


def submission(p):
    result = template(p)
    result['overall'] = {'status': 'pass', 'reason': 'Fixture overall boundary review, not a real judgment'}
    for row in result['items']:
        row.update(status='supported' if p['stage'] == 'answer' else 'covered', reason='Fixture item review')
        if p['stage'] == 'answer':
            row['witnesses'] = [{'claim_index': 0, 'claim_text': 'fixture date and rate',
                                 'citation_id': 'source:1', 'evidence_excerpt': 'date and rate'}]
    return result


class ChecklistTests(unittest.TestCase):
    def test_complete_shared_claim_can_support_separate_review_rows(self):
        p = packet()
        r = validate_review(p, submission(p), 'fixture')
        self.assertTrue(r['approved'])
        self.assertEqual(len(r['items']), 2)
        self.assertFalse(r['semantic_coverage_verified'])

    def test_missing_answer_and_global_failure_reject(self):
        for kind in ('missing', 'contradicted', 'unverifiable', 'overall'):
            p = packet()
            value = submission(p)
            if kind == 'overall':
                value['overall']['status'] = 'fail'
            else:
                value['items'][1]['status'] = kind
            self.assertFalse(validate_review(p, value, 'fixture')['approved'])

    def test_missing_duplicate_blank_and_unreviewed_records_fail_closed(self):
        p = packet()
        variants = [True, template(p)]
        for mutation in ('missing', 'duplicate', 'blank'):
            v = submission(p)
            if mutation == 'missing': v['items'].pop()
            elif mutation == 'duplicate': v['items'][1] = deepcopy(v['items'][0])
            else: v['items'][1]['reason'] = ' '
            variants.append(v)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_review(p, value, 'fixture')

    def test_invalid_claim_citation_or_excerpt_rejected(self):
        for key, value in [('claim_index', -1), ('citation_id', 'not-found'),
                           ('claim_text', 'changed'), ('evidence_excerpt', 'not present')]:
            p = packet()
            v = submission(p)
            v['items'][0]['witnesses'][0][key] = value
            with self.assertRaises(ValueError): validate_review(p, v, 'fixture')

    def test_changed_checklist_or_answer_invalidates_submission(self):
        for change in ('checklist', 'artifact'):
            p = packet()
            v = submission(p)
            if change == 'artifact':
                p['artifact']['changed'] = True
            else:
                p['checklist'][0]['required_answer'] = 'changed'
            with self.assertRaises(ValueError): validate_review(p, v, 'fixture')

    def test_trade_reference_cannot_be_chosen_by_reviewer(self):
        p = {'case': CASES[2], 'stage': 'answer', 'files': {},
             'checklist': [{'id': 'change', 'task': 'trade', 'expected_disposition': 'answer',
                            'checks': [{'path': ['summary', 'difference'], 'expected': 7}]}],
             'artifact': {'summary': {'difference': 7}}}
        v = {'packet_sha256': digest(p), 'overall': {'status': 'pass', 'reason': 'Checked scope'},
             'items': [{'id': 'change', 'status': 'supported', 'reason': 'Compared frozen reference',
                        'checks': deepcopy(p['checklist'][0]['checks'])}]}
        self.assertTrue(validate_review(p, v, 'fixture')['approved'])
        p['artifact']['summary']['difference'] = -7
        v['packet_sha256'] = digest(p)
        with self.assertRaises(ValueError): validate_review(p, v, 'fixture')

    def test_scope_selection_never_means_partial_execution(self):
        p = {'case': CASES[3], 'stage': 'plan', 'files': {},
             'checklist': load_checklists(CASES)['cases']['D89-4'],
             'artifact': {'status': 'needs_scope_selection'}}
        v = submission(p)
        for item in v['items']: item['status'] = 'needs_clarification'
        self.assertTrue(validate_review(p, v, 'fixture')['approved'])
        p['artifact']['status'] = 'needs_confirmation'
        v['packet_sha256'] = digest(p)
        with self.assertRaises(ValueError): validate_review(p, v, 'fixture')

    def test_reviewed_files_changes_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'evidence.json'
            path.write_text('original')
            hashes = file_hashes(tmp)
            self.assertTrue(unchanged(hashes))
            path.write_text('changed')
            self.assertFalse(unchanged(hashes))

    def test_new_preflight_freezes_checklists_without_network(self):
        with patch('tradeintel_ai.model_adapter.OpenAICompatibleModel.complete', side_effect=AssertionError('network')):
            state = preflight(config(), checklist_review=True)
        self.assertEqual(state['manifest']['version'], 'development-smoke-0093')
        self.assertEqual(len(state['manifest']['checklists']['cases']), 4)
        self.assertEqual(state['new_api_calls'], 0)

    def test_trade_checklist_matches_actual_summary_contract(self):
        from tradeintel_ai.research_brief import summary_with_comparison
        root = Path(__file__).resolve().parents[1]
        saved = json.loads((root / 'docs/experiments/phase13k-delivery/saved-live-result.json').read_text())
        data = next(r['data'] for r in saved['trade']['tool_results'] if r['tool_name'] == 'get_trade_series')
        for case_id, comparison in [('D89-2', {'kind': 'sequence'}),
                                    ('D89-3', {'kind': 'endpoint', 'reference_month': '2018-09', 'current_month': '2018-10'})]:
            rows = [r for r in load_checklists(CASES)['cases'][case_id] if r['task'] == 'trade']
            p = {'case': next(c for c in CASES if c['id'] == case_id), 'stage': 'answer', 'files': {},
                 'checklist': rows, 'artifact': {'summary': summary_with_comparison(data, comparison, None)}}
            v = template(p)
            v['overall'] = {'status': 'pass', 'reason': 'Offline numeric reference consistency only'}
            v['items'][0].update(status='supported', reason='Compared frozen historical reference', checks=rows[0]['checks'])
            self.assertTrue(validate_review(p, v, 'fixture')['approved'])

    def test_actual_delivery_can_be_reviewed_and_missing_answer_stops_next_case(self):
        candidate = policy_plan()
        candidate.update(comparison=None, policy_search_query='Section 301 effective date rate', request_units=[
            {'quote': '第一批关税何时生效，额外税率是多少？', 'kind': 'request', 'target': 'policy'},
            {'quote': '政策资料截止日是2018-07-06。', 'kind': 'constraint', 'target': 'none'}])
        def factory(stage):
            model = Mock()
            def complete(**kw):
                if stage == 'planning': value = candidate
                else:
                    payload = json.loads(kw['messages'][1]['content'])
                    self.assertNotIn('required_answer', json.dumps(payload))
                    value = {'claims': [{'text': 'Offline fixture, not a real policy answer',
                                         'citations': [payload['evidence'][0]['id']]}]}
                return ModelResponse(text=json.dumps(value), metadata={'finish_reason': 'stop'})
            model.complete.side_effect = complete
            return model
        def review(p):
            v = submission(p)
            if p['stage'] == 'answer':
                for r in v['items']: r.update(status='missing', reason='Fixture intentionally not answering the questions', witnesses=[])
            return v
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = run_batch(config(), out, reviewer=review, reviewer_id='fixture', source_kind='fixture',
                               model_factory=factory, checklist_review=True)
            self.assertEqual(result.get('stop_reason'), 'review_not_approved')
            self.assertEqual(len(result['calls']), 2)
            self.assertEqual(result['cases'][1]['status'], 'not_run')
            self.assertTrue(json.loads((out / 'D89-1-plan-review.json').read_text())['approved'])
            self.assertFalse(json.loads((out / 'D89-1-answer-review.json').read_text())['approved'])

    def test_live_style_workflow_saves_negative_review_without_execution_or_reference_leak(self):
        candidate = policy_plan()
        candidate.update(comparison=None, policy_search_query='Section 301 effective date rate', request_units=[
            {'quote': '第一批关税何时生效，额外税率是多少？', 'kind': 'request', 'target': 'policy'},
            {'quote': '政策资料截止日是2018-07-06。', 'kind': 'constraint', 'target': 'none'}])
        model = Mock()
        original_complete = model.complete
        model.complete.return_value = ModelResponse(text=json.dumps(candidate), metadata={'finish_reason': 'stop'})
        def review(p):
            self.assertEqual(len(p['checklist']), 2)
            self.assertEqual(len([r for r in p['artifact']['request_units'] if r['kind'] == 'request']), 1)
            v = submission(p)
            v['items'][1].update(status='wrong_scope', reason='Synthetic negative decision')
            return v
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = run_batch(config(), out, reviewer=review, reviewer_id='fixture', source_kind='fixture',
                               model_factory=lambda s: model, checklist_review=True)
            self.assertEqual(result.get('stop_reason'), 'review_not_approved')
            saved = json.loads((out / 'D89-1-plan-review.json').read_text())
            self.assertFalse(saved['approved'])
            self.assertFalse((out / 'D89-1/delivery').exists())
            self.assertEqual(len(result['calls']), 1)
            messages = original_complete.call_args.kwargs['messages']
            text = json.dumps(messages, ensure_ascii=False)
            self.assertNotIn('required_answer', text)
            self.assertNotIn('36587820118', text)
            self.assertIn('同一政策任务内的多个问题可保留在同一原文片段', text)


if __name__ == '__main__': unittest.main()
