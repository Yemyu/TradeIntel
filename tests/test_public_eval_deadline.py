import hashlib
import json
from pathlib import Path
import signal
import tempfile
import threading
import time
import unittest

from scripts import run_public_brief_eval as runner
from src.tradeintel_ai.public_eval_ledger import load, DuplicatePublicRun


class DeadlineTests(unittest.TestCase):
    def test_heartbeat_cannot_extend_deadline(self):
        before = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()
        with self.assertRaises(runner.ProviderDeadlineExceeded):
            with runner._provider_deadline(.04):
                for _ in range(100):
                    time.sleep(.01)
        self.assertLess(time.monotonic() - started, .8)
        self.assertEqual(signal.getsignal(signal.SIGALRM), before)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0., 0.))

    def test_success_restores_handler(self):
        before = signal.getsignal(signal.SIGALRM)
        with runner._provider_deadline(1):
            pass
        self.assertEqual(signal.getsignal(signal.SIGALRM), before)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0., 0.))

    def test_existing_timer_is_not_overwritten(self):
        signal.setitimer(signal.ITIMER_REAL, 10)
        try:
            with self.assertRaisesRegex(ValueError, '已有'):
                with runner._provider_deadline(1):
                    self.fail('must not execute')
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 8)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

    def test_worker_thread_rejected(self):
        errors = []
        def worker():
            try:
                runner._require_deadline_support()
            except ValueError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)

    def fixture(self, root):
        package = root / 'package'
        files = {}
        for name, value in [('requests/q1/messages.json', [{'role': 'user', 'content': 'fixture'}]),
                            ('host_artifacts/q1/response.json', {
                                'report': {}, 'report_sha256': None, 'evidence_sha256': None}),
                            ('host_artifacts/q1/snapshot.json', {
                                'protocol': 'public-brief-explanation-v1',
                                'messages': [{'role': 'user', 'content': 'fixture'}],
                                'report': {}, 'report_sha256': None, 'evidence_sha256': None})]:
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = package / 'MANIFEST.json'
        manifest.write_text(json.dumps({'schema_version': 'public-service-candidate-v1',
                                        'files_sha256': files}))
        return dict(provider={'id': 'fixture', 'model_id': 'fixture', 'base_url': 'https://invalid.local'},
                    package_path=package, output=root / 'out', question_id='q1',
                    matrix_path=root / 'unused',
                    freeze={'package_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
                            'params': {'timeout_seconds': .04}},
                    freeze_sha='0' * 64, ledger_root=root / 'ledger',
                    execution_channel='offline_injected')

    def test_deadline_and_interrupt_journal_and_prevent_retry(self):
        for kind in ['wall_clock_deadline', 'operator_interrupted', 'transport_error']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                args = self.fixture(Path(temp))
                calls = []
                def provider(**kwargs):
                    calls.append(1)
                    if kind == 'operator_interrupted':
                        raise KeyboardInterrupt()
                    if kind == 'transport_error':
                        raise OSError('fixture transport failure')
                    # Exception-catching adapters must not swallow the deadline.
                    try:
                        time.sleep(1)
                    except Exception:
                        self.fail('deadline was swallowed')
                result = runner._run_one_question(**args, provider_call=provider)
                self.assertEqual(result['status'], 'unknown_outcome')
                self.assertEqual(result['error_kind'], kind)
                self.assertEqual(result['api_calls'], 0)
                saved = json.loads((args['output'] / 'q1/run.json').read_text())
                self.assertEqual(saved, result)
                event = load(args['ledger_root'])['events'][-1]
                self.assertEqual(event['event'], 'unknown_outcome')
                args['output'] = Path(temp) / 'different-output'
                with self.assertRaises(DuplicatePublicRun):
                    runner._run_one_question(**args, provider_call=provider)
                self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
