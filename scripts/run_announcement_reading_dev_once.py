"""One-shot R2 reading-note development call; default action is offline preflight.

This never submits or enables an announcement. A started/uncertain attempt is
permanently spent; changing the frozen request requires a new reviewed plan.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import stat
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from scripts.freeze_announcement_reading_dev import (
    ENDPOINT, FROZEN, INPUT_TOKEN_RESERVE, MAX_BODY_BYTES, MODEL, PARAMS,
    PEAK_INPUT_USD_PER_M, PEAK_OUTPUT_USD_PER_M, PLANNED_USD_LIMIT, ROOT,
    _read, _sha, verify_frozen,
)
from scripts.run_trade_v3_canary import _atomic, _deadline, _locked, _now
from tradeintel_ai.announcement_reading_suggestions import parse_reading_answer
from tradeintel_ai.local_provider_config import (
    PRODUCT_CONFIG_PATH, load_product_config, product_config_identity,
    product_status,
)


LEDGER_ROOT = ROOT / ".local/experiments/announcement-reading-v2"
LEDGER_NAME = "r2-dev-20260928-v1"
SCHEMA = "announcement-reading-one-call-v1"
MAX_RESPONSE_BYTES = 1_048_576


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("provider redirect refused")


def _post(body: bytes, api_key: str) -> bytes:
    request = Request(
        ENDPOINT, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    with build_opener(_NoRedirect()).open(request, timeout=120) as response:
        if response.geturl() != ENDPOINT:
            raise ValueError("provider final URL changed")
        return response.read(MAX_RESPONSE_BYTES + 1)


def _paths(folder: Path) -> tuple[Path, Path, Path, Path]:
    return tuple(folder / f"{LEDGER_NAME}{suffix}" for suffix in
                 (".json", ".raw.json", ".review.json", ".lock"))


def _private_folder(folder: Path, *, create: bool) -> None:
    # Only the last child is created here; the existing project .local is reused.
    for parent in (ROOT / ".local", ROOT / ".local/experiments"):
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("private experiment parent is unsafe or absent")
    if folder.is_symlink():
        raise ValueError("private experiment folder is a symlink")
    if create:
        folder.mkdir(mode=0o700, exist_ok=True)
    if folder.exists() and (not folder.is_dir() or
                            stat.S_IMODE(folder.stat().st_mode) & 0o077):
        raise ValueError("private experiment folder must be owner-only")


def _ledger(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("reading attempt ledger is unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise ValueError("reading attempt ledger has an unknown schema")
    return value


def _config() -> tuple[Any, str]:
    if (PRODUCT_CONFIG_PATH.is_symlink() or not PRODUCT_CONFIG_PATH.is_file() or
            PRODUCT_CONFIG_PATH.parent.is_symlink()):
        raise ValueError("private product model configuration is missing or unsafe")
    config = load_product_config()
    status = product_status()
    if (not config.api_key or status["provider"] != "deepseek" or
            config.base_url.rstrip("/") != "https://api.deepseek.com" or
            config.model != MODEL):
        raise ValueError("saved provider/model differs from the frozen one-call plan")
    return config, product_config_identity()


def _save_exclusive(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _package() -> tuple[dict[str, Any], dict[str, Any]]:
    store = json.loads(_read(FROZEN / "source-store.json"))
    request = json.loads(_read(FROZEN / "offline/request.json"))
    sidecar = json.loads(_read(FROZEN / "offline/anchor-map.json"))
    offline_manifest = json.loads(_read(FROZEN / "offline/MANIFEST.json"))
    return store, {**request, "status": "offline_review_only",
                   "anchors": sidecar["anchors"],
                   "boundary": offline_manifest["boundary"]}


def _interpret(raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeded the frozen byte limit")
    provider = json.loads(raw)
    if not isinstance(provider, dict) or not isinstance(provider.get("choices"), list) \
            or len(provider["choices"]) != 1:
        raise ValueError("provider response shape is invalid")
    provider_model = provider.get("model")
    if (not isinstance(provider_model, str) or
            provider_model.lower() not in {"deepseek-flash", "deepseek-v4.1-flash"}):
        raise ValueError("provider response model differs from the frozen plan")
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
        raise ValueError("provider usage is malformed or over reserve")
    estimated = ((Decimal(prompt) * PEAK_INPUT_USD_PER_M +
                  Decimal(completion) * PEAK_OUTPUT_USD_PER_M) / Decimal(1_000_000))
    if estimated > PLANNED_USD_LIMIT:
        raise ValueError("provider usage exceeded the local cost plan")
    store, package = _package()
    review = parse_reading_answer(content, package, store)
    return review, {"prompt_tokens": prompt, "completion_tokens": completion,
                    "peak_cost_estimate_usd": str(estimated),
                    "finish_reason": "stop", "provider_model": provider_model,
                    "response_sha256": _sha(raw)}


def check(*, folder: Path = LEDGER_ROOT) -> dict[str, Any]:
    frozen = verify_frozen()
    _private_folder(folder, create=False)
    ledger_path, _, _, _ = _paths(folder)
    recorded = _ledger(ledger_path) if folder.exists() else None
    status = product_status()  # safe fields only; no credential is returned
    return {**frozen, "configured_provider": status["provider"],
            "configured_model": status["model"],
            "attempt_status": recorded["status"] if recorded else "not_started",
            "provider_calls_by_check": 0}


def run_once(*, authorized: bool, price_confirmed_date: str,
             folder: Path = LEDGER_ROOT) -> dict[str, Any]:
    if not authorized or price_confirmed_date != datetime.now().astimezone().date().isoformat():
        raise ValueError("one-call authorization and today's manual price check are required")
    frozen = verify_frozen()
    body = _read(FROZEN / "provider-body.json", max_bytes=MAX_BODY_BYTES)
    if len(body) > MAX_BODY_BYTES or frozen["body_sha256"] != _sha(body):
        raise ValueError("provider bytes differ from the frozen manifest")
    config, config_identity = _config()
    _private_folder(folder, create=True)
    ledger_path, raw_path, review_path, lock_path = _paths(folder)
    with _locked(lock_path):
        if any(path.exists() or path.is_symlink() for path in
               (ledger_path, raw_path, review_path)):
            raise ValueError("R2 development call already started; never retry automatically")
        record: dict[str, Any] = {
            "schema_version": SCHEMA, "status": "provider_call_started",
            "started_at": _now(), "case_id": frozen["case_id"],
            "manifest_sha256": frozen["manifest_sha256"],
            "body_sha256": frozen["body_sha256"],
            "config_identity_sha256": config_identity,
            "model": MODEL, "endpoint": ENDPOINT, "params": PARAMS,
            "price_confirmed_date": price_confirmed_date,
            "peak_estimate_usd": frozen["peak_estimate_usd"],
            "automatic_retries": 0,
        }
        _atomic(ledger_path, record)  # durable before any HTTP begins
        try:
            with _deadline(120):
                raw = _post(body, config.api_key)
        except HTTPError as exc:
            record.update(status="provider_rejected" if 400 <= exc.code < 500 else
                          "unknown_outcome", http_status=exc.code, ended_at=_now())
            _atomic(ledger_path, record)
            return {"status": record["status"], "http_status": exc.code,
                    "retry_allowed": False}
        except (TimeoutError, URLError, OSError, ValueError) as exc:
            del exc  # provider error text may contain private information
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
        _save_exclusive(review_path, json.dumps(review, ensure_ascii=False,
                                                  sort_keys=True).encode("utf-8"))
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
    if args.live:
        result = run_once(authorized=args.authorize_one_call,
                          price_confirmed_date=args.price_confirmed_date)
    else:
        result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
