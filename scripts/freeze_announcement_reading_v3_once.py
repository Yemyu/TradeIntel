"""Freeze/verify the FR2026-19517 v3 POST without contacting a provider.

The default artifact is an offline candidate. A separate explicit release
decision is required before a live-eligible copy may be created.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.prepare_announcement_reading_v3_offline import verify as verify_offline
from tradeintel_ai.announcement_reading_v3 import CHECK_IDS, MAX_POST_BYTES


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "evals/announcement_reading_v3/unseen-20260929-screen/2026-19517"
SOURCE_STORE = CASE / "source-store.json"
OFFLINE_PACK = CASE / "offline-pack"
REFERENCE = CASE / "reference.zh-CN.md"
REFERENCE_MANIFEST = CASE / "REFERENCE_MANIFEST.json"
REFERENCE_MANIFEST_SHA256 = "ca24dcf4fee87e56f05278f5b494e6a70d0524215cce7dd6b73f2e7dede16bea"
CASE_ID = "fr-2026-19517-reading-unseen-v3"
DOC_VERSION = "docver-e95b289ffe15d6cc"
SOURCE_SHA256 = "50ed2786ae6044f2f6bba64c10551b753eae671c2ef8dd3da0fb3facec13ce64"
REQUEST_SHA256 = "616593581ed7bf1661c4ae35d7ddf303f3db59840cd3c02e27ea65fbaaa1dc28"
FROZEN_CANDIDATE = ROOT / "evals/announcement_reading_v3/frozen/fr-2026-19517-candidate-v1"
FROZEN_LIVE = ROOT / "evals/announcement_reading_v3/frozen/fr-2026-19517-live-v1"
LEDGER_RELATIVE = ".local/experiments/announcement-reading-v3/fr-2026-19517-unseen-v1"
SCHEMA = "announcement-reading-v3-one-attempt-freeze-v1"
CANDIDATE_STATUS = "offline_candidate_not_released"
LIVE_STATUS = "live_eligible_after_separate_authorization"
MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"
PARAMS = {"thinking": {"type": "enabled"}, "reasoning_effort": "high",
          "max_tokens": 20_000, "response_format": {"type": "json_object"},
          "stream": False}
INPUT_TOKEN_RESERVE = 40_000
DEADLINE_SECONDS = 180
PRICE_CHECKED_ON = "2026-09-29"
PRICE_SOURCE_URL = "https://api-docs.deepseek.com/quick_start/pricing/"
PEAK_INPUT_MISS_PER_M = Decimal("0.30")
PEAK_OUTPUT_PER_M = Decimal("1.20")
PLANNED_USD_LIMIT = Decimal("0.04")
PACK_FILES = (
    "source-store.json", "offline/request.json", "offline/anchor-map.json",
    "offline/MANIFEST.json", "reference/reference.zh-CN.md",
    "reference/REFERENCE_MANIFEST.json", "provider-body.json",
)
CODE_FILES = (
    "scripts/freeze_announcement_reading_v3_once.py",
    "scripts/run_announcement_reading_v3_once.py",
    "scripts/prepare_announcement_reading_v3_offline.py",
    "src/tradeintel_ai/announcement_reading_v3.py",
    "src/tradeintel_ai/policy_documents.py",
    "src/tradeintel_ai/local_provider_config.py",
    "scripts/run_trade_v3_canary.py",
)


def _bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, *, max_bytes: int = 1_000_000) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError(f"v3 frozen input is missing or unsafe: {path.name}")
    return path.read_bytes()


def peak_estimate_usd(input_tokens: int = INPUT_TOKEN_RESERVE,
                      output_tokens: int = PARAMS["max_tokens"]) -> Decimal:
    if (type(input_tokens) is not int or type(output_tokens) is not int or
            input_tokens < 0 or output_tokens < 0):
        raise ValueError("token counts must be nonnegative integers")
    return ((Decimal(input_tokens) * PEAK_INPUT_MISS_PER_M +
             Decimal(output_tokens) * PEAK_OUTPUT_PER_M) / Decimal(1_000_000))


def _reference() -> dict[str, Any]:
    original = _read(REFERENCE_MANIFEST, max_bytes=100_000)
    if _sha(original) != REFERENCE_MANIFEST_SHA256:
        raise ValueError("v3 pre-answer reference manifest changed")
    manifest = json.loads(original)
    if (manifest.get("schema") != "announcement-reading-v3-pre-answer-reference-v1" or
            manifest.get("case") != "FR2026-19517" or
            manifest.get("doc_version") != DOC_VERSION or
            manifest.get("source_sha256") != SOURCE_SHA256 or
            manifest.get("request_sha256") != REQUEST_SHA256 or
            manifest.get("request_bytes") != 7438 or
            manifest.get("check_ids") != list(CHECK_IDS) or
            manifest.get("critical_fact_ids") != [f"F{i:02d}" for i in range(1, 12)] or
            manifest.get("model_answer_status") != "not_generated_for_this_case" or
            manifest.get("provider_authorized") is not False or
            not isinstance(manifest.get("files"), dict)):
        raise ValueError("v3 pre-answer reference identity changed")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if (not isinstance(name, str) or relative.is_absolute() or
                ".." in relative.parts or not relative.parts or
                not isinstance(expected, str) or
                _sha(_read(ROOT / relative)) != expected):
            raise ValueError(f"v3 reference-bound file changed: {name}")
    return manifest


def _source_request(store_path: Path, pack_path: Path) -> dict[str, Any]:
    _reference()
    verified = verify_offline(store_path, pack_path)
    request = json.loads(_read(pack_path / "request.json", max_bytes=100_000))
    if (verified.get("status") != "verified_offline" or
            verified.get("request_bytes") != 7438 or
            verified.get("anchor_count") != 21 or
            request.get("doc_version") != DOC_VERSION or
            request.get("source_sha256") != SOURCE_SHA256 or
            request.get("request_sha256") != REQUEST_SHA256 or
            request.get("check_ids") != list(CHECK_IDS)):
        raise ValueError("v3 source package differs from the pre-answer reference")
    messages = request.get("messages")
    if (not isinstance(messages, list) or len(messages) != 2 or
            any(not isinstance(item, dict) or set(item) != {"role", "content"} or
                not isinstance(item["content"], str) for item in messages) or
            [item["role"] for item in messages] != ["system", "user"]):
        raise ValueError("v3 message sequence is invalid")
    user = json.loads(messages[1]["content"])
    if (not isinstance(user, dict) or set(user) != {
            "schema_version", "doc_version", "source_sha256", "numbered_source_text"} or
            user["doc_version"] != DOC_VERSION or
            user["source_sha256"] != SOURCE_SHA256):
        raise ValueError("v3 provider message contains unexpected material")
    return request


def _body(request: dict[str, Any]) -> bytes:
    body = _bytes({"model": MODEL, "messages": request["messages"], **PARAMS})
    if len(body) > MAX_POST_BYTES:
        raise ValueError("complete v3 provider POST exceeds 34 KB; do not trim source")
    return body


def _fixed_fields(body: bytes, *, live_release: bool,
                  authorization_reference: str) -> dict[str, Any]:
    if peak_estimate_usd() > PLANNED_USD_LIMIT:
        raise ValueError("peak reserve estimate exceeds planned budget")
    if live_release and (not isinstance(authorization_reference, str) or
                         not authorization_reference.strip()):
        raise ValueError("live release requires a separate authorization reference")
    if not live_release and authorization_reference != "":
        raise ValueError("offline candidate cannot carry authorization")
    return {
        "schema_version": SCHEMA,
        "status": LIVE_STATUS if live_release else CANDIDATE_STATUS,
        "case_id": CASE_ID,
        "source_role": "unseen_before_first_provider_answer",
        "doc_version": DOC_VERSION,
        "source_sha256": SOURCE_SHA256,
        "request_sha256": REQUEST_SHA256,
        "reference_manifest_sha256": REFERENCE_MANIFEST_SHA256,
        "model": MODEL, "endpoint": ENDPOINT, "params": PARAMS,
        "request_body_bytes": len(body), "request_body_sha256": _sha(body),
        "input_token_reserve": INPUT_TOKEN_RESERVE,
        "output_token_reserve": PARAMS["max_tokens"],
        "deadline_seconds": DEADLINE_SECONDS,
        "price_checked_on": PRICE_CHECKED_ON,
        "price_source_url": PRICE_SOURCE_URL,
        "peak_input_cache_miss_usd_per_million": str(PEAK_INPUT_MISS_PER_M),
        "peak_output_usd_per_million": str(PEAK_OUTPUT_PER_M),
        "peak_reserve_estimate_usd": str(peak_estimate_usd()),
        "planned_usd_limit": str(PLANNED_USD_LIMIT),
        "account_hard_cap": False,
        "ledger_relative": LEDGER_RELATIVE,
        "authorization_reference": authorization_reference,
        "api_calls": 0,
    }


def prepare_frozen(output: Path = FROZEN_CANDIDATE, *, live_release: bool = False,
                   authorization_reference: str = "") -> dict[str, Any]:
    """Write a new immutable-by-convention package; never reuse an old path."""
    request = _source_request(SOURCE_STORE, OFFLINE_PACK)
    body = _body(request)
    inputs = {
        "source-store.json": _read(SOURCE_STORE),
        "offline/request.json": _read(OFFLINE_PACK / "request.json"),
        "offline/anchor-map.json": _read(OFFLINE_PACK / "anchor-map.json"),
        "offline/MANIFEST.json": _read(OFFLINE_PACK / "MANIFEST.json"),
        "reference/reference.zh-CN.md": _read(REFERENCE, max_bytes=100_000),
        "reference/REFERENCE_MANIFEST.json": _read(REFERENCE_MANIFEST, max_bytes=100_000),
        "provider-body.json": body,
    }
    fields = _fixed_fields(body, live_release=live_release,
                           authorization_reference=authorization_reference)
    output = Path(output)
    if output.is_symlink() or output.exists():
        raise ValueError("v3 frozen directory already exists; never overwrite")
    output.mkdir(parents=True, exist_ok=False)
    (output / "offline").mkdir()
    (output / "reference").mkdir()
    for name, data in inputs.items():
        (output / name).write_bytes(data)
    manifest = {
        **fields,
        "files_sha256": {name: _sha(data) for name, data in inputs.items()},
        "code_sha256": {name: _sha(_read(ROOT / name)) for name in CODE_FILES},
    }
    (output / "MANIFEST.json").write_bytes(_bytes(manifest) + b"\n")
    verify_frozen(output)
    return manifest


def verify_frozen(folder: Path = FROZEN_CANDIDATE) -> dict[str, Any]:
    folder = Path(folder)
    if (folder.is_symlink() or not folder.is_dir() or
            (folder / "offline").is_symlink() or
            (folder / "reference").is_symlink()):
        raise ValueError("v3 frozen directory is missing or unsafe")
    manifest_bytes = _read(folder / "MANIFEST.json", max_bytes=100_000)
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict) or manifest.get("status") not in {
            CANDIDATE_STATUS, LIVE_STATUS}:
        raise ValueError("v3 frozen manifest status is invalid")
    live_release = manifest["status"] == LIVE_STATUS
    body = _body(_source_request(folder / "source-store.json", folder / "offline"))
    expected = {
        **_fixed_fields(body, live_release=live_release,
                        authorization_reference=manifest.get("authorization_reference")),
        "files_sha256": {name: _sha(_read(folder / name)) for name in PACK_FILES},
        "code_sha256": {name: _sha(_read(ROOT / name)) for name in CODE_FILES},
    }
    if manifest != expected:
        raise ValueError("v3 manifest, budget, files or executing code changed")
    originals = {
        "source-store.json": SOURCE_STORE,
        "offline/request.json": OFFLINE_PACK / "request.json",
        "offline/anchor-map.json": OFFLINE_PACK / "anchor-map.json",
        "offline/MANIFEST.json": OFFLINE_PACK / "MANIFEST.json",
        "reference/reference.zh-CN.md": REFERENCE,
        "reference/REFERENCE_MANIFEST.json": REFERENCE_MANIFEST,
    }
    if any(_read(folder / name) != _read(path) for name, path in originals.items()):
        raise ValueError("v3 frozen copy differs from the saved source or reference")
    if _read(folder / "provider-body.json", max_bytes=MAX_POST_BYTES) != body:
        raise ValueError("v3 POST bytes differ from the verified request")
    return {
        "status": manifest["status"], "case_id": CASE_ID,
        "body_bytes": len(body), "body_sha256": _sha(body),
        "manifest_sha256": _sha(manifest_bytes),
        "peak_reserve_estimate_usd": str(peak_estimate_usd()),
        "planned_usd_limit": str(PLANNED_USD_LIMIT),
        "live_eligible_after_authorization": live_release,
        "api_calls": 0,
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=FROZEN_CANDIDATE)
    cli.add_argument("--verify", action="store_true")
    args = cli.parse_args()
    result = verify_frozen(args.output) if args.verify else prepare_frozen(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
