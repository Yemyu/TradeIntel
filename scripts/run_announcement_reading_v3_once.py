"""One-attempt FR2026-19517 v3 runner; defaults to read-only preflight.

The shipped offline candidate is never sendable. A separately authorized live
freeze, a same-day price confirmation, and a fresh isolated ledger are all
required before the sole provider attempt. No automatic retry exists.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import stat
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from scripts.freeze_announcement_reading_v3_once import (
    CASE_ID, DEADLINE_SECONDS, ENDPOINT, FROZEN_CANDIDATE, FROZEN_LIVE,
    INPUT_TOKEN_RESERVE, LEDGER_RELATIVE, LIVE_STATUS, MAX_POST_BYTES, MODEL,
    PARAMS, PLANNED_USD_LIMIT, PRICE_CHECKED_ON, ROOT, SCHEMA as FREEZE_SCHEMA,
    _read, _sha, peak_estimate_usd, verify_frozen,
)
from scripts.run_trade_v3_canary import _atomic, _deadline, _locked, _now
from tradeintel_ai.announcement_reading_v3 import parse_reading_answer
from tradeintel_ai.local_provider_config import (
    PRODUCT_CONFIG_PATH, load_product_config, product_config_identity,
    product_status,
)


LEDGER_ROOT = ROOT / LEDGER_RELATIVE
LEDGER_PARENT = LEDGER_ROOT.parent
LEDGER_NAME = CASE_ID
SCHEMA = "announcement-reading-v3-one-attempt-ledger-v1"
MAX_RESPONSE_BYTES = 1_048_576
ALLOWED_RESPONSE_MODELS = frozenset({
    "deepseek-flash", "deepseek-v4.1-flash", "deepseek-v4-flash",
})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("provider redirect refused")


def _post(body: bytes, api_key: str) -> bytes:
    request = Request(
        ENDPOINT, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    with build_opener(_NoRedirect()).open(request, timeout=DEADLINE_SECONDS) as response:
        if response.geturl() != ENDPOINT:
            raise ValueError("provider final URL changed")
        return response.read(MAX_RESPONSE_BYTES + 1)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _paths() -> tuple[Path, Path, Path, Path]:
    return tuple(LEDGER_ROOT / f"{LEDGER_NAME}{suffix}" for suffix in
                 (".json", ".raw.json", ".review.json", ".lock"))


def _private_folder(*, create: bool) -> None:
    for parent in (ROOT / ".local", ROOT / ".local/experiments"):
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("private experiment parent is unsafe or absent")
    if create:
        if LEDGER_PARENT.is_symlink() or LEDGER_ROOT.is_symlink():
            raise ValueError("v3 experiment folder is a symlink")
        LEDGER_PARENT.mkdir(mode=0o700, exist_ok=True)
        _fsync_directory(LEDGER_PARENT.parent)
        LEDGER_ROOT.mkdir(mode=0o700, exist_ok=True)
        _fsync_directory(LEDGER_PARENT)
    for path in (LEDGER_PARENT, LEDGER_ROOT):
        if path.is_symlink():
            raise ValueError("v3 experiment folder is a symlink")
        if path.exists() and (not path.is_dir() or
                              stat.S_IMODE(path.stat().st_mode) & 0o077):
            raise ValueError("v3 experiment folder must be owner-only")
    if create and (not LEDGER_PARENT.is_dir() or not LEDGER_ROOT.is_dir()):
        raise ValueError("v3 experiment folder could not be created")


def _ledger(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("v3 attempt ledger is unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA or
            value.get("case_id") != CASE_ID):
        raise ValueError("v3 attempt ledger identity is invalid")
    return value


def _config() -> tuple[Any, str]:
    if (PRODUCT_CONFIG_PATH.is_symlink() or not PRODUCT_CONFIG_PATH.is_file() or
            PRODUCT_CONFIG_PATH.parent.is_symlink()):
        raise ValueError("private product model configuration is missing or unsafe")
    config = load_product_config()
    status = product_status()
    if (not config.api_key or status["provider"] != "deepseek" or
            config.base_url.rstrip("/") != "https://api.deepseek.com" or
            config.model != MODEL or status["reasoning"] != "high"):
        raise ValueError("saved provider/model differs from the v3 frozen plan")
    return config, product_config_identity()


def _save_exclusive(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _package() -> tuple[dict[str, Any], dict[str, Any]]:
    store = json.loads(_read(FROZEN_LIVE / "source-store.json"))
    request = json.loads(_read(FROZEN_LIVE / "offline/request.json"))
    sidecar = json.loads(_read(FROZEN_LIVE / "offline/anchor-map.json"))
    return store, {**request, "status": "offline_review_only",
                   "anchors": sidecar["anchors"], "boundary": sidecar["boundary"]}


def _interpret(raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeded the byte limit")
    provider = json.loads(raw)
    if (not isinstance(provider, dict) or not isinstance(provider.get("choices"), list)
            or len(provider["choices"]) != 1):
        raise ValueError("provider response shape is invalid")
    model = provider.get("model")
    if not isinstance(model, str) or model.lower() not in ALLOWED_RESPONSE_MODELS:
        raise ValueError("provider response model differs from the Flash plan")
    choice = provider["choices"][0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise ValueError("provider answer was truncated or did not stop normally")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("provider returned empty final content")
    usage = provider.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("provider usage was absent")
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if (type(prompt) is not int or type(completion) is not int or prompt < 0 or
            completion < 0 or prompt > INPUT_TOKEN_RESERVE or
            completion > PARAMS["max_tokens"]):
        raise ValueError("provider usage is malformed or exceeds the reserve")
    store, package = _package()
    review = parse_reading_answer(content, package, store)
    return review, {"prompt_tokens": prompt, "completion_tokens": completion,
                    "finish_reason": "stop", "provider_model": model,
                    "peak_cache_miss_estimate_usd": str(peak_estimate_usd(prompt, completion)),
                    "response_sha256": _sha(raw)}


def _release_check() -> dict[str, Any]:
    frozen = verify_frozen(FROZEN_LIVE)
    if (frozen.get("status") != LIVE_STATUS or
            frozen.get("case_id") != CASE_ID or
            frozen.get("live_eligible_after_authorization") is not True or
            frozen.get("planned_usd_limit") != str(PLANNED_USD_LIMIT) or
            frozen.get("peak_reserve_estimate_usd") != str(peak_estimate_usd()) or
            peak_estimate_usd() > PLANNED_USD_LIMIT):
        raise ValueError("v3 package has no valid release or cost gate")
    return frozen


def check() -> dict[str, Any]:
    """Read-only; do not open the private model config or create a ledger."""
    candidate = verify_frozen(FROZEN_CANDIDATE)
    if not FROZEN_LIVE.exists():
        return {"status": "not_released", "case_id": CASE_ID,
                "candidate_body_bytes": candidate["body_bytes"],
                "candidate_body_sha256": candidate["body_sha256"],
                "attempt_status": "not_started", "provider_calls_by_check": 0}
    frozen = _release_check()
    _private_folder(create=False)
    ledger_path, _, _, _ = _paths()
    recorded = _ledger(ledger_path) if LEDGER_ROOT.exists() else None
    return {**frozen, "attempt_status": recorded["status"] if recorded else "not_started",
            "provider_calls_by_check": 0}


def run_once(*, authorized: bool, price_confirmed_date: str) -> dict[str, Any]:
    today = datetime.now().astimezone().date().isoformat()
    if not authorized or price_confirmed_date != today or PRICE_CHECKED_ON != today:
        raise ValueError("one-call authorization and today's price check are required")
    frozen = _release_check()
    body = _read(FROZEN_LIVE / "provider-body.json", max_bytes=MAX_POST_BYTES)
    if frozen["body_sha256"] != _sha(body):
        raise ValueError("POST bytes differ from the verified v3 package")
    config, config_identity = _config()
    _private_folder(create=True)
    ledger_path, raw_path, review_path, lock_path = _paths()
    with _locked(lock_path):
        if any(path.exists() or path.is_symlink() for path in
               (ledger_path, raw_path, review_path)):
            raise ValueError("v3 call already started; never retry automatically")
        record: dict[str, Any] = {
            "schema_version": SCHEMA, "status": "provider_call_started",
            "started_at": _now(), "case_id": CASE_ID,
            "freeze_schema": FREEZE_SCHEMA,
            "manifest_sha256": frozen["manifest_sha256"],
            "body_sha256": frozen["body_sha256"],
            "config_identity_sha256": config_identity,
            "model": MODEL, "endpoint": ENDPOINT, "params": PARAMS,
            "price_confirmed_date": price_confirmed_date,
            "peak_reserve_estimate_usd": frozen["peak_reserve_estimate_usd"],
            "planned_usd_limit": frozen["planned_usd_limit"],
            "account_hard_cap": False, "automatic_retries": 0,
        }
        _atomic(ledger_path, record)
        _fsync_directory(LEDGER_ROOT)
        try:
            with _deadline(DEADLINE_SECONDS):
                raw = _post(body, config.api_key)
        except HTTPError as exc:
            record.update(status="provider_rejected" if 400 <= exc.code < 500 else
                          "unknown_outcome", http_status=exc.code, ended_at=_now())
            _atomic(ledger_path, record)
            return {"status": record["status"], "http_status": exc.code,
                    "retry_allowed": False}
        except (TimeoutError, URLError, OSError, ValueError):
            record.update(status="unknown_outcome", error_category="transport_or_deadline",
                          ended_at=_now())
            _atomic(ledger_path, record)
            return {"status": record["status"], "retry_allowed": False}
        if len(raw) > MAX_RESPONSE_BYTES:
            record.update(status="invalid_response", error_category="response_too_large",
                          ended_at=_now())
            _atomic(ledger_path, record)
            return {"status": record["status"], "retry_allowed": False}
        _save_exclusive(raw_path, raw)
        _fsync_directory(LEDGER_ROOT)
        record["raw_sha256"] = _sha(raw)
        record["raw_saved_at"] = _now()
        _atomic(ledger_path, record)
        try:
            review, metadata = _interpret(raw)
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            record.update(status="invalid_response", error_category="answer_contract",
                          ended_at=_now())
            _atomic(ledger_path, record)
            return {"status": record["status"], "retry_allowed": False}
        review_bytes = json.dumps(review, ensure_ascii=False, sort_keys=True).encode("utf-8")
        _save_exclusive(review_path, review_bytes)
        _fsync_directory(LEDGER_ROOT)
        record.update(status="needs_human_review" if review["ready_for_review"] else
                      "invalid_response", response=metadata,
                      error_category=None if review["ready_for_review"] else "incomplete_check",
                      review_sha256=_sha(review_bytes), ended_at=_now())
        _atomic(ledger_path, record)
        return {"status": record["status"], "retry_allowed": False,
                "usage": metadata}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--live", action="store_true")
    cli.add_argument("--authorize-one-call", action="store_true")
    cli.add_argument("--price-confirmed-date", default="")
    args = cli.parse_args()
    result = (run_once(authorized=args.authorize_one_call,
                       price_confirmed_date=args.price_confirmed_date)
              if args.live else check())
    print(json.dumps(result, ensure_ascii=False, indent=2))
