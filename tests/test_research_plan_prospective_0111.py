import contextlib
import io
import json
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.preflight_research_plan_prospective_0111 import (
    QUESTIONS, REFERENCE, preflight,
)
from scripts import run_research_plan_prospective_0111 as runner


class Prospective0111PreflightTests(unittest.TestCase):
    def test_rejected_protocol_blocks_direct_calls_before_any_setup(self):
        with TemporaryDirectory() as tmp, patch.object(
                runner, 'validate_online_config', side_effect=AssertionError('setup reached')):
            out = Path(tmp) / 'run'
            with self.assertRaisesRegex(ValueError, '0112'):
                runner.run_online(None, out, interactive=lambda p: True, reviewer_id='fixture')
            self.assertFalse(out.exists())

    def test_rejected_protocol_blocks_cli_before_credentials(self):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(
                runner.getpass, 'getpass', side_effect=AssertionError('credential requested')):
            self.assertEqual(runner.main(['--execute', '--allow-online']), 2)

    def test_offline_output_cannot_claim_online_eligibility(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(runner.main(['--preflight']), 0)
        result = json.loads(out.getvalue())
        self.assertFalse(result['online_eligible'])
        self.assertEqual(result['acceptance_status'], 'audit_failed')

    def test_preflight_is_zero_api_and_has_fixed_split(self):
        with patch.object(runner, "ResearchPlannerModel",
                          side_effect=AssertionError("network")), \
             patch.object(runner, "ResearchPolicyModel",
                          side_effect=AssertionError("network")):
            report = preflight()
        self.assertEqual(report["status"], "preflight_passed")
        self.assertEqual(report["new_api_calls"], 0)
        self.assertEqual(report["counts"], {"support": 12, "clarification": 6, "boundary": 6})
        self.assertIsNone(report["semantic_scores"])

    def test_questions_and_references_are_not_the_retired_set(self):
        questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
        old = Path("evals/research_plan_acceptance_questions.jsonl")
        old_questions = {json.loads(line)["question"] for line in old.read_text(encoding="utf-8").splitlines()
                         if line.strip()}
        self.assertFalse(old_questions.intersection({row["question"] for row in questions}))
        refs = json.loads(REFERENCE.read_text(encoding="utf-8"))
        self.assertEqual(set(refs) - {"purpose"}, {row["id"] for row in questions})

    def test_runner_preflight_does_not_ask_for_key(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(
                runner.getpass, "getpass", side_effect=AssertionError("key requested")):
            self.assertEqual(runner.main(["--preflight"]), 0)
        self.assertIn('"new_api_calls": 0', out.getvalue())

    def test_online_requires_explicit_second_gate_before_key(self):
        with self.assertRaises(SystemExit) as ctx, patch.object(
                runner.getpass, "getpass", side_effect=AssertionError("key requested")):
            runner.main(["--execute"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
