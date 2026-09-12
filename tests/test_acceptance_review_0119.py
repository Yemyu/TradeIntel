"""Regression cases for the 0118 review; no external provider calls."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, digest, validate_fact_review
from tradeintel_ai.prospective_runner import default_cases, run_synthetic_batch, _independent_trade_baseline
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
        case = replace(default_cases()[2], facts=())
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


if __name__ == '__main__':
    unittest.main()
