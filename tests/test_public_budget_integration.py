"""Offline execution and score integration; no provider or credential access."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_public_brief_eval as runner
from scripts.score_public_brief_eval import collect_results


class BudgetIntegrationTests(unittest.TestCase):
    def execute(self, root, *, chars=2000, usage=None, finish='stop', malformed=False,
                oversized=False, protocol='v3'):
        package = root / 'package'
        report_path = runner.DEFAULT_PACKAGE / 'host_artifacts/q1/response.json'
        host = json.loads(report_path.read_text())
        answer = {'schema_version': 'public-brief-explanation-v1', 'interpretations': [
            {'observation_id': f'o{i+1}', 'kind': 'meaning',
             'text': '中' * min(350, max(0, chars-i*350))} for i in range(6)], 'watchlist': []}
        raw = json.dumps(answer, ensure_ascii=False)
        if malformed:
            raw = raw.replace('"schema_version":', '"schema_version":"duplicate","schema_version":', 1)
        if oversized:
            raw = 'x' * 65537
        files = {}
        for name, value in [('requests/q1/messages.json', [{'role':'user','content':'fixture'}]),
                            ('host_artifacts/q1/response.json', host)]:
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = package / 'MANIFEST.json'
        manifest.write_text(json.dumps({'files_sha256': files}))
        params = {'timeout_seconds': 1, 'max_tokens':8192, 'thinking':{'type':'enabled'},
                  'body_max_bytes':65536}
        params.update({'budget_protocol':'v3', 'body_max_chars':2000} if protocol=='v3'
                      else {'body_max_tokens':2000})
        result = runner._run_one_question(
            provider={'id':'fixture', 'model_id':'fixture', 'base_url':'https://invalid.local'},
            package_path=package, output=root/'results'/'run', question_id='q1',
            matrix_path=root/'unused',
            freeze={'params':params, 'package_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()},
            freeze_sha='a'*64, ledger_root=root/'ledger', execution_channel='offline_injected',
            provider_call=lambda **_: (raw, {'finish_reason':finish,
                'usage': {'completion_tokens':5000} if usage is None else usage}))
        return result

    def test_valid_boundary_reaches_review_and_over_boundary_preserves_structure(self):
        for chars in (2000, 2001):
            with self.subTest(chars=chars), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result = self.execute(root, chars=chars)
                self.assertEqual(result['status'], 'awaiting_semantic_review' if chars==2000
                                 else 'blocked_output_budget')
                self.assertEqual(result['output_budget']['body_chars'], chars)
                saved = json.loads((root/'results/run/q1/validation.json').read_text())
                self.assertEqual(saved['status'], 'manual_review_required')
                score = collect_results(results_root=root/'results', ledger_root=root/'ledger')
                # No human review exists: neither result may count as a whole pass.
                self.assertNotIn('"whole_pass": true', json.dumps(score))
                self.assertIn('"structure_result": "passed"', json.dumps(score))

    def test_usage_unknown_and_cost_excess_stop_after_structure(self):
        for usage, reason in [({},'usage_unknown'), ({'completion_tokens':True},'usage_unknown'),
                              ({'completion_tokens':8193},'total_output_tokens_exceeded')]:
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as tmp:
                result = self.execute(Path(tmp), usage=usage)
                self.assertEqual(result['status'], 'blocked_output_budget')
                self.assertEqual(result['output_budget']['reason'], reason)
                self.assertEqual(result['validation']['status'], 'manual_review_required')

    def test_raw_bytes_and_finish_gate_do_not_parse(self):
        for options, status in [({'oversized':True},'blocked_output_budget'),
                                ({'finish':'length'},'invalid_response')]:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as tmp:
                with patch.object(runner, 'parse_public', side_effect=AssertionError('must not parse')) as parse:
                    result = self.execute(Path(tmp), **options)
                parse.assert_not_called()
                self.assertEqual(result['status'], status)

    def test_duplicate_json_key_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.execute(Path(tmp), malformed=True)['status'], 'invalid_response')

    def test_v2_keeps_estimate_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.execute(Path(tmp), protocol='v2')
            self.assertEqual(result['status'], 'blocked_output_budget')
            self.assertEqual(result['output_budget']['body_method'], 'estimate')

    def test_protocol_tampering_rejected(self):
        provider = json.loads(runner.DEFAULT_MATRIX.read_text())['candidates'][2]
        original = runner.build_freeze_spec(provider=provider, package_path=runner.DEFAULT_PACKAGE,
                                           budget_protocol='v3')
        for value in ('v2', 'v4', None):
            changed = copy.deepcopy(original)
            if value is None:
                changed['params'].pop('budget_protocol')
            else:
                changed['params']['budget_protocol'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.verify_freeze(freeze=changed, provider=provider,
                                     package_path=runner.DEFAULT_PACKAGE, allow_candidate=True)


if __name__ == '__main__':
    unittest.main()
