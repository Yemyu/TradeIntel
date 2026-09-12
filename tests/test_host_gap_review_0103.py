"""Regression checks for provenance, stale approval, and batch integration."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_host_gap_workflow_0102 import gap_plan, QUESTION
from tests.test_unified_research_v2 import planner, policy_plan
from tests.test_development_smoke_0090 import config
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.unified_research import UnifiedResearchWorkflow, validate_plan
from tradeintel_ai.quote_gap_audit import audit_quote_gaps, digest_audit, validate_gap_review
from tradeintel_ai.answer_checklist import template
from tradeintel_ai.development_smoke import run_batch


def approve(audit):
    return {'audit_sha256': digest_audit(audit), 'reviewer': 'fixture',
            'overall': {'status': 'pass', 'reason': 'Synthetic separator review'},
            'gaps': [{k: g[k] for k in ('start', 'end', 'quote')} |
                     {'status': 'accepted_separator', 'reason': 'Synthetic reviewed separator'}
                     for g in audit['segments'] if g['source'] == 'host_gap' and g['quote'].strip()]}


class GapReviewTests(unittest.TestCase):
    def work(self):
        return UnifiedResearchWorkflow(planner(gap_plan()), require_request_units=True,
            derive_request_offsets=True, allow_host_gap_review=True)

    def test_recomputed_provenance_rejects_tampering_even_with_fresh_hash(self):
        p = gap_plan()
        audit = audit_quote_gaps(p['request_units'], QUESTION)
        self.assertTrue(validate_plan(p, QUESTION, host_alignment=audit))
        for change in ('quote', 'start', 'remove', 'classification'):
            bad = deepcopy(audit)
            gap = next(s for s in bad['segments'] if s['source'] == 'host_gap')
            if change == 'quote': gap['quote'] = '不'
            elif change == 'start': gap['start'] += 1
            elif change == 'remove': bad['segments'].remove(gap)
            else: gap['kind'] = 'context'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_plan(p, QUESTION, host_alignment=bad)
            with self.assertRaises(ValueError):
                validate_gap_review(bad, approve(bad))
        with self.assertRaises(ValueError):
            validate_plan({k: v for k, v in p.items() if k != 'request_units'}, QUESTION,
                          host_alignment=audit)

    def test_null_confirmation_does_not_consume_pending_review(self):
        work = self.work()
        preview = work.prepare(QUESTION)
        self.assertEqual(work.confirm(None, '/unused')['status'], 'confirmation_rejected')
        self.assertIsNotNone(work._pending)
        approved = work.approve_gap_review(preview['gap_review_token'], approve(preview['gap_audit']))
        self.assertEqual(approved['status'], 'needs_confirmation')
        self.assertIn('coverage_preview', approved)
        self.assertFalse(approved['semantic_coverage_verified'])

    def test_stale_sources_and_prior_message_cannot_approve(self):
        work = self.work()
        first = work.prepare(QUESTION)
        work.prepare(QUESTION)
        self.assertEqual(work.approve_gap_review(first['gap_review_token'], approve(first['gap_audit']))['status'],
                         'confirmation_rejected')
        current = work.prepare(QUESTION)
        with patch.object(work, '_fingerprints', return_value={'changed': True}):
            result = work.approve_gap_review(current['gap_review_token'], approve(current['gap_audit']))
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(work._pending)

    def test_missing_negative_and_noninteger_gap_decisions(self):
        audit = audit_quote_gaps(gap_plan()['request_units'], QUESTION)
        for mutation in ('missing', 'float', 'hash'):
            row = approve(audit)
            if mutation == 'missing': row['gaps'].pop()
            elif mutation == 'float': row['gaps'][0]['start'] = float(row['gaps'][0]['start'])
            else: row['audit_sha256'] = 'old'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_gap_review(audit, row)
        row = approve(audit)
        row['gaps'][0]['status'] = 'rejected'
        self.assertFalse(validate_gap_review(audit, row)['approved'])

    def test_batch_requires_gap_and_semantic_reviews_before_generation(self):
        p = policy_plan()
        p.update(comparison=None, policy_search_query='Section 301 effective date rate',
                 request_units=[{'quote': p['policy_question'], 'kind': 'request', 'target': 'policy'},
                    {'quote': '政策资料截止日是2018-07-06', 'kind': 'constraint', 'target': 'none'}])
        for mode, calls in [('accepted', 2), ('missing_gap', 1), ('wrong_scope', 1), ('tampered_file', 1)]:
            def factory(stage):
                model = Mock()
                def complete(**kw):
                    if stage == 'planning': value = p
                    else:
                        payload = json.loads(kw['messages'][1]['content'])
                        value = {'claims': [{'text': 'Synthetic intentionally incomplete answer',
                                             'citations': [payload['evidence'][0]['id']]}]}
                    return ModelResponse(text=json.dumps(value), metadata={'finish_reason': 'stop'})
                model.complete.side_effect = complete
                return model
            def review(packet):
                v = template(packet)
                v['overall'] = {'status': 'pass', 'reason': 'Synthetic review'}
                for row in v['items']:
                    row.update(status='covered' if packet['stage'] == 'plan' else 'missing',
                               reason='Synthetic decision')
                if packet['stage'] == 'plan':
                    self.assertEqual(packet['artifact']['status'], 'needs_gap_review')
                    v['gap_review'] = approve(packet['artifact']['gap_audit'])
                    if mode == 'missing_gap': del v['gap_review']
                    if mode == 'wrong_scope': v['items'][0]['status'] = 'wrong_scope'
                    if mode == 'tampered_file':
                        Path(packet['output'], 'preview.json').write_text('{}')
                return v
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / 'run'
                result = run_batch(config(), out, reviewer=review, reviewer_id='fixture',
                    source_kind='fixture', model_factory=factory, checklist_review=True, host_gap_review=True)
                self.assertEqual(len(result['calls']), calls)
                self.assertEqual(result['cases'][1]['status'], 'not_run')
                self.assertEqual((out / 'D89-1/delivery/gap-review.json').exists(), mode == 'accepted')
                self.assertEqual(json.loads((out / 'manifest.json').read_text())['version'], 'development-smoke-0103')


if __name__ == '__main__': unittest.main()
