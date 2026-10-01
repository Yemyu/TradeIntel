"""One authorized attempt for the final FR2026-19516 reading package.

The default command is offline. A live attempt consumes the case's existing
one-shot ledger before any provider request; an uncertain result is not retried.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from scripts import run_announcement_reading_unseen_once as candidate_runner
from scripts.freeze_announcement_reading_unseen_live import (
    CASE_ID, DEADLINE_SECONDS, ENDPOINT, FROZEN, INPUT_TOKEN_RESERVE,
    MAX_BODY_BYTES, MODEL, PARAMS, PLANNED_USD_LIMIT, ROOT, SCHEMA as FREEZE_SCHEMA,
    STATUS as FREEZE_STATUS, _read, _sha, peak_estimate_usd, verify_frozen,
)
from scripts.run_trade_v3_canary import _atomic, _deadline, _locked, _now
from tradeintel_ai.announcement_reading_suggestions import parse_reading_answer
from tradeintel_ai.local_provider_config import product_status


# Preserve exactly the same consumption slot as the immutable offline candidate.
LEDGER_ROOT = candidate_runner.LEDGER_ROOT
LEDGER_PARENT = candidate_runner.LEDGER_PARENT
LEDGER_NAME = candidate_runner.LEDGER_NAME
SCHEMA = candidate_runner.SCHEMA
MAX_RESPONSE_BYTES = 1_048_576
ALLOWED_RESPONSE_MODELS = frozenset({
    "deepseek-flash", "deepseek-v4.1-flash", "deepseek-v4-flash",
})


def _post(body: bytes, api_key: str) -> bytes:
    request = Request(
        ENDPOINT, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    with build_opener(candidate_runner._NoRedirect()).open(
            request, timeout=DEADLINE_SECONDS) as response:
        if response.geturl() != ENDPOINT:
            raise ValueError("provider final URL changed")
        return response.read(MAX_RESPONSE_BYTES + 1)


def _fsync_directory(path: Path) -> None:
    """Persist a newly created ledger directory entry before spending a call."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _package() -> tuple[dict[str, Any], dict[str, Any]]:
    store = json.loads(_read(FROZEN / "source-store.json"))
    request = json.loads(_read(FROZEN / "offline/request.json"))
    sidecar = json.loads(_read(FROZEN / "offline/anchor-map.json"))
    offline = json.loads(_read(FROZEN / "offline/MANIFEST.json"))
    return store, {**request, "status": "offline_review_only",
                   "anchors": sidecar["anchors"], "boundary": offline["boundary"]}


def _interpret(raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeded the byte limit")
    provider = json.loads(raw)
    if (not isinstance(provider, dict) or not isinstance(provider.get("choices"), list)
            or len(provider["choices"]) != 1):
        raise ValueError("provider response shape is invalid")
    model = provider.get("model")
    if (not isinstance(model, str) or
            model.lower() not in ALLOWED_RESPONSE_MODELS):
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
    frozen = verify_frozen(FROZEN)
    if (frozen.get("status") != FREEZE_STATUS or
            frozen.get("case_id") != CASE_ID or
            frozen.get("live_eligible_after_authorization") is not True or
            frozen.get("planned_usd_limit") != str(PLANNED_USD_LIMIT) or
            frozen.get("peak_reserve_estimate_usd") != str(peak_estimate_usd()) or
            peak_estimate_usd() > PLANNED_USD_LIMIT):
        raise ValueError("final package has no valid release or cost gate")
    return frozen


def check() -> dict[str, Any]:
    """Read-only preflight; it never creates a ledger or contacts the API."""
    frozen = _release_check()
    candidate_runner._private_folder(create=False)
    ledger_path, _, _, _ = candidate_runner._paths()
    recorded = (candidate_runner._ledger(ledger_path)
                if LEDGER_ROOT.exists() else None)
    status = product_status()
    return {**frozen, "configured_provider": status["provider"],
            "configured_model": status["model"],
            "attempt_status": recorded["status"] if recorded else "not_started",
            "provider_calls_by_check": 0}


def run_once(*, authorized: bool, price_confirmed_date: str) -> dict[str, Any]:
    if not authorized or price_confirmed_date != datetime.now().astimezone().date().isoformat():
        raise ValueError("one-call authorization and today's price check are required")
    frozen = _release_check()
    body = _read(FROZEN / "provider-body.json", max_bytes=MAX_BODY_BYTES)
    if frozen["body_sha256"] != _sha(body):
        raise ValueError("POST bytes differ from the verified final package")
    config, config_identity = candidate_runner._config()
    candidate_runner._private_folder(create=True)
    _fsync_directory(LEDGER_PARENT)
    ledger_path, raw_path, review_path, lock_path = candidate_runner._paths()
    with _locked(lock_path):
        if any(path.exists() or path.is_symlink() for path in
               (ledger_path, raw_path, review_path)):
            raise ValueError("unseen call already started; never retry automatically")
        record: dict[str, Any] = {
            "schema_version": SCHEMA, "status": "provider_call_started",
            "started_at": _now(), "case_id": CASE_ID,
            "final_freeze_schema": FREEZE_SCHEMA,
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
        candidate_runner._save_exclusive(raw_path, raw)
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
        candidate_runner._save_exclusive(
            review_path, json.dumps(review, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        _fsync_directory(LEDGER_ROOT)
        record.update(status="needs_human_review", response=metadata,
                      review_sha256=_sha(_read(review_path)), ended_at=_now())
        _atomic(ledger_path, record)
        return {"status": record["status"], "retry_allowed": False,
                "usage": metadata}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-call", action="store_true")
    parser.add_argument("--price-confirmed-date", default="")
    args = parser.parse_args()
    result = (run_once(authorized=args.authorize_one_call,
                       price_confirmed_date=args.price_confirmed_date)
              if args.live else check())
    print(json.dumps(result, ensure_ascii=False, indent=2))
