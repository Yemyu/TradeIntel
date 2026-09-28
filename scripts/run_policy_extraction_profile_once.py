"""Run one versioned policy-extraction profile without retrying or overwriting.

The profile is prepared and verified offline first. A live call is intentionally
separate from the previous v1/high-thinking ledger, so results cannot be
silently compared as if they used the same request.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request
from typing import Any

from scripts.prepare_policy_extraction_profile_v5 import verify_profile
from scripts.prepare_policy_extraction_pilot import ROOT
from scripts.run_trade_v3_canary import _deadline, _locked
from tradeintel_ai.announcement_extraction_pilot import adapt_suggestion
from tradeintel_ai.local_provider_config import load_product_config, product_status


PROFILE = ROOT / "tmp/policy-extraction-dev-20260926/r2-v9-no-thinking-per-code-evidence2"
LEDGER_ROOT = ROOT / ".local/experiments/policy-extraction-v5-no-thinking-per-code-evidence2"
MAX_RESPONSE_BYTES = 1_000_000
LOCAL_BUDGET_USD = 0.10
INPUT_PRICE_PER_MILLION = 0.30
OUTPUT_PRICE_PER_MILLION = 1.20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _private_root() -> Path:
    parent = ROOT / ".local" / "experiments"
    if parent.is_symlink() or not parent.is_dir():
        raise ValueError("unsafe local experiment parent")
    if LEDGER_ROOT.is_symlink():
        raise ValueError("unsafe local experiment ledger")
    LEDGER_ROOT.mkdir(mode=0o700, exist_ok=True)
    if not LEDGER_ROOT.is_dir() or LEDGER_ROOT.stat().st_mode & 0o077:
        raise ValueError("experiment ledger must be private")
    return LEDGER_ROOT


def _read(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        raise ValueError("unsafe experiment record")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("invalid experiment record")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid experiment record")
    return value


def _atomic(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                          allow_nan=False) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".policy-v2-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save_raw(path: Path, data: bytes) -> str:
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeds safe storage limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def _config() -> Any:
    config = load_product_config()
    status = product_status()
    if not config.api_key or status["provider"] != "deepseek" \
            or config.base_url.rstrip("/") != "https://api.deepseek.com" \
            or config.model != "deepseek-flash":
        raise ValueError("local provider is not the frozen DeepSeek Flash endpoint")
    return config


def _usage_cost(usage: dict[str, Any]) -> float | None:
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is not int or type(completion) is not int or prompt < 0 or completion < 0:
        return None
    return round((prompt * INPUT_PRICE_PER_MILLION +
                  completion * OUTPUT_PRICE_PER_MILLION) / 1_000_000, 8)


def _paths() -> tuple[Path, Path, Path]:
    root = _private_root()
    return root / "r2.json", root / "r2.response.json", root / "r2.draft.json"


def check() -> dict[str, Any]:
    verified = verify_profile(PROFILE)
    _config()
    ledger, _, _ = _paths()
    existing = _read(ledger)
    return {"profile": verified, "ledger_status": existing.get("status") if existing else "not_started",
            "api_calls": 0, "local_budget_usd": LOCAL_BUDGET_USD}


def _post(body: bytes, api_key: str) -> bytes:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            raise ValueError("provider redirect refused")

    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": "Bearer " + api_key,
                 "Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(NoRedirect())
    with _deadline(90):
        with opener.open(request, timeout=90) as response:
            if response.status != 200:
                raise ValueError("provider did not return HTTP 200")
            return response.read(MAX_RESPONSE_BYTES + 1)


def run_once() -> dict[str, Any]:
    verified = verify_profile(PROFILE)
    config = _config()
    ledger, raw_path, draft_path = _paths()
    lock = LEDGER_ROOT / "r2.lock"
    body = json.loads((PROFILE / "provider-body.json").read_text(encoding="utf-8"))
    request = json.loads((PROFILE / "request.json").read_text(encoding="utf-8"))
    body_bytes = json.dumps(body, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode("utf-8")
    with _locked(lock):
        if _read(ledger) is not None or raw_path.exists():
            raise ValueError("v2 R2 already has an attempt; never retry or overwrite")
        record: dict[str, Any] = {
            "schema_version": "policy-extraction-profile-attempt-v1",
            "profile": str(PROFILE), "profile_sha256": hashlib.sha256(
                (PROFILE / "manifest.json").read_bytes()).hexdigest(),
            "status": "provider_call_started", "started_at_utc": _now(),
            "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
            "body_bytes": len(body_bytes), "model": body["model"],
            "thinking": body["thinking"], "reasoning_effort": body["reasoning_effort"],
            "max_tokens": body["max_tokens"], "attempts": 1,
        }
        _atomic(ledger, record)
        try:
            raw = _post(body_bytes, config.api_key)
        except urllib.error.HTTPError as exc:
            record.update(status="provider_http_error", http_status=exc.code,
                          finished_at_utc=_now())
            _atomic(ledger, record)
            return {"status": record["status"], "http_status": exc.code}
        except Exception as exc:
            record.update(status="unknown_outcome", error_type=type(exc).__name__,
                          finished_at_utc=_now())
            _atomic(ledger, record)
            return {"status": record["status"], "error_type": type(exc).__name__}
        try:
            raw_hash = _save_raw(raw_path, raw)
            record.update(status="raw_saved", raw_response_sha256=raw_hash,
                          raw_response_bytes=len(raw), finished_at_utc=_now())
            _atomic(ledger, record)
            provider = json.loads(raw)
            usage = provider.get("usage") if isinstance(provider, dict) else None
            cost = _usage_cost(usage) if isinstance(usage, dict) else None
            choice = provider["choices"][0]
            message = choice["message"]
            content = message.get("content")
            record.update(usage=usage if isinstance(usage, dict) else None,
                          peak_cost_estimate_usd=cost,
                          finish_reason=choice.get("finish_reason"))
            if cost is None:
                raise ValueError("provider usage absent or malformed")
            if cost > LOCAL_BUDGET_USD:
                raise ValueError("recorded usage exceeds local budget")
            if choice.get("finish_reason") != "stop" or not isinstance(content, str) or not content.strip():
                raise ValueError("response empty or truncated")
            answer = json.loads(content)
            store = json.loads((ROOT / "tmp/policy-extraction-dev-20260926/r2-v9/document-store.json").read_text())
            draft = adapt_suggestion(answer, store, request["doc_version"])
            _atomic(draft_path, draft)
            record["status"] = "needs_review"
        except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
            record.update(status="invalid_answer", validation_error_type=type(exc).__name__,
                          validation_error=str(exc)[:300])
        _atomic(ledger, record)
        return {"status": record["status"], "finish_reason": record.get("finish_reason"),
                "usage": record.get("usage"), "peak_cost_estimate_usd": record.get("peak_cost_estimate_usd"),
                "raw_response_sha256": record.get("raw_response_sha256"),
                "validation_error": record.get("validation_error")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-call", action="store_true")
    args = parser.parse_args()
    if args.live != args.authorize_one_call:
        parser.error("live mode requires both --live and --authorize-one-call")
    print(json.dumps(run_once() if args.live else check(), ensure_ascii=False, indent=2))
