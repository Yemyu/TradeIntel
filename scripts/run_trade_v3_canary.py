"""One-shot v3 development canary with a durable no-retry ledger.

Without --live --authorize-one-call this command only verifies the package and
prints safe preflight information. Never use the scored four-question package
here. The one live attempt is recorded *before* any provider request.
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
from typing import Any, Iterator

from tradeintel_ai.local_provider_config import (
    PRODUCT_CONFIG_PATH, load_product_config, product_config_identity,
    product_request_params, product_status,
)
from tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleModel
from tradeintel_ai.trade_explanation import MAX_INPUT_BYTES, MAX_RAW_BYTES, parse

from scripts.prepare_trade_v3_canary import MODEL_REQUEST, ROOT, verify


_LEDGER_NAME = "trade-v3-canary"
_LEDGER_SCHEMA = "trade-v3-canary-run-v1"
_SAFE_ERROR_KEYS = {"http_status", "code", "param", "category"}


class DeadlineExceeded(TimeoutError):
    """The whole local attempt reached its wall-clock limit."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _ledger_root(root: Path) -> Path:
    base = root / ".local"
    folder = base / _LEDGER_NAME
    for path in (base, folder):
        if path.is_symlink():
            raise ValueError("开发试验账本路径不安全")
        path.mkdir(mode=0o700, exist_ok=True)
        if not path.is_dir():
            raise ValueError("开发试验账本目录无效")
    return folder


def _paths(root: Path, package: Path) -> tuple[Path, Path, Path]:
    # One v3 development attempt *in total*, not one per regenerated package.
    # The package digest is recorded inside the ledger for provenance.
    del package
    folder = _ledger_root(root)
    case_id = "dev-soybean-export"
    return (folder / f"{case_id}.json", folder / f"{case_id}.raw.txt",
            folder / f"{case_id}.lock")


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("开发试验账本文件无效")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != _LEDGER_SCHEMA:
        raise ValueError("开发试验账本结构无效")
    return value


def _atomic(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".trade-v3-canary-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("开发试验锁文件无效")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _deadline(seconds: int) -> Iterator[None]:
    if not hasattr(signal, "setitimer"):
        raise ValueError("当前系统不能保证单次调用总时限")
    previous = signal.getsignal(signal.SIGALRM)
    if previous not in (signal.SIG_DFL, signal.SIG_IGN):
        raise ValueError("当前进程已有计时器，不能安全启动开发调用")
    def expired(_signum: int, _frame: object) -> None:
        raise DeadlineExceeded("单次调用达到总时限，结果未知；不自动重试")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _config() -> tuple[Any, dict[str, object], str]:
    if not PRODUCT_CONFIG_PATH.is_file() or PRODUCT_CONFIG_PATH.is_symlink():
        raise ValueError("未找到安全的产品模型配置；不使用旧实验密钥")
    config = load_product_config()
    status = product_status()
    params = {**product_request_params(), "max_tokens": MODEL_REQUEST["max_tokens"]}
    expected_params = {"thinking": {"type": MODEL_REQUEST["thinking"]},
                       "reasoning_effort": MODEL_REQUEST["reasoning"],
                       "max_tokens": MODEL_REQUEST["max_tokens"]}
    if (not config.api_key or status["provider"] != MODEL_REQUEST["provider"] or
            config.base_url.rstrip("/") != MODEL_REQUEST["base_url"] or
            config.model != MODEL_REQUEST["model"] or
            config.temperature != MODEL_REQUEST["temperature"] or
            params != expected_params):
        raise ValueError("产品模型配置与本次开发题固定参数不一致；不发送请求")
    return (replace(config, timeout_seconds=min(config.timeout_seconds, 90)),
            params, product_config_identity())


def _safe_metadata(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    model = metadata.get("model")
    usage = metadata.get("usage")
    if not isinstance(model, str) or len(model) > 100:
        model = None
    if not isinstance(usage, dict) or len(_bytes(usage)) > 20_000:
        usage = None
    return {"response_model": model, "usage": usage,
            "finish_reason": metadata.get("finish_reason")
            if isinstance(metadata.get("finish_reason"), str) else None}


def _update(ledger: Path, lock: Path, changes: dict[str, Any]) -> dict[str, Any]:
    with _locked(lock):
        record = _read(ledger)
        if record is None or record.get("status") != "provider_call_started":
            raise ValueError("开发试验状态已变化；不得覆盖历史结果")
        record.update(changes)
        _atomic(ledger, record)
        return record


def _save_raw(path: Path, raw: str) -> str:
    data = raw.encode("utf-8")
    if len(data) > 1_000_000:
        raise ValueError("模型原答超过可保存上限")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def check(root: Path, package: Path) -> dict[str, Any]:
    root, package = Path(root).resolve(), Path(package).resolve()
    prepared = verify(root, package)
    ledger, _, _ = _paths(root, package)
    existing = _read(ledger)
    status = product_status()
    _config()
    return {"package": prepared["status"],
            "ledger_status": existing["status"] if existing else "not_started",
            "provider": status["provider"], "model": status["model"],
            "configured": status["configured"], "fixed_parameters_match": True,
            "api_calls_this_check": 0,
            "deadline_seconds": MODEL_REQUEST["total_deadline_seconds"],
            "max_tokens": MODEL_REQUEST["max_tokens"]}


def run_once(root: Path, package: Path) -> dict[str, Any]:
    root, package = Path(root).resolve(), Path(package).resolve()
    verify(root, package)
    config, params, config_digest = _config()
    ledger, raw_path, lock = _paths(root, package)
    manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
    request_bytes = (package / "requests/messages.json").read_bytes()
    report_bytes = (package / "host_artifacts/report.json").read_bytes()
    if (hashlib.sha256(request_bytes).hexdigest() !=
            manifest["files_sha256"]["requests/messages.json"] or
            hashlib.sha256(report_bytes).hexdigest() !=
            manifest["files_sha256"]["host_artifacts/report.json"]):
        raise ValueError("开发题包在预检后变化；不发送请求")
    prompt = json.loads(request_bytes)
    report = json.loads(report_bytes)
    if len(_bytes(prompt)) > MAX_INPUT_BYTES:
        raise ValueError("开发题模型输入超过预算")
    started = {"schema_version": _LEDGER_SCHEMA,
               "status": "provider_call_started", "api_calls_reserved": 1,
               "started_at": _now(), "requested_model": config.model,
               "config_sha256": config_digest,
               "manifest_sha256": hashlib.sha256((package / "MANIFEST.json").read_bytes()).hexdigest(),
               "report_sha256": manifest["report_sha256"],
               "request_sha256": hashlib.sha256(_bytes(prompt)).hexdigest(),
               "deadline_seconds": MODEL_REQUEST["total_deadline_seconds"],
               "request_params": params}
    with _locked(lock):
        if _read(ledger) is not None or raw_path.exists():
            raise ValueError("这份开发题包已有调用记录，不能再次调用")
        _atomic(ledger, started)
    started_monotonic = time.monotonic()
    try:
        with _deadline(MODEL_REQUEST["total_deadline_seconds"]):
            answer = OpenAICompatibleModel(config, system_prompt="",
                                           request_params=params).complete(messages=prompt, tools=[])
            raw = getattr(answer, "text", None)
            if not isinstance(raw, str) or not raw.strip():
                return _update(ledger, lock, {"status": "failed", "ended_at": _now(),
                                              "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                                              "error_category": "empty_response"})
            raw_digest = _save_raw(raw_path, raw)
            metadata = _safe_metadata(getattr(answer, "metadata", None))
            if getattr(answer, "tool_calls", ()):
                status, parsed, error = "invalid_answer", None, "unexpected_tool_call"
            elif metadata["finish_reason"] != "stop":
                status, parsed, error = "invalid_answer", None, "finish_reason_not_stop"
            elif len(raw.encode("utf-8")) > MAX_RAW_BYTES:
                status, parsed, error = "invalid_answer", None, "raw_over_budget"
            else:
                try:
                    parsed = parse(raw, report, manifest["report_sha256"])
                except ValueError:
                    status, parsed, error = "invalid_answer", None, "contract_rejected"
                else:
                    status, error = "needs_review", None
            return _update(ledger, lock, {"status": status, "ended_at": _now(),
                                          "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                                          "raw_sha256": raw_digest, "raw_file": raw_path.name,
                                          **metadata, "parsed": parsed,
                                          "error_category": error})
    except ModelAdapterError as exc:
        code = exc.details.get("http_status")
        failed = type(code) is int and 400 <= code < 500
        return _update(ledger, lock, {"status": "failed" if failed else "unknown_outcome",
                                      "ended_at": _now(),
                                      "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                                      "error_category": "provider_rejected" if failed else "provider_outcome_unknown",
                                      "error_details": {key: value for key, value in exc.details.items()
                                                        if key in _SAFE_ERROR_KEYS}})
    except Exception as exc:
        return _update(ledger, lock, {"status": "unknown_outcome", "ended_at": _now(),
                                      "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                                      "error_category": "total_deadline" if isinstance(exc, DeadlineExceeded)
                                      else "local_outcome_unknown"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-call", action="store_true")
    args = parser.parse_args()
    if args.authorize_one_call and not args.live:
        parser.error("授权标记必须与 --live 同时提供")
    if args.live and not args.authorize_one_call:
        parser.error("真实调用需要明确的 --authorize-one-call")
    result = run_once(args.root, args.package) if args.live else check(args.root, args.package)
    # Never print raw answers, prompts, credentials, or saved config.
    visible = {key: value for key, value in result.items()
               if key not in {"parsed", "request_params", "config_sha256"}}
    print(json.dumps(visible, ensure_ascii=False))


if __name__ == "__main__":
    main()
