"""Offline controls: independent windows and immutable reviewed delivery."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradeintel_ai.prospective_runner import (
    default_cases, _independent_trade_baseline, _direct_trade_recompute,
    run_synthetic_batch,
    summary_with_comparison, EvidenceRegistryV21,
)
from tradeintel_ai.prospective_acceptance import (
    ProspectiveCallLedger, AcceptanceGuardError, freeze_dependencies,
    digest, validate_fact_review,
)
from tradeintel_ai.unified_research import inspect_delivery
from tests.test_prospective_runner_0114 import StaticModel, trade_case
from tests.test_trade_mapping_proposal_0105 import candidate


class ReviewBinding0121Tests(unittest.TestCase):
    def registered_result(self):
        case = default_cases()[0]
        request = deepcopy(case.independent_request)
        request['trade']['months'] = None
        request['comparison'] = {'kind': 'registered', 'comparison_id': 'immediate_post_same_months'}
        baseline = _independent_trade_baseline(replace(case, independent_request=request))
        return {'request': baseline['request'], 'summary': summary_with_comparison(
            baseline['data'], request['comparison'], EvidenceRegistryV21().repository)}

    def test_registered_full_workflow_compares_expanded_baseline(self):
        question = ('查询其他原产地整体美元消费进口额；比较登记窗口immediate_post_same_months；'
                    '只做描述性比较，不做因果分析；第一批关税，政策整体范围。')
        plan = candidate()
        plan['trade']['months'] = None
        plan['comparison'] = {'kind': 'registered', 'comparison_id': 'immediate_post_same_months'}
        plan['evidence']['trade.months'] = '登记窗口immediate_post_same_months'
        plan['evidence']['trade.comparison'] = '登记窗口immediate_post_same_months'
        plan['request_units'][0]['quote'] = question
        case = replace(trade_case(), question=question, run_controls=True,
                       independent_request={'trade': deepcopy(plan['trade']),
                                            'comparison': deepcopy(plan['comparison'])})
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = run_synthetic_batch(out, cases=[case], model_factory=lambda *_: StaticModel(plan))
            self.assertEqual(result['status'], 'completed', result)
            self.assertTrue(json.loads((out / case.id / 'scope-comparison.json').read_text())['scope_equal'])

    def test_registered_swapped_windows_and_consistent_arithmetic_fail(self):
        result = self.registered_result()
        self.assertTrue(_direct_trade_recompute(result)['checks']['passed'])
        comparison = result['summary']['comparison']
        for left, right in [('reference_months', 'current_months'),
                            ('reference_total_usd', 'current_total_usd')]:
            comparison[left], comparison[right] = comparison[right], comparison[left]
        change = comparison['current_total_usd'] - comparison['reference_total_usd']
        comparison['change_usd'] = change
        comparison['change_percent'] = str((Decimal(change) * 100 /
            Decimal(comparison['reference_total_usd'])).quantize(Decimal('0.01')))
        checks = _direct_trade_recompute(result)['checks']
        self.assertTrue(checks['series_equal'])
        self.assertFalse(checks['passed'])

    def test_registered_missing_month_cannot_define_its_own_expected_series(self):
        result = self.registered_result()
        removed = result['summary']['series'].pop()
        result['summary']['total_usd'] -= removed['value_usd']
        self.assertFalse(_direct_trade_recompute(result)['checks']['series_equal'])

    def test_report_and_matching_marker_rewrite_cannot_finalize(self):
        original = ProspectiveCallLedger.finalize_reviewed
        def tamper(ledger, **kwargs):
            directory = ledger.output / trade_case().id / 'delivery'
            marker_path = directory / 'delivery-status.json'
            marker = json.loads(marker_path.read_text())
            name = next(name for name in marker['expected_files'] if name.endswith('.md'))
            report = directory / name
            report.write_text(report.read_text() + '\nInjected false conclusion.\n')
            marker['file_sha256'][name] = hashlib.sha256(report.read_bytes()).hexdigest()
            marker_path.write_text(json.dumps(marker))
            self.assertTrue(inspect_delivery(directory)['verified'])
            return original(ledger, **kwargs)
        with TemporaryDirectory() as tmp, patch.object(ProspectiveCallLedger, 'finalize_reviewed', tamper):
            result = run_synthetic_batch(Path(tmp) / 'run',
                cases=[replace(trade_case(), run_controls=True)],
                model_factory=lambda *_: StaticModel(candidate()))
            self.assertEqual(result['status'], 'stopped')
            self.assertEqual(result['stop_reason'], 'frozen_inputs_changed')

    def test_fake_fact_approval_without_packet_cannot_bind(self):
        with TemporaryDirectory() as tmp:
            ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'run',
                frozen_snapshot=freeze_dependencies([Path(__file__)]))
            ledger.record_artifact('reviews/q-facts-with_evidence-decision.json', {'approved': True})
            with self.assertRaises(AcceptanceGuardError):
                ledger._fact_bindings('q', baseline=False)

    def test_fact_decision_is_recomputed_and_bound(self):
        packet = {'case_id': 'q', 'arm': 'with_evidence',
                  'facts': [{'id': 'rate', 'required_fact': 'rate'}],
                  'answer': {'claims': [{'text': '25%', 'citations': ['s']}]},
                  'evidence': {'s': {'text': 'rate 25%'}}}
        submission = {'case_id': 'q', 'arm': 'with_evidence', 'packet_sha256': digest(packet),
            'reviewer': 'offline-test', 'reviewed_at': '2026-09-13',
            'facts': [{'id': 'rate', 'status': 'supported', 'reason': 'fixture',
                       'claim_indices': [0], 'source_id': 's', 'evidence_excerpt': '25%'}],
            'claims': [{'index': 0, 'status': 'supported', 'reason': 'fixture', 'fact_ids': ['rate']}],
            'citation_review': {'status': 'pass', 'reason': 'fixture'}}
        for forged in (False, True):
            with self.subTest(forged=forged), TemporaryDirectory() as tmp:
                ledger = ProspectiveCallLedger(['q'], Path(tmp) / 'run',
                    frozen_snapshot=freeze_dependencies([Path(__file__)]))
                decision = validate_fact_review(packet, submission)
                if forged:
                    decision['fact_counts']['supported'] = 99
                for kind, value in [('packet', packet), ('submission', submission), ('decision', decision)]:
                    ledger.record_artifact(f'reviews/q-facts-with_evidence-{kind}.json', value)
                if forged:
                    with self.assertRaisesRegex(AcceptanceGuardError, 'recomputed'):
                        ledger._fact_bindings('q', baseline=False)
                else:
                    self.assertEqual(set(ledger._fact_bindings('q', baseline=False)), {'with_evidence'})
