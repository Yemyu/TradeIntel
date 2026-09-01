"""A small, provider-neutral HTTP adapter for OpenAI-compatible tool calling.

The project deliberately keeps the model boundary separate from the evidence
tools.  This module translates the provider-neutral ``ChatModel`` messages and
schemas into the widely used ``/chat/completions`` JSON shape, and translates a
response back into :class:`~tradeintel_ai.agent.ModelResponse`.

It uses only the Python standard library.  This keeps the core project easy to
run offline and makes the model provider a replaceable configuration choice.
No API key is ever included in an exception message or request log.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .agent import ModelResponse, ModelToolCall


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_TEMPERATURE = 0.0

DEFAULT_SYSTEM_PROMPT = """你是 TradeShock AI 的证据约束分析助手。
你只能使用系统提供的已登记只读工具查询事实和计算；不要编造数字、来源、工具结果或 SQL。
工具返回的 causal_allowed、causal_language_allowed 和 limitations 是硬约束。
如果因果状态被阻断，只能描述观察到的变化，并明确说不能据此证明关税导致变化。
最终回答要引用工具结果中的来源和限制；如果证据不足，直接说明不足，不要用常识补齐。
"""


class ModelAdapterError(RuntimeError):
    """A safe, user-facing model transport or response-contract error."""


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    """Configuration for an OpenAI-compatible chat-completions endpoint."""

    base_url: str
    model: str
    api_key: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    temperature: float = DEFAULT_TEMPERATURE

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("base_url 不能为空")
        if not self.model.strip():
            raise ValueError("model 不能为空")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature 必须位于 0 到 2 之间")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "OpenAICompatibleConfig":
        """Read project-scoped settings without printing or persisting secrets.

        ``TRADEINTEL_MODEL_API_KEY`` is optional so a local endpoint can run
        without authentication.  Remote services commonly require it and will
        return a sanitized HTTP error if it is missing.
        """

        values = env if env is not None else os.environ
        base_url = values.get("TRADEINTEL_MODEL_BASE_URL", DEFAULT_BASE_URL).strip()
        model = values.get("TRADEINTEL_MODEL_NAME", "").strip()
        api_key = values.get("TRADEINTEL_MODEL_API_KEY", "").strip()
        try:
            timeout = float(values.get("TRADEINTEL_MODEL_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
        except (TypeError, ValueError) as exc:
            raise ModelAdapterError("TRADEINTEL_MODEL_TIMEOUT 必须是数字") from exc
        try:
            temperature = float(values.get("TRADEINTEL_MODEL_TEMPERATURE", DEFAULT_TEMPERATURE))
        except (TypeError, ValueError) as exc:
            raise ModelAdapterError("TRADEINTEL_MODEL_TEMPERATURE 必须是数字") from exc
        if not model:
            raise ModelAdapterError(
                "缺少 TRADEINTEL_MODEL_NAME；先指定模型名称，才能启动真实模型模式"
            )
        try:
            return cls(
                base_url=base_url,
                model=model,
                api_key=api_key,
                timeout_seconds=timeout,
                temperature=temperature,
            )
        except ValueError as exc:
            raise ModelAdapterError(str(exc)) from exc


def _endpoint(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return f"{cleaned}/chat/completions"


def _string_content(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _tool_arguments(value: object) -> str:
    if isinstance(value, str):
        return value or "{}"
    return json.dumps(value if isinstance(value, Mapping) else {}, ensure_ascii=False)


def _normalise_messages(messages: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Translate the internal message shape into chat-completions messages."""

    result: list[dict[str, object]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            raise ModelAdapterError("模型消息必须是对象")
        role = str(message.get("role", ""))
        if role not in {"system", "user", "assistant", "tool"}:
            raise ModelAdapterError(f"不支持的模型消息角色：{role!r}")
        if role == "assistant" and "tool_calls" in message:
            raw_calls = message.get("tool_calls")
            if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes)):
                raise ModelAdapterError("assistant.tool_calls 必须是列表")
            calls: list[dict[str, object]] = []
            for index, raw_call in enumerate(raw_calls):
                if not isinstance(raw_call, Mapping):
                    raise ModelAdapterError("每个 assistant 工具调用必须是对象")
                name = str(raw_call.get("name", ""))
                if not name:
                    raise ModelAdapterError("assistant 工具调用缺少 name")
                calls.append(
                    {
                        "id": str(raw_call.get("call_id", f"call_{index + 1}")),
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": _tool_arguments(raw_call.get("arguments", {})),
                        },
                    }
                )
            result.append(
                {
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": calls,
                }
            )
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id", ""))
            if not call_id:
                raise ModelAdapterError("tool 消息缺少 tool_call_id")
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": _string_content(message.get("content", "")),
                }
            )
            continue
        result.append({"role": role, "content": _string_content(message.get("content", ""))})
    return result


def _normalise_tools(tools: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Nest provider-neutral function schemas in the chat-completions shape."""

    result: list[dict[str, object]] = []
    for tool in tools:
        if not isinstance(tool, Mapping) or tool.get("type") != "function":
            raise ModelAdapterError("每个模型工具 schema 都必须是 type=function 对象")
        name = str(tool.get("name", ""))
        if not name:
            raise ModelAdapterError("模型工具 schema 缺少 name")
        function: dict[str, object] = {"name": name}
        for field in ("description", "parameters"):
            if field in tool:
                function[field] = tool[field]
        result.append({"type": "function", "function": function})
    return result


def _parse_arguments(value: object) -> dict[str, object]:
    if value is None or value == "":
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        raise ModelAdapterError("模型工具参数不是 JSON 对象")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ModelAdapterError("模型工具参数不是合法 JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ModelAdapterError("模型工具参数必须是 JSON 对象")
    return dict(parsed)


def _parse_response(payload: Mapping[str, object]) -> ModelResponse:
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise ModelAdapterError("模型响应缺少 choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ModelAdapterError("模型响应的 choice 不是对象")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ModelAdapterError("模型响应缺少 message")

    raw_calls = message.get("tool_calls", [])
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes)):
        raise ModelAdapterError("模型响应的 tool_calls 不是列表")
    calls: list[ModelToolCall] = []
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, Mapping):
            raise ModelAdapterError("模型响应的工具调用不是对象")
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            raise ModelAdapterError("模型响应的工具调用缺少 function")
        name = str(function.get("name", ""))
        if not name:
            raise ModelAdapterError("模型响应的工具调用缺少 name")
        calls.append(
            ModelToolCall(
                call_id=str(raw_call.get("id", f"call_{index + 1}")),
                name=name,
                arguments=_parse_arguments(function.get("arguments", "{}")),
            )
        )
    return ModelResponse(text=_string_content(message.get("content", "")), tool_calls=tuple(calls))


class OpenAICompatibleModel:
    """Implement the project's minimal ``ChatModel`` protocol over HTTP."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.config = config
        self.system_prompt = system_prompt.strip()
        self._opener = opener

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> "OpenAICompatibleModel":
        return cls(OpenAICompatibleConfig.from_env(env), **kwargs)

    def _payload(
        self,
        *,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        normalised_messages = _normalise_messages(messages)
        if self.system_prompt and not any(item.get("role") == "system" for item in normalised_messages):
            normalised_messages.insert(0, {"role": "system", "content": self.system_prompt})
        return {
            "model": self.config.model,
            "messages": normalised_messages,
            "tools": _normalise_tools(tools),
            "tool_choice": "auto",
            "temperature": self.config.temperature,
        }

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> ModelResponse:
        payload = self._payload(messages=messages, tools=tools)
        request = Request(
            _endpoint(self.config.base_url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}),
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            # Never include request headers or payload: they may contain secrets
            # or user data.  The status code is enough for a useful diagnosis.
            raise ModelAdapterError(f"模型服务返回 HTTP {exc.code}") from exc
        except URLError as exc:
            raise ModelAdapterError(f"无法连接模型服务：{exc.reason}") from exc
        except TimeoutError as exc:
            raise ModelAdapterError("模型服务请求超时") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelAdapterError("模型服务返回的不是合法 JSON") from exc
        if not isinstance(decoded, Mapping):
            raise ModelAdapterError("模型服务返回的 JSON 不是对象")
        return _parse_response(decoded)


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_SYSTEM_PROMPT",
    "ModelAdapterError",
    "OpenAICompatibleConfig",
    "OpenAICompatibleModel",
]
