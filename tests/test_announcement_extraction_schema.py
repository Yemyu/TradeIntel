"""Offline tests for the isolated structured announcement transport."""
from pathlib import Path
import json
import unittest

from tradeintel_ai.announcement_extraction_pilot import (
    D2_SOURCE_SHA256,
    D2_SOURCE_URL,
    adapt_suggestion,
    extract_d2_text,
    make_disabled_store,
)
from tradeintel_ai.announcement_extraction_schema import (
    FUNCTION_NAME,
    SCHEMA_VERSION,
    function_definition,
    normalise_transport_answer,
    parse_tool_response,
    prepare_schema_request,
    schema_hash,
    tool_choice,
)
from tradeintel_ai.policy_candidates import REQUIRED_FIELDS


ROOT = Path(__file__).resolve().parents[1]


def _transport_unknown(version: str) -> dict:
    return {
        "doc_version": version,
        "fields": [
            {"field": name, "status": "unknown",
             "value": {"present": False, "data": ""},
             "reason": "正文不足以确定", "evidence": []}
            for name in REQUIRED_FIELDS
        ],
    }


class AnnouncementExtractionSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (ROOT / "evals/policy_extraction_v1/sources/csms-65794272.html").read_bytes()
        text, _ = extract_d2_text(raw)
        cls.store = make_disabled_store("d2_copper_2025", "csms65794272", text,
                                        url=D2_SOURCE_URL, source_sha256=D2_SOURCE_SHA256)
        cls.version = cls.store["documents"][0]["doc_version"]

    def test_definition_is_stable_and_strict_compatible_shape(self):
        definition = function_definition(strict=True)
        self.assertEqual(definition["type"], "function")
        self.assertEqual(definition["function"]["name"], FUNCTION_NAME)
        self.assertTrue(definition["function"]["strict"])
        params = definition["function"]["parameters"]
        self.assertEqual(set(params["properties"]), {"doc_version", "fields"})
        self.assertEqual(params["required"], ["doc_version", "fields"])
        item = params["properties"]["fields"]["items"]
        self.assertEqual(set(item["properties"]),
                         {"field", "status", "value", "reason", "evidence"})
        self.assertEqual(schema_hash(definition), schema_hash(function_definition(strict=True)))
        self.assertEqual(tool_choice(), {"type": "function",
                                         "function": {"name": FUNCTION_NAME}})

    def test_transport_unknown_normalises_to_existing_review_contract(self):
        answer = normalise_transport_answer(_transport_unknown(self.version))
        self.assertEqual(answer["doc_version"], self.version)
        self.assertEqual(len(answer["fields"]), 13)
        self.assertTrue(all(item["value"] is None and item["reason"] for item in answer["fields"]))
        draft = adapt_suggestion(answer, self.store, self.version)
        self.assertEqual(draft["status"], "review_only")

    def test_valid_single_tool_call_is_parsed_without_semantic_claim(self):
        args = _transport_unknown(self.version)
        raw = json.dumps({
            "id": "fixture-response",
            "model": "deepseek-flash",
            "choices": [{"finish_reason": "tool_calls", "message": {
                "content": "",
                "tool_calls": [{"id": "call_1", "type": "function",
                                 "function": {"name": FUNCTION_NAME,
                                               "arguments": json.dumps(args, ensure_ascii=False)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }, ensure_ascii=False)
        parsed = parse_tool_response(raw)
        self.assertEqual(parsed["schema_version"], SCHEMA_VERSION)
        self.assertEqual(parsed["arguments"], args)
        self.assertEqual(parsed["finish_reason"], "tool_calls")

    def test_response_contract_rejects_mixed_text_wrong_function_multiple_calls_and_duplicates(self):
        args = json.dumps(_transport_unknown(self.version), ensure_ascii=False)

        def response(*, calls=None, content="", name=FUNCTION_NAME):
            if calls is None:
                calls = [{"id": "call_1", "type": "function",
                          "function": {"name": name, "arguments": args}}]
            return json.dumps({"choices": [{"finish_reason": "tool_calls",
                                               "message": {"content": content,
                                                           "tool_calls": calls}}]})

        with self.assertRaisesRegex(ValueError, "mixed text"):
            parse_tool_response(response(content="unexpected"))
        with self.assertRaisesRegex(ValueError, "unexpected function"):
            parse_tool_response(response(name="other_function"))
        with self.assertRaisesRegex(ValueError, "exactly one tool call"):
            parse_tool_response(response(calls=[
                {"id": "a", "type": "function", "function": {"name": FUNCTION_NAME, "arguments": args}},
                {"id": "b", "type": "function", "function": {"name": FUNCTION_NAME, "arguments": args}},
            ]))
        duplicate = '{"doc_version":"x","doc_version":"y","fields":[]}'
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_tool_response(json.dumps({"choices": [{"finish_reason": "tool_calls",
                "message": {"content": "", "tool_calls": [{"type": "function",
                    "function": {"name": FUNCTION_NAME, "arguments": duplicate}}]}}]}))

    def test_prepare_uses_independent_budget_and_does_not_change_old_package(self):
        prepared = prepare_schema_request(self.store, self.version, model="deepseek-flash")
        self.assertEqual(prepared["schema_version"], SCHEMA_VERSION)
        self.assertLessEqual(prepared["body_bytes"], prepared["body_limit"])
        self.assertLess(prepared["input_request_bytes"], 24_000)
        self.assertEqual(prepared["body"]["parallel_tool_calls"], False)
        self.assertEqual(prepared["body"]["thinking"], {"type": "disabled"})
        self.assertEqual(prepared["body"]["tools"][0]["function"]["name"], FUNCTION_NAME)
        self.assertLessEqual(prepared["input_token_estimate"]["tokens"],
                             prepared["input_token_limit"])


if __name__ == "__main__":
    unittest.main()
