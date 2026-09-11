import json
import unittest
from pathlib import Path

from scripts.run_intent_development import preflight, run


class IntentRunnerTests(unittest.TestCase):
    def test_frozen_preflight_is_offline_and_bounded(self):
        manifest, cases = preflight()
        self.assertEqual(len(cases), 12)
        self.assertEqual(manifest['maximum_api_requests'], 12)
        self.assertFalse(manifest['tools_exposed'])
        result = run()
        self.assertEqual(result['api_requests'], 0)
        self.assertEqual(result['status'], 'preflight_passed')

    def test_execution_requires_key_before_creating_files(self):
        target = Path('tmp/intent-development/test-no-key.json')
        journal = target.with_suffix('.jsonl')
        target.unlink(missing_ok=True)
        journal.unlink(missing_ok=True)
        with self.assertRaises(ValueError):
            run(execute=True, output=target, api_key='')
        self.assertFalse(target.exists())
        self.assertFalse(journal.exists())

    def test_manifest_has_runner_fingerprint(self):
        manifest = json.loads(Path('evals/intent_development_manifest.json').read_text())
        self.assertIn('scripts/run_intent_development.py', manifest['files'])


if __name__ == '__main__': unittest.main()
