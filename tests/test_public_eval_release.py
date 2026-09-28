"""Offline checks for the bounded four-question release (no credentials)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_public_brief_eval as runner
from src.tradeintel_ai.public_eval_ledger import claim, make_base_key, validate_review_checks


class PublicEvalReleaseTests(unittest.TestCase):
    def test_thinking_usage_does_not_count_as_visible_body(self):
        result = runner._output_budget("简短解释", {"completion_tokens": 7000},
                                       max_tokens=8192, thinking_enabled=True)
        self.assertTrue(result["within_gate"])
        self.assertEqual(result["body_method"], "estimate")
        self.assertFalse(runner._output_budget("短回答", {"completion_tokens": 9000},
                                             max_tokens=8192, thinking_enabled=True)["within_gate"])
        self.assertFalse(runner._output_budget("字" * 5000, {"completion_tokens": 7000},
                                             max_tokens=8192, thinking_enabled=True)["within_gate"])

    def test_frozen_total_budget_cannot_differ_from_provider(self):
        provider = runner.preflight(provider_id="glm-46v")["provider"]
        freeze = runner.build_freeze_spec(provider=provider, package_path=runner.DEFAULT_PACKAGE)
        freeze["params"]["max_tokens"] = 2000
        with self.assertRaisesRegex(ValueError, "预算或推理"):
            runner.verify_freeze(freeze=freeze, provider=provider,
                                 package_path=runner.DEFAULT_PACKAGE, allow_candidate=True)

    def test_changes_between_preflight_and_send_never_reach_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "package"
            shutil.copytree(runner.DEFAULT_PACKAGE, package)
            provider = runner.preflight(provider_id="glm-46v", package_path=package)["provider"]
            freeze = runner.build_freeze_spec(provider=provider, package_path=package)
            original = runner.verify_freeze
            def change_after_verify(**kwargs):
                digest = original(**kwargs)
                (package / "requests/q1/messages.json").write_text("[]", encoding="utf-8")
                return digest
            with patch.object(runner, "verify_freeze", side_effect=change_after_verify), \
                    unittest.mock.patch.object(runner, "_response_parts") as response:
                with self.assertRaisesRegex(ValueError, "发送前材料"):
                    runner.run_injected(provider=provider, package_path=package,
                                        output=root / "out", question_id="q1", freeze=freeze,
                                        provider_call=lambda **_: self.fail("must not call"), ledger_root=root)
                response.assert_not_called()

    def test_claim_enforces_question_order_inside_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "先完成 q1"):
                claim(Path(temp), base_key=make_base_key("a" * 64, "b" * 64, "q2"),
                      metadata={"question_id": "q2"})

    def test_four_review_items_and_verdict_must_agree(self):
        with self.assertRaises(ValueError):
            validate_review_checks(None, "pass")
        checks = {name: {"passed": True, "reason": "测试理由"}
                  for name in ("structure", "facts", "relevance", "usefulness")}
        validate_review_checks(checks, "pass")
        checks["facts"]["passed"] = False
        with self.assertRaises(ValueError):
            validate_review_checks(checks, "pass")
        validate_review_checks(checks, "major_error")

    def test_actual_payload_contains_frozen_deepseek_effort(self):
        provider = runner.preflight(provider_id="deepseek-flash")["provider"]
        model = runner._PublicEvalModel(
            runner.OpenAICompatibleConfig(provider["base_url"], provider["model_id"], "test-only"),
            request_params=provider["request_params"])
        payload = model._payload(messages=[{"role": "user", "content": "test"}], tools=[])
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["max_tokens"], 8192)


if __name__ == "__main__":
    unittest.main()
