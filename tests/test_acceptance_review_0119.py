"""Regression cases for the 0118 review; no external provider calls."""
from copy import deepcopy
from dataclasses import replace
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, digest, validate_fact_review
from tradeintel_ai.prospective_runner import (
    _independent_trade_baseline,
    _fact_review_packet,
    _policy_pair_packet,
    default_cases,
    run_synthetic_batch,
)
from tradeintel_ai.policy_facts import reference_evidence
from tests.test_prospective_runner_0114 import StaticModel, policy_case


def policy_factory(stage, _case):
    if stage == 'planning':
        return StaticModel(policy_case()[1])
    if stage == 'policy_with_evidence':
        def answer(messages, _tools):
            from tradeintel_ai.agent import ModelResponse
            citation = json.loads(messages[-1]['content'])['evidence'][0]['id']
            return ModelResponse(text=json.dumps({'claims': [
                {'text': '未经核对的政策草稿', 'citations': [citation]}]}, ensure_ascii=False),
                metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 7}})
        return StaticModel(callback=answer)
    return StaticModel({'answer': '无法确定', 'claims': []})


def reject_facts(packet):
    return {'case_id': packet['case_id'], 'arm': packet['arm'],
            'packet_sha256': digest(packet), 'reviewer': 'offline-fixture-reviewer',
            'reviewed_at': '2026-09-13T00:00:00Z',
            'facts': [{'id': fact['id'], 'status': 'missing', 'reason': '没有回答所需事实',
                       'claim_indices': []} for fact in packet['facts']],
            'claims': [{'index': i, 'status': 'unsupported', 'reason': '内容无支持',
                        'fact_ids': []} for i in range(len(packet['answer']['claims']))],
            'citation_review': {'status': 'fail' if packet['arm'] == 'with_evidence'
                                else 'not_applicable', 'reason': '引用无法支持主张'}}


class AcceptanceReview0119Tests(unittest.TestCase):
    def test_declared_settings_are_not_claimed_as_actual_http_payload(self):
        # Capture-only legacy fixture: strict cases may no longer drop facts.
        case = replace(default_cases()[2], facts=(), policy_reference=None)
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            run_synthetic_batch(out, cases=[case], model_factory=policy_factory)
            record = json.loads((out / case.id / 'policy-pair-capture.json').read_text())
            self.assertFalse(record['actual_payloads_verified'])

    def test_pending_review_cannot_complete_protocol(self):
        with TemporaryDirectory() as tmp:
            result = run_synthetic_batch(Path(tmp) / 'run', cases=[default_cases()[2]],
                                         model_factory=policy_factory)
            self.assertEqual(result['stop_reason'], 'fact_review_pending')
            self.assertFalse(result['synthetic_protocol_completed'])

    def test_negative_main_fact_review_stops_before_baseline_call(self):
        with TemporaryDirectory() as tmp:
            result = run_synthetic_batch(Path(tmp) / 'run', cases=[default_cases()[2]],
                                         model_factory=policy_factory, fact_reviewer=reject_facts)
            self.assertEqual(result['stop_reason'], 'main_fact_review_rejected')
            self.assertEqual(result['stage_counts']['policy_no_evidence'], 0)
            self.assertFalse(result['synthetic_protocol_completed'])

    def test_bad_independent_arithmetic_cannot_be_used_as_baseline(self):
        with patch('tradeintel_ai.prospective_runner._direct_trade_recompute',
                   return_value={'checks': {'passed': False}}):
            with self.assertRaisesRegex(AcceptanceGuardError, 'baseline_recompute_failed'):
                _independent_trade_baseline(default_cases()[0])

    def test_without_evidence_fact_review_still_needs_review_evidence(self):
        packet = {'case_id': 'P1', 'arm': 'without_evidence',
                  'facts': [{'id': 'rate'}],
                  'answer': {'claims': [{'text': '税率25%', 'citations': []}]},
                  'evidence': {}}
        submission = {'case_id': 'P1', 'arm': 'without_evidence',
                      'packet_sha256': digest(packet), 'reviewer': 'human',
                      'reviewed_at': '2026-09-13T00:00:00Z',
                      'facts': [{'id': 'rate', 'status': 'supported', 'reason': '猜测',
                                 'claim_indices': [0]}],
                      'claims': [{'index': 0, 'status': 'supported', 'reason': '猜测',
                                  'fact_ids': ['rate']}]}
        with self.assertRaises(AcceptanceGuardError):
            validate_fact_review(packet, submission)

    def test_strict_fact_review_binds_each_fact_to_its_declared_source(self):
        case = default_cases()[2]
        packet = _fact_review_packet(
            case, 'with_evidence', answer='事实',
            claims=[{'text': '事实', 'citations': []}],
            evidence=reference_evidence(case.policy_reference),
            reference_sha256=case.policy_reference['reference_sha256'],
        )
        submission = {
            'case_id': case.id, 'arm': 'with_evidence',
            'packet_sha256': digest(packet), 'reviewer': 'human',
            'reviewed_at': '2026-09-13T00:00:00Z',
            'facts': [{
                'id': case.facts[0]['id'], 'status': 'supported',
                'reason': '引用存在但不是该事实声明的允许来源', 'claim_indices': [0],
                'source_id': case.facts[1]['evidence_ids'][0],
                'evidence_excerpt': packet['evidence'][case.facts[1]['evidence_ids'][0]]['text'],
            }] + [{
                'id': fact['id'], 'status': 'missing', 'reason': '未审支持', 'claim_indices': []
            } for fact in case.facts[1:]],
            'claims': [{'index': 0, 'status': 'supported', 'reason': '有来源',
                        'fact_ids': [case.facts[0]['id']]}],
            'citation_review': {'status': 'pass', 'reason': '结构检查'},
        }
        with self.assertRaisesRegex(AcceptanceGuardError, 'not bound'):
            validate_fact_review(packet, submission)

    def test_strict_fact_review_rejects_unknown_claim_citation(self):
        case = default_cases()[2]
        packet = _fact_review_packet(
            case, 'with_evidence', answer='事实',
            claims=[{'text': '事实', 'citations': ['not-in-packet']}],
            evidence=reference_evidence(case.policy_reference),
            reference_sha256=case.policy_reference['reference_sha256'],
        )
        submission = {
            'case_id': case.id, 'arm': 'with_evidence',
            'packet_sha256': digest(packet), 'reviewer': 'human',
            'reviewed_at': '2026-09-13T00:00:00Z', 'facts': [
                {'id': fact['id'], 'status': 'missing', 'reason': '未支持', 'claim_indices': []}
                for fact in case.facts
            ],
            'claims': [{'index': 0, 'status': 'unsupported', 'reason': '引用无效', 'fact_ids': []}],
            'citation_review': {'status': 'fail', 'reason': '引用无效'},
        }
        with self.assertRaisesRegex(AcceptanceGuardError, 'unknown'):
            validate_fact_review(packet, submission)

    def test_policy_reference_mismatch_stops_before_policy_pair(self):
        case = default_cases()[2]
        preview = {'request': {
            'policy_question': '另一份政策问题', 'policy_as_of': case.policy_reference['as_of']
        }}
        with self.assertRaisesRegex(AcceptanceGuardError, 'policy_reference_scope_mismatch'):
            _policy_pair_packet(case, preview, StaticModel({}), StaticModel({}))

    def test_registered_independent_baseline_materializes_host_window(self):
        case = replace(default_cases()[0])
        independent = deepcopy(case.independent_request)
        independent['trade']['months'] = None
        independent['comparison'] = {
            'kind': 'registered', 'comparison_id': 'immediate_post_same_months'
        }
        case = replace(case, independent_request=independent)
        baseline = _independent_trade_baseline(case)
        self.assertIsNone(baseline['request']['trade']['months'])
        self.assertEqual(len(baseline['execution_request']['trade']['months']), 10)
        self.assertTrue(baseline['independent_recompute']['checks']['passed'])

    def test_host_gap_gate_stops_when_no_separate_gap_reviewer_is_supplied(self):
        class GapWorkflow:
            def __init__(self, planner, **_kwargs):
                self.planner = planner

            def prepare(self, question, *, audit_output):
                self.planner.complete(
                    messages=[{'role': 'user', 'content': question}], tools=[]
                )
                return {
                    'status': 'needs_gap_review',
                    'tasks': ['trade'],
                    'executed': False,
                    'gap_review_required': True,
                    'gap_review_token': 'gap-token',
                    'gap_audit': {'version': 'host-gap-review-proposal-0102'},
                }

        case = replace(default_cases()[0], allow_host_gap_review=True)
        with TemporaryDirectory() as tmp:
            result = run_synthetic_batch(
                Path(tmp) / 'run', cases=[case],
                workflow_factory=lambda planner, **kwargs: GapWorkflow(planner, **kwargs),
                model_factory=lambda _stage, _case: StaticModel({'status': 'plan'}),
            )
        self.assertEqual(result['stop_reason'], 'gap_review_pending')
        self.assertEqual(result['stage_counts']['planning'], 1)
        self.assertEqual(result['stage_counts']['policy_with_evidence'], 0)

    def test_host_gap_review_must_finish_before_confirmation(self):
        approved = []

        class GapWorkflow:
            def __init__(self, planner, **_kwargs):
                self.planner = planner

            def prepare(self, question, *, audit_output):
                self.planner.complete(
                    messages=[{'role': 'user', 'content': question}], tools=[]
                )
                return {
                    'status': 'needs_gap_review', 'tasks': ['trade'],
                    'executed': False, 'gap_review_required': True,
                    'gap_review_token': 'gap-token',
                    'gap_audit': {'version': 'host-gap-review-proposal-0102'},
                }

            def approve_gap_review(self, token, submission, *, reviewer):
                approved.append((token, submission, reviewer))
                return {
                    'status': 'needs_confirmation', 'tasks': ['trade'],
                    'executed': False, 'confirmation_token': 'confirm-token',
                    'gap_review_required': True,
                    'gap_review': {'approved': True, 'reviewer': reviewer},
                }

            def confirm(self, token, output, *, model=None, source_kind='fixture'):
                self.assert_token = token
                output = Path(output)
                output.mkdir(parents=True, exist_ok=False)
                result_path = output / 'result.json'
                result_path.write_text('{}')
                marker = {
                    'status': 'complete', 'expected_files': ['result.json'],
                    'file_sha256': {
                        'result.json': hashlib.sha256(result_path.read_bytes()).hexdigest()
                    },
                    'execution_status': 'trade_draft', 'interrupted': False,
                }
                (output / 'delivery-status.json').write_text(json.dumps(marker))
                return {'status': 'trade_draft', 'tasks': ['trade']}

        def gap_reviewer(packet):
            self.assertEqual(packet['case_id'], 'RUN-TRADE-01')
            return {'gap_decision': 'accepted_separator'}

        from tests.test_prospective_runner_0114 import trade_case
        case = replace(trade_case(), allow_host_gap_review=True)
        with TemporaryDirectory() as tmp:
            result = run_synthetic_batch(
                Path(tmp) / 'run', cases=[case],
                workflow_factory=lambda planner, **kwargs: GapWorkflow(planner, **kwargs),
                model_factory=lambda _stage, _case: StaticModel({'status': 'plan'}),
                gap_reviewer=gap_reviewer,
            )
            self.assertTrue((Path(tmp) / 'run' / case.id / 'gap-review.json').is_file())
            self.assertTrue((Path(tmp) / 'run' / case.id / 'preview-after-gap.json').is_file())
        self.assertEqual(result['stop_reason'], 'acceptance_integration_incomplete_0116')
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0][0], 'gap-token')


if __name__ == '__main__':
    unittest.main()
