import json
from pathlib import Path
import tempfile
import unittest
import shutil
from unittest.mock import patch

from scripts.run_public_brief_eval import (
    DEFAULT_MATRIX,
    DEFAULT_PACKAGE,
    _validate_provider,
    _output_budget,
    preflight,
    run,
)


class PublicBriefEvalRunnerTests(unittest.TestCase):
    def test_matrix_has_the_two_codex_candidates_and_four_api_slots(self):
        matrix = json.loads(DEFAULT_MATRIX.read_text(encoding="utf-8"))
        ids = [item["id"] for item in matrix["candidates"]]
        self.assertEqual(ids, ["codex-luna-highest", "codex-sol-high", "glm-46v",
                               "glm-45-air", "deepseek-flash", "deepseek-pro"])

    def test_api_preflight_is_offline_and_verifies_candidate_hashes(self):
        result = preflight(provider_id="glm-46v", package_path=DEFAULT_PACKAGE)
        self.assertEqual(result["status"], "preflight_passed")
        self.assertEqual(result["api_calls"], 0)
        self.assertEqual([item["id"] for item in result["questions"]], ["q1", "q2", "q3", "q4"])

    def test_codex_candidates_are_preflight_only_manual_sessions(self):
        for provider_id, model_id, effort in (
                ("codex-luna-highest", "gpt-5.6-luna", "max"),
                ("codex-sol-high", "gpt-5.6-sol", "high")):
            result = preflight(provider_id=provider_id, package_path=DEFAULT_PACKAGE)
            self.assertEqual(result["status"], "preflight_passed")
            self.assertEqual(result["api_calls"], 0)
            self.assertEqual(result["execution_channel"], "codex_session")
            self.assertEqual(result["scoring"], "manual_independent_session_required")
            self.assertEqual(result["provider"]["model_id"], model_id)
            self.assertEqual(result["provider"]["reasoning_effort"], effort)

    def test_codex_candidate_cannot_be_sent_through_api_executor(self):
        provider = preflight(provider_id="codex-luna-highest")["provider"]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "never-created"
            with self.assertRaisesRegex(ValueError, "独立无历史上下文"):
                run(provider=provider, package_path=DEFAULT_PACKAGE, output=output,
                    execute=True, authorize_real_call=True)
            self.assertFalse(output.exists())

    def test_unknown_model_id_and_non_https_endpoint_are_rejected(self):
        provider = {
            "id": "test-provider", "channel": "openai_compatible_api",
            "model_id": "", "base_url": "http://example.invalid/v1",
            "secret_env": "TRADEINTEL_TEST_KEY",
            "request_params": {"max_tokens": 2000, "thinking": {"type": "disabled"}},
        }
        with self.assertRaises(ValueError):
            _validate_provider(provider)

    def test_dry_run_never_creates_output_or_reads_a_key(self):
        result = preflight(provider_id="glm-45-air", package_path=DEFAULT_PACKAGE)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            report = run(provider=result["provider"], package_path=DEFAULT_PACKAGE,
                         output=output, execute=False, authorize_real_call=False,
                         question_ids=("q1", "q2"))
            self.assertEqual(report["api_calls"], 0)
            self.assertFalse(output.exists())

    def test_deepseek_restores_previously_probed_identity(self):
        result = preflight(provider_id='deepseek-flash', package_path=DEFAULT_PACKAGE)
        self.assertEqual(result['provider']['model_id'], 'deepseek-flash')

    def test_candidate_cannot_make_real_calls_even_with_authorization(self):
        provider = preflight(provider_id='glm-46v')['provider']
        with tempfile.TemporaryDirectory() as temp, \
                patch('scripts.run_public_brief_eval._PublicEvalModel') as client:
            output = Path(temp) / 'never-created'
            with self.assertRaisesRegex(ValueError, '真实执行暂未放行'):
                run(provider=provider, package_path=DEFAULT_PACKAGE, output=output,
                    execute=True, authorize_real_call=True)
            client.assert_not_called()
            self.assertFalse(output.exists())

    def test_empty_hash_map_and_forged_budget_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'package'
            shutil.copytree(DEFAULT_PACKAGE, package)
            path = package / 'MANIFEST.json'
            original = json.loads(path.read_text())
            changed = json.loads(path.read_text())
            changed['files_sha256'] = {}
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, '未全部登记摘要'):
                preflight(provider_id='glm-46v', package_path=package)
            original['scenarios']['q1']['input_estimate']['tokens'] = 1
            path.write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError, '预算'):
                preflight(provider_id='glm-46v', package_path=package)

    def test_output_budget_prefers_reported_tokens_and_blocks_large_answer(self):
        self.assertTrue(_output_budget("短回答", {"completion_tokens": 3})["within_gate"])
        blocked = _output_budget("很长" * 2500, {})
        self.assertFalse(blocked["within_gate"])
        self.assertEqual(blocked["method"], "fallback_estimate")


if __name__ == "__main__":
    unittest.main()
