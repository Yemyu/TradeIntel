"""Run one frozen policy-field extraction case, with a durable no-retry ledger.

Default mode is offline preflight. A live attempt requires both explicit flags.
The provider's first response is saved before JSON or candidate validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any
import urllib.error
import urllib.request

from scripts.prepare_policy_extraction_pilot import ROOT, verify_package
from scripts.run_trade_v3_canary import _deadline, _locked
from tradeintel_ai.announcement_extraction_pilot import adapt_suggestion, encode_provider_request
from tradeintel_ai.local_provider_config import load_product_config, product_status


PACKAGES = {
    "r2": ROOT / "tmp/policy-extraction-dev-20260926/r2-v9",
    "d2": ROOT / "tmp/policy-extraction-dev-20260926/d2-v8",
    "h1": ROOT / "tmp/policy-extraction-dev-20260926/h1-v2",
    "h2": ROOT / "tmp/policy-extraction-dev-20260926/h2-v2",
}
BODY_SHA256 = {
    "r2": "e59b09a216f9e04e67ed0f57304d105d85b1c5ea0d6b635817bf20e9ec920e09",
    "d2": "c127004767322ceb85603ade8e6df521edfd432b0891822e0273a626a3ebee04",
    "h1": "068162a3c1b20c17632b3ed943ac036d1bdf278baae5889f333b12198d7a587f",
    "h2": "3e7f3dfd2566a00867b02a4a09a930c443c39863e499cd1b69679b8970734ddd",
}
MAX_RESPONSE_BYTES = 1_000_000
LOCAL_BUDGET_USD = 0.10
PEAK_INPUT_PER_MILLION = 0.30
PEAK_OUTPUT_PER_MILLION = 1.20
MAX_OUTPUT_TOKENS = 4096
MAX_INPUT_TOKENS_ESTIMATE = 24_000
CASE_ORDER = ("r2", "d2", "h1", "h2")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _private_dir(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("unsafe experiment directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("experiment directory must be private")


def _root() -> Path:
    root = ROOT / ".local" / "experiments" / "policy-extraction-v1"
    for folder in (ROOT / ".local", ROOT / ".local" / "experiments"):
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("unsafe experiment parent directory")
    _private_dir(root)
    return root


def _read_json(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        raise ValueError("unsafe experiment record")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("unsafe experiment record")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid experiment record")
    return value


def _atomic(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".policy-extract-", dir=path.parent)
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


def _save_response(path: Path, data: bytes) -> str:
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeds safe storage limit")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def _body(case: str) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    package = PACKAGES[case]
    verified = verify_package(package)
    request = json.loads((package / "request.json").read_text(encoding="utf-8"))
    body = {
        "model": "deepseek-flash", "messages": request["messages"],
        "thinking": {"type": "enabled"}, "reasoning_effort": "high",
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"}, "stream": False,
    }
    encoded = encode_provider_request(body, request)
    if hashlib.sha256(encoded).hexdigest() != BODY_SHA256[case]:
        raise ValueError("final HTTP request differs from frozen preflight")
    return encoded, verified, request


def _config() -> Any:
    config = load_product_config()
    status = product_status()
    if not config.api_key or status["provider"] != "deepseek" \
            or config.base_url.rstrip("/") != "https://api.deepseek.com" \
            or config.model != "deepseek-flash" or status["reasoning"] != "high":
        raise ValueError("local provider configuration differs from frozen pilot")
    return config


def _usage_cost(usage: dict[str, Any]) -> float | None:
    input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(input_tokens) is not int or type(output_tokens) is not int \
            or input_tokens < 0 or output_tokens < 0:
        return None
    return round((input_tokens * PEAK_INPUT_PER_MILLION +
                  output_tokens * PEAK_OUTPUT_PER_MILLION) / 1_000_000, 8)


def _prior_gate(case: str, root: Path) -> float:
    spent = 0.0
    for prior in CASE_ORDER[:CASE_ORDER.index(case)]:
        record = _read_json(root / f"{prior}.json")
        if record is None or record.get("status") != "needs_review":
            raise ValueError(f"{prior} has not produced a contract-valid first answer")
        review = _read_json(root / f"{prior}.review.json")
        if review is None or review.get("decision") != "pass" \
                or review.get("response_sha256") != record.get("raw_response_sha256"):
            raise ValueError(f"{prior} semantic review has not passed")
        amount = record.get("peak_cost_estimate_usd")
        if type(amount) not in (int, float) or amount < 0:
            raise ValueError(f"{prior} has no measurable usage; stop")
        spent += amount
    # A conservative local estimate, not a provider-side charge limit.
    proposed = (MAX_INPUT_TOKENS_ESTIMATE * PEAK_INPUT_PER_MILLION +
                MAX_OUTPUT_TOKENS * PEAK_OUTPUT_PER_MILLION) / 1_000_000
    if spent + proposed > LOCAL_BUDGET_USD:
        raise ValueError("local estimated cost cap would be exceeded")
    return round(spent + proposed, 8)


def check(case: str) -> dict[str, Any]:
    encoded, verified, _ = _body(case)
    _config()
    root = _root()
    existing = _read_json(root / f"{case}.json")
    if existing is None:
        estimated_total = _prior_gate(case, root)
    else:
        estimated_total = None
    return {"case": case, "package": verified["status"], "body_bytes": len(encoded),
            "body_sha256": BODY_SHA256[case],
            "ledger_status": existing.get("status") if existing else "not_started",
            "estimated_peak_total_usd": estimated_total, "api_calls": 0}


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
            data = response.read(MAX_RESPONSE_BYTES + 1)
    return data


def run_once(case: str) -> dict[str, Any]:
    encoded, verified, request = _body(case)
    config = _config()
    root = _root()
    ledger, raw_path, draft_path = (root / f"{case}{suffix}" for suffix in
                                    (".json", ".response.json", ".draft.json"))
    lock = root / f"{case}.lock"
    with _locked(lock):
        if _read_json(ledger) is not None or raw_path.exists():
            raise ValueError("this case already has an attempt; never retry or overwrite")
        estimated_total = _prior_gate(case, root)
        record = {"schema_version": "policy-extraction-attempt-v1", "case": case,
                  "status": "provider_call_started", "started_at_utc": _utc(),
                  "package": str(PACKAGES[case]), "package_request_sha256": verified["request_sha256"],
                  "http_body_sha256": BODY_SHA256[case], "http_body_bytes": len(encoded),
                  "model": "deepseek-flash", "reasoning_effort": "high",
                  "estimated_peak_total_usd_before_call": estimated_total,
                  "attempts": 1}
        _atomic(ledger, record)
        try:
            data = _post(encoded, config.api_key)
        except urllib.error.HTTPError as exc:
            record.update(status="provider_http_error", http_status=exc.code, finished_at_utc=_utc())
            _atomic(ledger, record)
            return {"case": case, "status": record["status"], "http_status": exc.code}
        except Exception as exc:
            # Never copy provider body, URL, headers, key, or arbitrary exception text.
            record.update(status="unknown_outcome", error_type=type(exc).__name__,
                          finished_at_utc=_utc())
            _atomic(ledger, record)
            return {"case": case, "status": record["status"], "error_type": type(exc).__name__}
        try:
            raw_hash = _save_response(raw_path, data)
        except Exception as exc:
            record.update(status="unknown_outcome", error_type=type(exc).__name__,
                          finished_at_utc=_utc())
            _atomic(ledger, record)
            return {"case": case, "status": record["status"], "error_type": type(exc).__name__}
        try:
            record.update(raw_response_sha256=raw_hash, raw_response_bytes=len(data),
                          status="raw_saved", finished_at_utc=_utc())
            _atomic(ledger, record)
            provider = json.loads(data)
            usage = provider.get("usage") if isinstance(provider, dict) else None
            cost = _usage_cost(usage) if isinstance(usage, dict) else None
            choice = provider["choices"][0]
            content = choice["message"]["content"]
            record.update(usage=usage if isinstance(usage, dict) else None,
                          peak_cost_estimate_usd=cost,
                          finish_reason=choice.get("finish_reason"))
            if cost is None:
                raise ValueError("provider usage absent or malformed")
            if choice.get("finish_reason") != "stop" or not isinstance(content, str) or not content.strip():
                raise ValueError("response empty or truncated")
            answer = json.loads(content)
            store = json.loads((PACKAGES[case] / "document-store.json").read_text(encoding="utf-8"))
            draft = adapt_suggestion(answer, store, request["doc_version"])
            _atomic(draft_path, draft)
            record["status"] = "needs_review"
        except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
            record.update(status="invalid_answer", validation_error_type=type(exc).__name__,
                          validation_error=str(exc)[:300])
        _atomic(ledger, record)
        return {"case": case, "status": record["status"],
                "finish_reason": record.get("finish_reason"),
                "usage": record.get("usage"),
                "peak_cost_estimate_usd": record.get("peak_cost_estimate_usd"),
                "validation_error": record.get("validation_error"),
                "raw_response_sha256": record.get("raw_response_sha256")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASE_ORDER, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-call", action="store_true")
    args = parser.parse_args()
    if args.live != args.authorize_one_call:
        parser.error("live mode requires both --live and --authorize-one-call")
    result = run_once(args.case) if args.live else check(args.case)
    print(json.dumps(result, ensure_ascii=False, indent=2))
