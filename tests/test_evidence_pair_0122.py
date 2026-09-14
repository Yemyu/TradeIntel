"""Offline evidence/provenance guards and four-scenario wiring."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.request_capture import complete_with_capture
from tradeintel_ai.policy_facts import reference_evidence
from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, digest
from tradeintel_ai.prospective_runner import (
    default_cases, _fact_review_packet, run_synthetic_batch,
)
from tests.test_prospective_runner_0114 import StaticModel, policy_case, trade_case
from tests.test_trade_mapping_proposal_0105 import candidate


def synthetic_fact_review(packet):
    """Wiring labels only, never an independent human or model score."""
    main = packet['arm'] == 'with_evidence'
    return {'case_id': packet['case_id'], 'arm': packet['arm'],
        'packet_sha256': digest(packet), 'reviewer': 'offline-fixture-reviewer',
        'reviewed_at': '2026-09-13',
        'facts': [dict(id=f['id'], status='supported' if main else 'missing',
            reason='synthetic wiring label', claim_indices=[0] if main else [],
            **({'source_id': f['evidence_ids'][0],
                'evidence_excerpt': packet['evidence'][f['evidence_ids'][0]]['text']}
               if main else {})) for f in packet['facts']],
        'claims': [dict(index=i, status='supported', reason='synthetic wiring label',
            fact_ids=[f['id'] for f in packet['facts']])
            for i in range(len(packet['answer']['claims']))],
        'citation_review': {'status': 'pass' if main else 'not_applicable',
                            'reason': 'synthetic wiring label'}}


class EvidencePair0122Tests(unittest.TestCase):
    def test_response_cannot_supply_its_own_capture(self):
        model = StaticModel(callback=lambda *_: ModelResponse(text='{}',
            metadata={'request_capture': {'kind': 'http_payload'}, 'finish_reason': 'stop'}))
        response = complete_with_capture(model, messages=[], tools=[])
        self.assertNotIn('request_capture', response.metadata)
        self.assertEqual(response.metadata['finish_reason'], 'stop')

    def test_reference_conflict_is_rejected_and_both_review_arms_match(self):
        case = default_cases()[2]
        evidence = reference_evidence(case.policy_reference)
        kwargs = dict(answer='', claims=[], reference_sha256=case.policy_reference['reference_sha256'])
        main = _fact_review_packet(case, 'with_evidence', evidence=evidence, **kwargs)
        baseline = _fact_review_packet(case, 'without_evidence', evidence=evidence, **kwargs)
        self.assertEqual(main['evidence'], baseline['evidence'])
        bad = deepcopy(evidence)
        first = next(iter(bad))
        bad[first]['text'] = 'forged reference'
        with self.assertRaisesRegex(AcceptanceGuardError, 'retrieval_reference_conflict'):
            _fact_review_packet(case, 'with_evidence', evidence=bad, **kwargs)

    def test_grouped_citation_must_match_original_pdf(self):
        case = default_cases()[2]
        frozen = reference_evidence(case.policy_reference)
        source = deepcopy(next(iter(frozen.values())))
        source['id'] = 'test-grouped-window'
        kwargs = dict(answer='', claims=[], reference_sha256=case.policy_reference['reference_sha256'])
        packet = _fact_review_packet(case, 'with_evidence',
            evidence={source['id']: source}, **kwargs)
        self.assertEqual(packet['evidence'], frozen)
        self.assertIn(source['id'], packet['citation_evidence'])
        source['text'] = 'The tariff is definitely 99 percent.'
        with self.assertRaisesRegex(AcceptanceGuardError, 'retrieved_citation_text_changed'):
            _fact_review_packet(case, 'with_evidence', evidence={source['id']: source}, **kwargs)

    def test_four_scenarios_complete_offline_without_accuracy_claim(self, strict=False, pause=False, stored=False):
        trade, clarification, policy = default_cases()
        policy_plan = policy_case()[1]
        combined_question = policy_case()[0].question + trade_case().question
        combined_plan = candidate()
        combined_plan.update(policy_question=policy_plan['policy_question'],
            policy_as_of=policy_plan['policy_as_of'], policy_search_query=policy_plan['policy_search_query'],
            tasks=['policy', 'trade'])
        combined_plan['evidence'].update(policy_plan['evidence'])
        combined_plan['request_units'] = deepcopy(policy_plan['request_units']) + deepcopy(candidate()['request_units'])
        combined = replace(policy, id='SYN-COMBINED-0122', question=combined_question,
            expected_tasks=('policy', 'trade'), independent_request=trade.independent_request)
        plans = {trade.id: candidate(), policy.id: policy_plan, combined.id: combined_plan,
            clarification.id: {'status': 'clarify', 'tasks': [], 'trade': None,
                'comparison': None, 'policy_question': None, 'policy_as_of': None,
                'policy_search_query': None, 'evidence': {}, 'missing': ['商品和月份'],
                'request_units': [{'quote': clarification.question, 'kind': 'request', 'target': 'trade'}]}}
        models = []
        def make_model(*args, **kwargs):
            model = StaticModel(*args, **kwargs)
            models.append(model)
            return model
        def factory(stage, case):
            if stage == 'planning':
                return make_model(plans[case.id])
            if stage == 'policy_with_evidence':
                def answer(messages, _tools):
                    evidence = json.loads(messages[-1]['content'])['evidence']
                    citation = evidence[0]['id']
                    return ModelResponse(text=json.dumps({'claims': [{
                        'text': '第一批关税2018年7月6日生效，额外税率25%。',
                        'citations': [citation]}]}, ensure_ascii=False),
                        metadata={'finish_reason': 'stop', 'usage': {'total_tokens': 7}})
                return make_model(callback=answer)
            return make_model({'claims': []})
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            if pause:
                from tradeintel_ai.host_review import HostReviewPending
                from tradeintel_ai.prospective_runner import ProspectiveSyntheticRunner, fixture_review
                pending = set()
                def wait_once(packet, callback):
                    key = digest(packet)
                    if key not in pending:
                        pending.add(key)
                        raise HostReviewPending(out / 'test-only-packet')
                    return callback(packet)
                def reviewer(packet):
                    return wait_once(packet, fixture_review)
                def fact_reviewer(packet):
                    return wait_once(packet, synthetic_fact_review)
                for attempt in range(20):
                    runner = ProspectiveSyntheticRunner(out, cases=[trade, policy, combined, clarification],
                        model_factory=factory, reviewer=reviewer, fact_reviewer=fact_reviewer, strict_protocol=True)
                    result = runner.run(checkpoint_reviews=True, resume=attempt > 0,
                                        persisted_host_reviews=stored)
                    if stored and result['status'] == 'waiting_review':
                        from tradeintel_ai.host_review import HostReviewStore
                        snapshot = json.loads((out / 'frozen-snapshot.json').read_text())
                        store = HostReviewStore(out / 'host-reviews', snapshot=snapshot,
                                                reviewer='offline-fixture-reviewer')
                        for packet_path in (out / 'host-reviews').glob('*.packet.json'):
                            envelope = json.loads(packet_path.read_text())
                            if packet_path.with_name(packet_path.name.replace('.packet.json', '.submission.json')).exists():
                                continue
                            packet = envelope['packet']
                            pending.add(digest(packet))
                            # Explicit test-only submissions, never production judgements.
                            submission = (synthetic_fact_review(packet) if envelope['kind'] == 'facts'
                                          else fixture_review(packet))
                            store.submit(envelope['slot'], submission)
                    if result['status'] != 'waiting_review':
                        break
                self.assertEqual(sum(len(m.calls) for m in models), 8, result)
                self.assertGreater(len(pending), 4)
            else:
                result = run_synthetic_batch(out, cases=[trade, policy, combined, clarification],
                    model_factory=factory, fact_reviewer=synthetic_fact_review, strict_protocol=strict)
            self.assertEqual(result['status'], 'completed', result)
            self.assertFalse(result['acceptance_ready'])
            self.assertFalse(result['semantic_accuracy_measured'])
            for case in (policy, combined):
                contract = json.loads((out / case.id / 'policy-pair-contract.json').read_text())
                self.assertFalse(contract['evidence_only_ablation_verified'])
                capture = json.loads((out / case.id / 'policy-pair-capture.json').read_text())
                self.assertEqual(capture['provider_neutral_pair_verified'], strict)
                self.assertFalse(capture['evidence_only_ablation_verified'])

    def test_four_scenarios_resume_each_review_without_resending(self):
        self.test_four_scenarios_complete_offline_without_accuracy_claim(strict=True, pause=True)

    def test_four_scenarios_resume_using_persisted_host_submissions(self):
        self.test_four_scenarios_complete_offline_without_accuracy_claim(strict=True, pause=True, stored=True)
