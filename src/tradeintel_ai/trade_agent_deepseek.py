"""Thinking-mode tool-call bridge for the current trade assistant only.

The historical generic adapter is part of frozen evaluations, so this bridge
adds DeepSeek's reasoning replay without changing that adapter or its results.
Reasoning stays in the current model call and is never placed in metadata.
"""

from __future__ import annotations

import io
import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.request import urlopen

from .agent import ModelResponse
from .model_adapter import ModelAdapterError, OpenAICompatibleConfig, OpenAICompatibleModel


@dataclass(frozen=True)
class ThinkingToolResponse(ModelResponse):
    """A transient model result; never persist ``reasoning_content``."""

    reasoning_content: str | None = field(default=None, repr=False)
    reasoning_present: bool = False
    wire_content: str | None = field(default=None, repr=False)
    wire_content_present: bool = False


class DeepSeekThinkingToolModel(OpenAICompatibleModel):
    """Replay each assistant tool turn exactly as DeepSeek thinking mode needs."""

    def __init__(self, config: OpenAICompatibleConfig, *, system_prompt: str = "",
                 opener=urlopen, request_params: Mapping[str, object] | None = None) -> None:
        super().__init__(config, system_prompt=system_prompt, opener=opener,
                         request_params=request_params)
        if self.request_params.get("thinking") != {"type": "enabled"}:
            raise ValueError("DeepSeek 推理工具适配器要求 thinking=enabled")
        self._capture_lock = threading.Lock()

    def _payload(self, *, messages: Sequence[Mapping[str, object]],
                 tools: Sequence[Mapping[str, object]]) -> dict[str, object]:
        payload = super()._payload(messages=messages, tools=tools)
        # DeepSeek's official thinking/tool example omits tool_choice. Its
        # separate integration guide warns that sending this optional field
        # may be rejected; with tools present the default is automatic.
        payload.pop("tool_choice", None)
        wire_messages = payload["messages"]
        offset = len(wire_messages) - len(messages)
        for source, wire in zip(messages, wire_messages[offset:]):
            if source.get("role") == "assistant" and "tool_calls" in source:
                if "reasoning_content" not in source:
                    raise ModelAdapterError("推理工具消息缺少 reasoning_content；停止继续调用")
                reasoning = source["reasoning_content"]
                if reasoning is not None and not isinstance(reasoning, str):
                    raise ModelAdapterError("推理工具消息的 reasoning_content 类型无效")
                wire["reasoning_content"] = reasoning
        return payload

    def complete(self, *, messages: Sequence[Mapping[str, object]],
                 tools: Sequence[Mapping[str, object]]) -> ModelResponse:
        # Reuse the frozen transport, timeout, HTTP-error sanitization and
        # tool parser. Observe only the provider response body in memory so
        # the private reasoning field can be carried to the next tool turn.
        with self._capture_lock:
            original_opener = self._opener
            response_bodies: list[bytes] = []

            def capture(request: Any, *, timeout: float) -> io.BytesIO:
                with original_opener(request, timeout=timeout) as response:
                    raw = response.read()
                response_bodies.append(raw)
                return io.BytesIO(raw)

            self._opener = capture
            try:
                parsed = super().complete(messages=messages, tools=tools)
            finally:
                self._opener = original_opener
            if not parsed.tool_calls:
                return parsed
            if len(response_bodies) != 1:
                raise ModelAdapterError("推理工具响应无法验证；停止继续调用")
            try:
                body = json.loads(response_bodies[0].decode("utf-8"))
                message = body["choices"][0]["message"]
                reasoning = message["reasoning_content"]
            except (KeyError, IndexError, TypeError, UnicodeError, ValueError) as exc:
                raise ModelAdapterError("推理工具响应缺少 reasoning_content；停止继续调用") from exc
            if reasoning is not None and not isinstance(reasoning, str):
                raise ModelAdapterError("推理工具响应的 reasoning_content 类型无效")
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise ModelAdapterError("推理工具响应的 content 类型无效")
            return ThinkingToolResponse(text=parsed.text, tool_calls=parsed.tool_calls,
                                        metadata=parsed.metadata,
                                        reasoning_content=reasoning,
                                        reasoning_present=True,
                                        wire_content=content,
                                        wire_content_present="content" in message)


def create_trade_agent_model(config: OpenAICompatibleConfig,
                             request_params: Mapping[str, object], *, opener=urlopen) -> OpenAICompatibleModel:
    """Choose the private replay bridge only for DeepSeek thinking mode."""
    model_type = (DeepSeekThinkingToolModel
                  if config.base_url.rstrip("/") == "https://api.deepseek.com"
                  and request_params.get("thinking") == {"type": "enabled"}
                  else OpenAICompatibleModel)
    return model_type(config, system_prompt="", request_params=request_params, opener=opener)
