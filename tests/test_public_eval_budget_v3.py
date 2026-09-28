import copy
import json
import unittest

from scripts import run_public_brief_eval as runner


def parsed_body(text, rationale=""):
    return {
        "interpretations": [{"text": text}],
        "watchlist": [{"rationale": rationale}],
    }


def parsed_policy_body(text="政策说明"):
    value = parsed_body("贸易观察", "后续核对")
    value["policy_explanations"] = [{"topic": "change", "text": text}]
    return value


class PublicEvalBudgetV3Tests(unittest.TestCase):
    def test_v3_counts_reader_fields_not_json_or_hidden_metadata(self):
        result = runner._output_budget(
            '{"interpretations": [{"text": "短"}], "hidden": "' + "x" * 5000 + '"}',
            {"completion_tokens": 100},
            max_tokens=8192,
            budget_protocol="v3",
            body_max_chars=1,
            parsed=parsed_body("短", "好"),
        )
        self.assertEqual(result["body_chars"], 2)
        self.assertFalse(result["within_gate"])
        self.assertEqual(result["reason"], "body_characters_exceeded")
        self.assertEqual(result["body_method"], "unicode_reader_fields")

    def test_v3_character_boundary_and_unicode_are_explicit(self):
        exactly = runner._output_budget(
            "{}", {"completion_tokens": 1}, max_tokens=8192,
            budget_protocol="v3", body_max_chars=2000,
            parsed=parsed_body("🙂" * 1999, "好"),
        )
        over = runner._output_budget(
            "{}", {"completion_tokens": 1}, max_tokens=8192,
            budget_protocol="v3", body_max_chars=2000,
            parsed=parsed_body("🙂" * 2000, "好"),
        )
        self.assertEqual(exactly["body_chars"], 2000)
        self.assertTrue(exactly["within_gate"])
        self.assertEqual(over["body_chars"], 2001)
        self.assertFalse(over["within_gate"])

    def test_v3_missing_or_malformed_usage_is_unknown(self):
        parsed = parsed_body("可以")
        for usage in ({}, {"completion_tokens": True},
                      {"completion_tokens": -1}, {"completion_tokens": "10"}):
            with self.subTest(usage=usage):
                result = runner._output_budget(
                    "{}", usage, max_tokens=8192, budget_protocol="v3",
                    body_max_chars=2000, parsed=parsed,
                )
                self.assertFalse(result["within_gate"])
                self.assertFalse(result["total_usage_known"])
                self.assertEqual(result["reason"], "usage_unknown")
                self.assertIsNone(result["tokens"])
                self.assertEqual(result["method"], "usage_unavailable")

    def test_v3_cost_and_raw_byte_gates_are_separate(self):
        parsed = parsed_body("短")
        over_cost = runner._output_budget(
            "{}", {"completion_tokens": 8193}, max_tokens=8192,
            budget_protocol="v3", body_max_chars=2000, parsed=parsed,
        )
        self.assertFalse(over_cost["cost_gate"])
        self.assertTrue(over_cost["chars_gate"])
        self.assertEqual(over_cost["reason"], "total_output_tokens_exceeded")
        over_bytes = runner._output_budget(
            "x" * 11, {"completion_tokens": 1}, max_tokens=8192,
            max_bytes=10, budget_protocol="v3", body_max_chars=2000,
            parsed=parsed,
        )
        self.assertFalse(over_bytes["bytes_gate"])
        self.assertEqual(over_bytes["reason"], "raw_bytes_exceeded")

    def test_v3_counts_policy_explanations_in_reader_length(self):
        parsed = parsed_policy_body("政" * 3)
        self.assertEqual(runner._public_body_characters(parsed), len("贸易观察") + len("后续核对") + 3)
        result = runner._output_budget(
            "{}", {"completion_tokens": 1}, max_tokens=8192,
            budget_protocol="v3", body_max_chars=5, parsed=parsed,
        )
        self.assertEqual(result["body_chars"], 11)
        self.assertFalse(result["within_gate"])
        self.assertEqual(result["reason"], "body_characters_exceeded")

    def test_v3_freeze_has_versioned_shape_and_v2_compatibility(self):
        matrix = json.loads(runner.DEFAULT_MATRIX.read_text())
        provider = copy.deepcopy(matrix["candidates"][2])
        legacy_package = runner.ROOT / "tmp/public-brief-eval-v1/candidate-service-20260922-v1"
        v2 = runner.build_freeze_spec(provider=provider, package_path=legacy_package,
                                      budget_protocol="v2")
        v3 = runner.build_freeze_spec(provider=provider, package_path=runner.DEFAULT_PACKAGE,
                                      budget_protocol="v3")
        self.assertNotIn("budget_protocol", v2["params"])
        self.assertEqual(v2["params"]["body_max_tokens"], 2000)
        self.assertEqual(v3["params"]["budget_protocol"], "v3")
        self.assertEqual(v3["params"]["body_max_chars"], 2000)
        self.assertNotIn("body_max_tokens", v3["params"])
        self.assertNotIn("evals/public_brief_v1/SCORING_V3.zh-CN.md", v2["scoring_sha256"])
        self.assertIn("evals/public_brief_v1/SCORING_V3.zh-CN.md", v3["scoring_sha256"])
        self.assertEqual(runner.verify_freeze(
            freeze=v3, provider=provider, package_path=runner.DEFAULT_PACKAGE,
            allow_candidate=True), runner.canonical_sha(v3))

    def test_v3_freeze_rejects_missing_or_wrong_budget_fields(self):
        matrix = json.loads(runner.DEFAULT_MATRIX.read_text())
        provider = copy.deepcopy(matrix["candidates"][2])
        freeze = runner.build_freeze_spec(provider=provider, package_path=runner.DEFAULT_PACKAGE,
                                           budget_protocol="v3")
        freeze["params"].pop("body_max_chars")
        with self.assertRaisesRegex(ValueError, "字段"):
            runner.verify_freeze(freeze=freeze, provider=provider,
                                 package_path=runner.DEFAULT_PACKAGE, allow_candidate=True)

    def test_v3_cannot_freeze_only_old_scoring(self):
        provider = json.loads(runner.DEFAULT_MATRIX.read_text())["candidates"][2]
        freeze = runner.build_freeze_spec(provider=provider, package_path=runner.DEFAULT_PACKAGE,
                                          budget_protocol="v3")
        freeze["scoring_sha256"].pop("evals/public_brief_v1/SCORING_V3.zh-CN.md")
        with self.assertRaisesRegex(ValueError, "评分文件"):
            runner.verify_freeze(freeze=freeze, provider=provider,
                                 package_path=runner.DEFAULT_PACKAGE, allow_candidate=True)


if __name__ == "__main__":
    unittest.main()
