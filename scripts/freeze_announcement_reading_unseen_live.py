"""Freeze and verify the final, one-call FR2026-19516 provider request.

This module never contacts the provider. The earlier offline candidate is
immutable: changing its freeze or runner code would invalidate its manifest.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from scripts import freeze_announcement_reading_unseen as candidate


ROOT = candidate.ROOT
CASE_ID = candidate.CASE_ID
SOURCE_STORE = candidate.SOURCE_STORE
OFFLINE_PACK = candidate.OFFLINE_PACK
FROZEN = ROOT / "evals/announcement_reading_v2/frozen/fr-2026-19516-unseen-live-v1"
MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"
PARAMS = {
    "thinking": {"type": "enabled"},
    "reasoning_effort": "high",
    "max_tokens": 20_000,
    "response_format": {"type": "json_object"},
    "stream": False,
}
SCHEMA = "announcement-reading-unseen-live-freeze-v1"
STATUS = "live_eligible_after_authorization"
MAX_BODY_BYTES = 30_000
INPUT_TOKEN_RESERVE = 40_000
DEADLINE_SECONDS = 180
PRICE_CHECKED_ON = "2026-09-29"
PRICE_SOURCE_URL = "https://api-docs.deepseek.com/quick_start/pricing/"
PEAK_INPUT_MISS_PER_M = Decimal("0.30")
PEAK_OUTPUT_PER_M = Decimal("1.20")
PLANNED_USD_LIMIT = Decimal("0.04")
CODE_FILES = (
    "scripts/freeze_announcement_reading_unseen_live.py",
    "scripts/run_announcement_reading_unseen_live_once.py",
    "scripts/freeze_announcement_reading_unseen.py",
    "scripts/run_announcement_reading_unseen_once.py",
    "scripts/prepare_announcement_reading_offline.py",
    "scripts/run_trade_v3_canary.py",
    "src/tradeintel_ai/announcement_reading_suggestions.py",
    "src/tradeintel_ai/policy_documents.py",
    "src/tradeintel_ai/local_provider_config.py",
)
PACK_FILES = candidate.PACK_FILES
_read = candidate._read
_sha = candidate._sha
_bytes = candidate._bytes


def peak_estimate_usd(input_tokens: int = INPUT_TOKEN_RESERVE,
                      output_tokens: int = PARAMS["max_tokens"]) -> Decimal:
    if (type(input_tokens) is not int or type(output_tokens) is not int or
            input_tokens < 0 or output_tokens < 0):
        raise ValueError("token counts must be nonnegative integers")
    return ((Decimal(input_tokens) * PEAK_INPUT_MISS_PER_M +
             Decimal(output_tokens) * PEAK_OUTPUT_PER_M) / Decimal(1_000_000))


def _body(request: dict[str, Any]) -> bytes:
    body = _bytes({"model": MODEL, "messages": request["messages"], **PARAMS})
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("final provider body exceeds the independent byte limit")
    return body


def _fixed_fields(body: bytes) -> dict[str, Any]:
    estimate = peak_estimate_usd()
    if estimate > PLANNED_USD_LIMIT:
        raise ValueError("peak cost reserve exceeds the planned limit")
    return {
        "schema_version": SCHEMA,
        "status": STATUS,
        "case_id": CASE_ID,
        "source_role": "unseen_before_first_provider_answer",
        "doc_version": candidate.DOC_VERSION,
        "source_sha256": candidate.SOURCE_SHA256,
        "request_sha256": candidate.REQUEST_SHA256,
        "reference_manifest_sha256": candidate.REFERENCE_MANIFEST_SHA256,
        "model": MODEL,
        "endpoint": ENDPOINT,
        "params": PARAMS,
        "request_body_bytes": len(body),
        "input_token_reserve": INPUT_TOKEN_RESERVE,
        "deadline_seconds": DEADLINE_SECONDS,
        "price_checked_on": PRICE_CHECKED_ON,
        "price_source_url": PRICE_SOURCE_URL,
        "peak_input_cache_miss_usd_per_million": str(PEAK_INPUT_MISS_PER_M),
        "peak_output_usd_per_million": str(PEAK_OUTPUT_PER_M),
        "peak_reserve_estimate_usd": str(peak_estimate_usd()),
        "planned_usd_limit": str(PLANNED_USD_LIMIT),
        "account_hard_cap": False,
        "api_calls": 0,
    }


def prepare_frozen(output: Path = FROZEN) -> dict[str, Any]:
    """Create a final technical package once; this is not user authorization."""
    candidate.verify_frozen(candidate.FROZEN)
    request = candidate._source_package(SOURCE_STORE, OFFLINE_PACK)
    body = _body(request)
    inputs = {
        "source-store.json": _read(SOURCE_STORE),
        "offline/request.json": _read(OFFLINE_PACK / "request.json"),
        "offline/anchor-map.json": _read(OFFLINE_PACK / "anchor-map.json"),
        "offline/MANIFEST.json": _read(OFFLINE_PACK / "MANIFEST.json"),
        "provider-body.json": body,
    }
    output = Path(output)
    if output.is_symlink() or output.exists():
        raise ValueError("final frozen directory already exists; never overwrite")
    output.mkdir(parents=True, exist_ok=False)
    (output / "offline").mkdir()
    for name, data in inputs.items():
        (output / name).write_bytes(data)
    manifest = {
        **_fixed_fields(body),
        "files_sha256": {name: _sha(data) for name, data in inputs.items()},
        "code_sha256": {name: _sha(_read(ROOT / name)) for name in CODE_FILES},
    }
    (output / "MANIFEST.json").write_bytes(_bytes(manifest) + b"\n")
    verify_frozen(output)
    return manifest


def verify_frozen(folder: Path = FROZEN) -> dict[str, Any]:
    """Fail closed if source, code, budget, or the exact POST bytes changed."""
    folder = Path(folder)
    if (folder.is_symlink() or not folder.is_dir() or
            (folder / "offline").is_symlink()):
        raise ValueError("final frozen directory is missing or unsafe")
    manifest_bytes = _read(folder / "MANIFEST.json", max_bytes=100_000)
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("final manifest is malformed")
    files_sha = {name: _sha(_read(folder / name)) for name in PACK_FILES}
    code_sha = {name: _sha(_read(ROOT / name)) for name in CODE_FILES}
    request = candidate._source_package(folder / "source-store.json",
                                        folder / "offline")
    body = _body(request)
    expected = {**_fixed_fields(body), "files_sha256": files_sha,
                "code_sha256": code_sha}
    if manifest != expected:
        raise ValueError("final manifest, budget, files, or executing code changed")
    originals = {
        "source-store.json": SOURCE_STORE,
        "offline/request.json": OFFLINE_PACK / "request.json",
        "offline/anchor-map.json": OFFLINE_PACK / "anchor-map.json",
        "offline/MANIFEST.json": OFFLINE_PACK / "MANIFEST.json",
    }
    if any(_read(folder / name) != _read(path) for name, path in originals.items()):
        raise ValueError("final frozen copy differs from the saved source")
    if _read(folder / "provider-body.json", max_bytes=MAX_BODY_BYTES) != body:
        raise ValueError("final POST bytes differ from the verified source request")
    return {"status": STATUS, "case_id": CASE_ID, "body_bytes": len(body),
            "body_sha256": _sha(body), "manifest_sha256": _sha(manifest_bytes),
            "peak_reserve_estimate_usd": str(peak_estimate_usd()),
            "planned_usd_limit": str(PLANNED_USD_LIMIT),
            "api_calls": 0, "live_eligible_after_authorization": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FROZEN)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = verify_frozen(args.output) if args.verify else prepare_frozen(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
