import json
import unittest
from io import BytesIO
from urllib.error import HTTPError

from src.tradeintel_ai.agent import ModelResponse
from src.tradeintel_ai.model_adapter import (
    ModelAdapterError,
    OpenAICompatibleConfig,
    OpenAICompatibleModel,
    _normalise_messages,
    _normalise_tools,
)
from src.tradeintel_ai.request_capture import capture_http_request, complete_with_capture
from src.tradeintel_ai.research_models import ResearchPolicyModel


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


class TradeIntelAiModelAdapterTests(unittest.TestCase):
    def setUp(self):
        self.config = OpenAICompatibleConfig(
            base_url="http://localhost:8000/v1",
            model="test-model",
            api_key="test-secret",
        )
        self.tools = [
            {
                "type": "function",
                "name": "get_policy_event",
                "description": "Read a policy event.",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

    def test_provider_neutral_messages_and_tools_are_translated(self):
        messages = [
            {"role": "user", "content": "查政策"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "call_id": "call_1",
                        "name": "get_policy_event",
                        "arguments": {"policy_id": "us_301_list1_2018"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "get_policy_event",
                "content": {"status": "ok"},
            },
        ]
        translated_messages = _normalise_messages(messages)
        self.assertEqual(translated_messages[0], {"role": "user", "content": "查政策"})
        self.assertEqual(
            translated_messages[1]["tool_calls"][0]["function"],
            {
                "name": "get_policy_event",
                "arguments": '{"policy_id": "us_301_list1_2018"}',
            },
        )
        self.assertEqual(json.loads(translated_messages[2]["content"]), {"status": "ok"})

    def test_provider_tool_schema_has_function_nesting(self):
        self.assertEqual(
            _normalise_tools(self.tools),
            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_policy_event",
                        "description": "Read a policy event.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

    def test_complete_parses_text_and_tool_calls_and_inserts_system_prompt(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["request_capture"] = capture_http_request(request, timeout)
            return FakeResponse(
                {
                    "id": "chatcmpl-test",
                    "model": "test-model",
                    "created": 123,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_7",
                                        "type": "function",
                                        "function": {
                                            "name": "get_policy_event",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )

        model = OpenAICompatibleModel(self.config, opener=opener)
        response = model.complete(messages=[{"role": "user", "content": "查政策"}], tools=self.tools)
        self.assertIsInstance(response, ModelResponse)
        self.assertEqual(response.text, "")
        self.assertEqual(response.tool_calls[0].name, "get_policy_event")
        self.assertEqual(response.tool_calls[0].arguments, {})
        self.assertEqual(response.metadata["model"], "test-model")
        self.assertEqual(response.metadata["requested_model"], "test-model")
        self.assertEqual(response.metadata["usage"]["total_tokens"], 14)
        capture = captured["request_capture"]
        self.assertEqual(capture["kind"], "http_payload")
        self.assertEqual(capture["timeout_seconds"], 60.0)
        self.assertEqual(capture["payload"]["model"], "test-model")
        self.assertNotIn("Authorization", json.dumps(capture))
        self.assertNotIn("test-secret", json.dumps(capture))
        self.assertEqual(capture["payload"], captured["payload"])
        self.assertEqual(captured["url"], "http://localhost:8000/v1/chat/completions")
        self.assertEqual(captured["timeout"], 60.0)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-secret")
        self.assertEqual(captured["payload"]["model"], "test-model")
        self.assertEqual(captured["payload"]["messages"][0]["role"], "system")
        self.assertEqual(captured["payload"]["tools"][0]["function"]["name"], "get_policy_event")

    def test_complete_with_capture_attaches_the_final_payload_without_headers(self):
        def opener(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(timeout, 60.0)
            self.assertEqual(payload["model"], "test-model")
            self.assertEqual(payload["max_tokens"], 768)
            self.assertEqual(payload["thinking"], {"type": "disabled"})
            return FakeResponse({
                "model": "test-model",
                "choices": [{"finish_reason": "stop",
                             "message": {"content": '{"claims": []}'}}],
            })

        model = ResearchPolicyModel(self.config, opener=opener)
        response = complete_with_capture(
            model, messages=[{"role": "user", "content": "查政策"}], tools=[]
        )
        capture = response.metadata["request_capture"]
        self.assertEqual(capture["kind"], "http_payload")
        self.assertEqual(capture["payload"]["model"], "test-model")
        self.assertEqual(capture["payload"]["max_tokens"], 768)
        self.assertNotIn("Authorization", json.dumps(capture))
        self.assertNotIn("test-secret", json.dumps(capture))

    def test_from_env_requires_model_name_but_does_not_print_key(self):
        with self.assertRaisesRegex(ModelAdapterError, "TRADEINTEL_MODEL_NAME"):
            OpenAICompatibleConfig.from_env({"TRADEINTEL_MODEL_API_KEY": "secret"})

    def test_no_tool_control_omits_tool_fields_entirely(self):
        payload = OpenAICompatibleModel(self.config)._payload(messages=[{"role": "user", "content": "查政策"}], tools=[])
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)

    def test_invalid_tool_arguments_are_rejected(self):
        def opener(request, timeout):
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_bad",
                                        "function": {
                                            "name": "get_policy_event",
                                            "arguments": "not-json",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )

        with self.assertRaisesRegex(ModelAdapterError, "合法 JSON"):
            OpenAICompatibleModel(self.config, opener=opener).complete(
                messages=[{"role": "user", "content": "查政策"}], tools=self.tools
            )

    def test_http_error_does_not_leak_api_key(self):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 401, "unauthorized", {}, BytesIO(b"secret"))

        with self.assertRaises(ModelAdapterError) as context:
            OpenAICompatibleModel(self.config, opener=opener).complete(
                messages=[{"role": "user", "content": "查政策"}], tools=self.tools
            )
        self.assertNotIn("test-secret", str(context.exception))
        self.assertEqual(str(context.exception), "模型服务返回 HTTP 401")


if __name__ == "__main__":
    unittest.main()
