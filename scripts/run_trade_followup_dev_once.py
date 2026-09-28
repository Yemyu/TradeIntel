"""One bounded DeepSeek development call for the report-follow-up canary.

Default operation is offline preflight. A real request requires the explicit
--live --authorize-one-call pair and is reserved before contacting the provider.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tradeintel_ai.local_provider_config import (PRODUCT_CONFIG_PATH, load_product_config,
    product_config_identity, product_status, product_request_params)
from tradeintel_ai.model_adapter import (ModelAdapterError, OpenAICompatibleModel,
    safe_error_details)
from tradeintel_ai.trade_explanation import report_sha256
from tradeintel_ai.trade_report_followup import (MAX_INPUT_BYTES, MAX_RAW_BYTES,
    build_catalog, catalog_sha256, messages, parse)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tmp/trade-followup-dev-20260925-b"
LOCAL = ROOT / ".local/trade-followup-dev"
MODEL = "deepseek-flash"
PARAMS = {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "max_tokens": 4096}
DEADLINE_SECONDS = 90
SCHEMA = "trade-followup-dev-call-v1"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_metadata(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {"response_id": None, "response_model": None, "usage": None,
                "finish_reason": None}
    response_id = metadata.get("response_id")
    if not isinstance(response_id, str) or len(response_id) > 120:
        response_id = None
    model = metadata.get("model")
    usage = metadata.get("usage")
    if not isinstance(model, str) or len(model) > 120:
        model = None
    if not isinstance(usage, dict) or len(_json_bytes(usage)) > 10_000:
        usage = None
    reason = metadata.get("finish_reason")
    return {"response_id": response_id, "response_model": model, "usage": usage,
            "finish_reason": reason if isinstance(reason, str) else None}


def _secure_local() -> None:
    for path in (ROOT / ".local", LOCAL):
        if path.is_symlink():
            raise ValueError("本地试验目录是符号链接，拒绝使用")
        path.mkdir(mode=0o700, exist_ok=True)
        if not path.is_dir():
            raise ValueError("本地试验路径无效")
        os.chmod(path, 0o700)


@contextmanager
def _lock():
    _secure_local()
    lock_path = LOCAL / "model.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("模型试验锁文件无效")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic(path: Path, value: dict[str, Any]) -> None:
    _secure_local()
    fd, temporary = tempfile.mkstemp(prefix=".followup-", dir=LOCAL)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(_json_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_state() -> dict[str, Any] | None:
    path = LOCAL / "attempt.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("试验记录无效，拒绝覆盖")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SCHEMA:
        raise ValueError("试验记录版本不匹配，拒绝覆盖")
    return value


def _package() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]], dict[str, Any]]:
    if PACKAGE.is_symlink() or not PACKAGE.is_dir():
        raise ValueError("找不到离线开发包")
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("kind") != "offline-development-canary" or manifest.get("provider_calls") != 0:
        raise ValueError("开发包清单类型不符")
    if set(manifest.get("files", {})) != {"report.json", "catalog.json",
                                          "messages.json", "fake_answer.json"}:
        raise ValueError("开发包清单缺少必需文件")
    for name, expected in manifest.get("files", {}).items():
        path = PACKAGE / name
        if path.is_symlink() or not path.is_file() or _sha(path.read_bytes()) != expected:
            raise ValueError(f"开发包文件缺失或变更：{name}")
    report = json.loads((PACKAGE / "report.json").read_text(encoding="utf-8"))
    catalog = json.loads((PACKAGE / "catalog.json").read_text(encoding="utf-8"))
    prompt = json.loads((PACKAGE / "messages.json").read_text(encoding="utf-8"))
    code_path = ROOT / "src/tradeintel_ai/trade_report_followup.py"
    if _sha(code_path.read_bytes()) != manifest.get("code_sha256"):
        raise ValueError("开发包对应的追问代码已变化，需重新审阅包")
    digest = catalog_sha256(build_catalog(report))
    if (report_sha256(report) != manifest.get("report_sha256") or
            digest != manifest.get("catalog_sha256") or catalog_sha256(catalog) != digest or
            catalog != build_catalog(report) or
            len(_json_bytes(prompt)) > MAX_INPUT_BYTES):
        raise ValueError("报告、目录或模型消息与清单不一致")
    if messages(report, manifest["question"], catalog, digest) != prompt:
        raise ValueError("实际模型消息与已审阅开发包不一致")
    return manifest, report, prompt, catalog


def _config() -> tuple[Any, str]:
    if not PRODUCT_CONFIG_PATH.is_file() or PRODUCT_CONFIG_PATH.is_symlink():
        raise ValueError("没有安全保存的产品模型配置")
    config = load_product_config()
    status = product_status()
    actual_params = {**product_request_params(), "max_tokens": PARAMS["max_tokens"]}
    if (status["provider"] != "deepseek" or config.model != MODEL or
            config.base_url.rstrip("/") != "https://api.deepseek.com" or
            not config.api_key or config.temperature != 0 or
            status["reasoning"] not in {"default", "high"} or actual_params != PARAMS):
        raise ValueError("本机模型配置不是 DeepSeek Flash/high/2048 固定参数；不发送请求")
    return replace(config, timeout_seconds=min(config.timeout_seconds, DEADLINE_SECONDS)), product_config_identity()


def check() -> dict[str, Any]:
    manifest, _report, prompt, _catalog = _package()
    config, _identity = _config()
    current = _read_state()
    return {"status": "ready" if current is None else current.get("status"),
            "provider": "deepseek", "requested_model": config.model,
            "reasoning_effort": "high", "max_tokens": PARAMS["max_tokens"],
            "deadline_seconds": DEADLINE_SECONDS, "report_sha256": manifest["report_sha256"],
            "request_bytes": len(_json_bytes(prompt)), "api_calls_this_check": 0,
            "response_model_can_confirm_snapshot": False}


def _network_preflight(base_url: str) -> None:
    """Reach the configured host without a key or model request before a slot is reserved."""
    request = Request(base_url, method="HEAD")
    try:
        with urlopen(request, timeout=8):
            return
    except HTTPError as exc:
        # The API root requires credentials even for HEAD. Its 401 proves the
        # host is reachable; it is not a paid model request.
        if exc.code == 401:
            return
        raise ValueError(f"模型服务连通预检返回 HTTP {exc.code}；未预留调用名额") from exc
    except URLError as exc:
        category = safe_error_details(exc).get("category", "network_error")
        raise ValueError(f"模型服务连通预检失败（{category}）；未预留调用名额") from exc


def _save_raw(raw: str) -> str:
    contents = raw.encode("utf-8")
    if len(contents) > 1_000_000:
        raise ValueError("模型原答超过安全存储上限")
    path = LOCAL / "answer.raw.txt"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())
    return _sha(contents)


def _update(changes: dict[str, Any]) -> dict[str, Any]:
    with _lock():
        path = LOCAL / "attempt.json"
        state = _read_state()
        if state is None or state.get("status") != "provider_call_started":
            raise ValueError("调用账本状态改变，拒绝覆盖")
        state.update(changes)
        _atomic(path, state)
        return state


class DeadlineExceeded(TimeoutError):
    pass


@contextmanager
def _deadline():
    if not hasattr(signal, "setitimer"):
        raise ValueError("当前系统不能保证90秒总时限")
    prior = signal.getsignal(signal.SIGALRM)
    if prior not in (signal.SIG_DFL, signal.SIG_IGN):
        raise ValueError("当前进程已有计时器，不能安全开始调用")
    def expired(_signum: int, _frame: object) -> None:
        raise DeadlineExceeded("整体请求超过90秒，调用结果未知")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, DEADLINE_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prior)


def run_once() -> dict[str, Any]:
    manifest, report, prompt, catalog = _package()
    config, config_identity = _config()
    if _read_state() is not None or (LOCAL / "answer.raw.txt").exists():
        raise ValueError("本开发题已登记尝试；不允许自动重试")
    _network_preflight(config.base_url)
    started = {"schema_version": SCHEMA, "status": "provider_call_started",
               "started_at": _now(), "provider": "deepseek", "requested_model": MODEL,
               "reasoning_effort": "high", "temperature": 0,
              "max_tokens": PARAMS["max_tokens"], "deadline_seconds": DEADLINE_SECONDS,
               "api_calls_reserved": 1, "report_sha256": manifest["report_sha256"],
               "followup_question_sha256": manifest["followup_question_sha256"],
               "catalog_sha256": manifest["catalog_sha256"],
               "request_sha256": _sha(_json_bytes(prompt)),
               "package_manifest_sha256": _sha((PACKAGE / "manifest.json").read_bytes()),
               "runner_sha256": _sha(Path(__file__).read_bytes()),
               "product_config_sha256": config_identity}
    with _lock():
        if _read_state() is not None or (LOCAL / "answer.raw.txt").exists():
            raise ValueError("本开发题已登记尝试；不允许自动重试")
        _atomic(LOCAL / "attempt.json", started)
    began = time.monotonic()
    try:
        with _deadline():
            response = OpenAICompatibleModel(config, system_prompt="",
                                             request_params=PARAMS).complete(messages=prompt, tools=[])
        raw = getattr(response, "text", None)
        metadata = _safe_metadata(getattr(response, "metadata", None))
        tool_calls = getattr(response, "tool_calls", ())
        if not isinstance(raw, str) or not raw.strip():
            if tool_calls:
                error = "unexpected_tool_call"
            elif metadata["finish_reason"] == "length":
                error = "finish_reason_length_empty_content"
            else:
                error = "empty_response"
            return _update({"status": "failed", "ended_at": _now(),
                            "elapsed_seconds": round(time.monotonic() - began, 3),
                            "error_category": error, "response_text_utf8_bytes": 0,
                            "tool_calls_count": len(tool_calls), **metadata})
        raw_hash = _save_raw(raw)
        usage = metadata.get("usage") or {}
        completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
        if tool_calls:
            error = "unexpected_tool_call"
        elif metadata["finish_reason"] not in {"stop", "completed"}:
            error = "finish_reason_not_complete"
        elif (len(raw.encode("utf-8")) > MAX_RAW_BYTES or
              (type(completion) is int and completion > PARAMS["max_tokens"])):
            error = "output_over_budget"
        else:
            try:
                parsed = parse(raw, report, manifest["question"], catalog,
                               manifest["catalog_sha256"])
            except ValueError:
                parsed, error = None, "contract_rejected"
            else:
                error = None
        return _update({"status": "needs_review" if error is None else "invalid_answer",
                        "ended_at": _now(), "elapsed_seconds": round(time.monotonic() - began, 3),
                        "raw_sha256": raw_hash, "raw_file": "answer.raw.txt",
                        "raw_utf8_bytes": len(raw.encode("utf-8")),
                        "contract_pass": error is None,
                        "interpretation_count": len(parsed["answer"]["points"]) if error is None else None,
                        "parsed": parsed, "error_category": error, **metadata})
    except ModelAdapterError as exc:
        code = exc.details.get("http_status")
        rejected = type(code) is int and 400 <= code < 500
        diagnostic = safe_error_details(exc)
        return _update({"status": "failed" if rejected else "unknown_outcome",
                        "ended_at": _now(), "elapsed_seconds": round(time.monotonic() - began, 3),
                        "error_category": "provider_rejected" if rejected else "provider_outcome_unknown",
                        "error_details": {**{key: value for key, value in diagnostic.items()
                                              if key in {"http_status", "category"}},
                                          **{key: value for key, value in exc.details.items()
                                             if key in {"http_status", "code", "param", "category"}}}})
    except Exception as exc:
        return _update({"status": "unknown_outcome", "ended_at": _now(),
                        "elapsed_seconds": round(time.monotonic() - began, 3),
                        "error_category": "total_deadline" if isinstance(exc, DeadlineExceeded)
                        else "local_outcome_unknown"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-call", action="store_true")
    args = parser.parse_args()
    if args.live != args.authorize_one_call:
        parser.error("真实请求需要同时提供 --live 与 --authorize-one-call")
    result = run_once() if args.live else check()
    visible = {key: value for key, value in result.items()
               if key not in {"parsed", "usage", "product_config_sha256", "request_params"}}
    print(json.dumps(visible, ensure_ascii=False))


if __name__ == "__main__":
    main()
