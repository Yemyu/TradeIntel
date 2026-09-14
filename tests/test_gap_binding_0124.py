"""Strict real-workflow separator review, with synthetic reviewer labels."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradeintel_ai.prospective_runner import default_cases, run_synthetic_batch
from tradeintel_ai.prospective_acceptance import ProspectiveCallLedger, FrozenInputChanged
from tradeintel_ai.quote_gap_audit import digest_audit
from tests.test_prospective_runner_0114 import StaticModel
from tests.test_trade_mapping_proposal_0105 import candidate


def separator_review(packet):
    audit = packet['gap_audit']
    return {'audit_sha256': digest_audit(audit), 'reviewer': 'offline-fixture-reviewer',
        'overall': {'status': 'pass', 'reason': 'synthetic separator check'},
        'gaps': [{**{key: g[key] for key in ('start', 'end', 'quote')},
                  'status': 'accepted_separator', 'reason': 'synthetic separator check'}
                 for g in audit['segments'] if g['source'] == 'host_gap' and g['quote'].strip()]}


class GapBinding0124Tests(unittest.TestCase):
    def test_persisted_gap_and_report_reviews_resume_without_replanning(self):
        from tradeintel_ai.prospective_runner import ProspectiveSyntheticRunner, fixture_review
        from tradeintel_ai.host_review import HostReviewStore
        from tradeintel_ai.prospective_acceptance import digest
        case = replace(default_cases()[0], allow_host_gap_review=True)
        plan = candidate()
        plan['request_units'][0]['quote'] = case.question[:-1]
        models = []
        def factory(*_):
            model = StaticModel(plan)
            models.append(model)
            return model
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            for attempt in range(8):
                runner = ProspectiveSyntheticRunner(out, cases=[case], strict_protocol=True,
                    model_factory=factory, gap_reviewer=separator_review)
                result = runner.run(checkpoint_reviews=True, persisted_host_reviews=True, resume=attempt > 0)
                if result['status'] != 'waiting_review':
                    break
                snapshot = json.loads((out / 'frozen-snapshot.json').read_text())
                store = HostReviewStore(out / 'host-reviews', snapshot=snapshot, reviewer='offline-fixture-reviewer')
                for path in (out / 'host-reviews').glob('*.packet.json'):
                    if path.with_name(path.name.replace('.packet.json', '.submission.json')).exists():
                        continue
                    envelope = json.loads(path.read_text())
                    packet = envelope['packet']
                    submission = separator_review(packet) if envelope['kind'] == 'gap' else fixture_review(packet)
                    submission['packet_sha256'] = digest(packet)
                    store.submit(envelope['slot'], submission)
            self.assertEqual(result['status'], 'completed', result.get('stop_reason'))
            self.assertEqual(sum(len(m.calls) for m in models), 1)

    def run_gap(self, root):
        case = replace(default_cases()[0], allow_host_gap_review=True)
        plan = candidate()
        plan['request_units'][0]['quote'] = case.question[:-1]
        return run_synthetic_batch(root, cases=[case], strict_protocol=True,
            model_factory=lambda *_: StaticModel(plan), gap_reviewer=separator_review)

    def test_real_gap_workflow_binds_all_review_materials(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = self.run_gap(out)
            self.assertEqual(result['status'], 'completed', result.get('stop_reason'))
            for name in ('packet', 'submission', 'outcome', 'review'):
                self.assertTrue((out / default_cases()[0].id / f'gap-{name}.json').is_file())

    def test_changed_gap_submission_blocks_finalization(self):
        original = ProspectiveCallLedger.finalize_reviewed
        def change(ledger, **kwargs):
            path = ledger.output / default_cases()[0].id / 'gap-submission.json'
            value = json.loads(path.read_text())
            value['overall']['status'] = 'fail'
            path.write_text(json.dumps(value))
            return original(ledger, **kwargs)
        with TemporaryDirectory() as tmp, patch.object(ProspectiveCallLedger, 'finalize_reviewed', change):
            with self.assertRaises(FrozenInputChanged):
                self.run_gap(Path(tmp) / 'run')
            state = json.loads((Path(tmp) / 'run' / 'ledger.json').read_text())
            self.assertEqual(state['status'], 'stopped')
            self.assertEqual(state['stop_reason'], 'frozen_inputs_changed')
