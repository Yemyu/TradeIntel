"""Header-free capture of the HTTP payload sent by an adapter.

Message bodies may contain sensitive user data. Omitting authentication
headers is not comprehensive content redaction.

The historical evaluation manifests freeze ``model_adapter.py``.  That file
must not be edited after a run has been recorded, so capture is installed at
the adapter's opener boundary instead.  The boundary sees the final
``urllib.request.Request`` (the bytes that would actually be sent), while it
never records headers such as ``Authorization``.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
from collections.abc import Callable, Mapping
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit

from .agent import ModelResponse


def _json_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _safe_endpoint(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "[REDACTED_ENDPOINT]"
    try:
        parts = urlsplit(value)
    except ValueError:
        return "[REDACTED_ENDPOINT]"
    if parts.username is not None or parts.password is not None:
        return "[REDACTED_ENDPOINT]"
    # Query strings and fragments are deliberately omitted: providers should
    # not receive credentials there, but omitting them makes the capture safe
    # even when a caller accidentally does so.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def sanitize_request_capture(value: object) -> dict[str, object] | None:
    """Return a self-consistent capture, or ``None`` for untrusted metadata."""

    if not isinstance(value, Mapping) or value.get("kind") != "http_payload":
        return None
    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        return None
    try:
        payload_copy = json.loads(json.dumps(payload, ensure_ascii=False))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload_copy, Mapping):
        return None
    expected = _json_digest(payload_copy)
    if value.get("payload_sha256") != expected:
        return None
    timeout = value.get("timeout_seconds")
    if (type(timeout) not in (int, float) or not math.isfinite(float(timeout))
            or float(timeout) <= 0):
        return None
    return {
        "kind": "http_payload",
        "endpoint": _safe_endpoint(value.get("endpoint")),
        "timeout_seconds": float(timeout),
        "payload": payload_copy,
        "payload_sha256": expected,
    }


def capture_http_request(request: Any, timeout_seconds: float) -> dict[str, object] | None:
    """Capture JSON request bytes immediately before an opener sends them."""

    raw = getattr(request, "data", None)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, (bytes, bytearray)):
        return None
    try:
        payload = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return sanitize_request_capture({
        "kind": "http_payload",
        "endpoint": getattr(request, "full_url", None),
        "timeout_seconds": timeout_seconds,
        "payload": payload,
        "payload_sha256": _json_digest(payload),
    })


class _CaptureSink:
    def __init__(self, opener: Callable[..., Any]) -> None:
        self.original = opener
        self.latest: dict[str, object] | None = None

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        timeout = kwargs.get("timeout")
        if timeout is None and args:
            timeout = args[0]
        self.latest = capture_http_request(request, timeout)
        return self.original(request, *args, **kwargs)


@contextmanager
def capture_model_opener(model: Any) -> Iterator[_CaptureSink | None]:
    """Temporarily observe a compatible model's private opener boundary."""

    original = getattr(model, "_opener", None)
    if not callable(original):
        yield None
        return
    sink = _CaptureSink(original)
    setattr(model, "_opener", sink)
    try:
        yield sink
    finally:
        setattr(model, "_opener", original)


def _attach(response: Any, capture: Mapping[str, object] | None) -> Any:
    if isinstance(response, ModelResponse):
        metadata = dict(response.metadata)
        metadata.pop("request_capture", None)
        if capture is not None:
            metadata["request_capture"] = deepcopy_capture(capture)
        return ModelResponse(text=response.text, tool_calls=response.tool_calls,
                             metadata=metadata)
    if isinstance(response, Mapping):
        result = dict(response)
        metadata = dict(result.get("metadata", {})) if isinstance(result.get("metadata"), Mapping) else {}
        metadata.pop("request_capture", None)
        if capture is not None:
            metadata["request_capture"] = deepcopy_capture(capture)
        result["metadata"] = metadata
        return result
    return response


def deepcopy_capture(value: Mapping[str, object]) -> dict[str, object]:
    """Copy JSON-shaped capture data without importing a general serializer."""

    return json.loads(json.dumps(value, ensure_ascii=False))


def complete_with_capture(model: Any, *, messages: Any, tools: Any) -> Any:
    """Call a model and attach the observed payload when it exposes an opener."""

    with capture_model_opener(model) as sink:
        response = model.complete(messages=messages, tools=tools)
    return _attach(response, sink.latest if sink is not None else None)


__all__ = [
    "capture_http_request",
    "capture_model_opener",
    "complete_with_capture",
    "sanitize_request_capture",
]
