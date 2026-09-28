"""Offline safety checks for the one-attempt announcement extraction runner."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from scripts import run_policy_extraction_pilot_once as runner


class PolicyExtractionPilotRunnerTests(unittest.TestCase):
    def test_frozen_r2_body_and_package(self):
        body, package, _ = runner._body("r2")
        self.assertEqual(package["status"], "verified")
        self.assertEqual(len(body), 23866)

    def test_no_successor_without_review(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "r2 has not produced"):
                runner._prior_gate("d2", Path(folder))

    def test_network_failure_occupies_case_without_retry(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            calls = []

            def fail_once(_body: bytes, _key: str) -> bytes:
                calls.append(1)
                raise TimeoutError("sensitive provider detail")

            with patch.object(runner, "_root", return_value=root), \
                    patch.object(runner, "_config", return_value=SimpleNamespace(api_key="test-only")), \
                    patch.object(runner, "_post", side_effect=fail_once):
                result = runner.run_once("r2")
                self.assertEqual(result, {"case": "r2", "status": "unknown_outcome",
                                          "error_type": "TimeoutError"})
                self.assertEqual(calls, [1])
                self.assertNotIn("sensitive provider detail", (root / "r2.json").read_text())
                with self.assertRaisesRegex(ValueError, "already has an attempt"):
                    runner.run_once("r2")
                self.assertEqual(calls, [1])

    def test_prior_gate_requires_bound_review_and_usage(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            raw = "a" * 64
            runner._atomic(root / "r2.json", {
                "status": "needs_review", "raw_response_sha256": raw,
                "peak_cost_estimate_usd": 0.01,
            })
            runner._atomic(root / "r2.review.json", {
                "decision": "pass", "response_sha256": "b" * 64,
            })
            with self.assertRaisesRegex(ValueError, "semantic review"):
                runner._prior_gate("d2", root)
            runner._atomic(root / "r2.review.json", {
                "decision": "pass", "response_sha256": raw,
            })
            self.assertLess(runner._prior_gate("d2", root), runner.LOCAL_BUDGET_USD)

    def test_truncated_reasoning_only_response_is_saved_and_blocks_retry(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            provider = {"model": "deepseek-flash", "usage": {
                "prompt_tokens": 4705, "completion_tokens": 4096,
                "completion_tokens_details": {"reasoning_tokens": 4096}},
                "choices": [{"finish_reason": "length", "message": {
                    "content": "", "reasoning_content": "unfinished"}}]}
            with patch.object(runner, "_root", return_value=root), \
                    patch.object(runner, "_config", return_value=SimpleNamespace(api_key="test-only")), \
                    patch.object(runner, "_post", return_value=json.dumps(provider).encode()):
                result = runner.run_once("r2")
                self.assertEqual(result["status"], "invalid_answer")
                self.assertTrue((root / "r2.response.json").is_file())
                self.assertFalse((root / "r2.draft.json").exists())
                with self.assertRaisesRegex(ValueError, "already has an attempt"):
                    runner.run_once("r2")


if __name__ == "__main__":
    unittest.main()
