"""Prepare and verify the FR2026-19516 reading pilot without contacting a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.prepare_announcement_reading_offline import verify as verify_offline


ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "fr-2026-19516-reading-unseen-v1"
CASE = ROOT / "evals/announcement_reading_v2/unseen-20260928-screen/2026-19516"
SOURCE_STORE = CASE / "source-store.json"
OFFLINE_PACK = CASE / "offline-pack"
REFERENCE_MANIFEST = CASE / "REFERENCE_MANIFEST.json"
FROZEN = ROOT / "evals/announcement_reading_v2/frozen/fr-2026-19516-unseen-v1"

# Anchors set before a model answer existed. Never re-compute these from a
# potentially edited reference file and then accept the new values.
REFERENCE_MANIFEST_SHA256 = "25c2fb7e123128956bfd1e7e0ce8e41496abd294e012cd43bfaca23f27af4895"
REQUEST_SHA256 = "0ebde1623741467e34ef7cc7f2c9ce06046a4a9f0459e719129c3e58f57e8a39"
DOC_VERSION = "docver-4856274e93216a5e"
SOURCE_SHA256 = "8ca8e250cec45f44dafb77b28d4e243db5439072221878ead7b85f645e5c06e0"
SYSTEM_PROMPT_SHA256 = "38ea5388f02ed4b64f9ac6afe6ebc3f0a4f25e1af29a835cfdf39f42d7e992f5"

# This is an offline candidate matching the former development setting. A
# separate decision must fix current price and budget before live release.
MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"
PARAMS = {
    "thinking": {"type": "enabled"},
    "reasoning_effort": "high",
    "max_tokens": 12_288,
    "response_format": {"type": "json_object"},
    "stream": False,
}
SCHEMA = "announcement-reading-unseen-freeze-v1"
MAX_BODY_BYTES = 30_000
INPUT_TOKEN_RESERVE = 30_000
DEADLINE_SECONDS = 120
CODE_FILES = (
    "scripts/freeze_announcement_reading_unseen.py",
    "scripts/run_announcement_reading_unseen_once.py",
    "scripts/prepare_announcement_reading_offline.py",
    "scripts/run_trade_v3_canary.py",
    "src/tradeintel_ai/announcement_reading_suggestions.py",
    "src/tradeintel_ai/policy_documents.py",
    "src/tradeintel_ai/local_provider_config.py",
)
PACK_FILES = (
    "source-store.json", "offline/request.json", "offline/anchor-map.json",
    "offline/MANIFEST.json", "provider-body.json",
)


def _bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, *, max_bytes: int = 1_000_000) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError(f"unseen reading input is missing or unsafe: {path.name}")
    return path.read_bytes()


def _reference() -> dict[str, Any]:
    original = _read(REFERENCE_MANIFEST, max_bytes=100_000)
    if _sha(original) != REFERENCE_MANIFEST_SHA256:
        raise ValueError("pre-answer reference manifest changed")
    manifest = json.loads(original)
    if (manifest.get("case") != "FR2026-19516" or
            manifest.get("doc_version") != DOC_VERSION or
            manifest.get("request_sha256") != REQUEST_SHA256 or
            manifest.get("system_prompt_sha256") != SYSTEM_PROMPT_SHA256 or
            manifest.get("model_answer_status") != "not_generated_in_this_phase" or
            len(manifest.get("critical_fact_ids", [])) != 13 or
            not isinstance(manifest.get("files"), dict) or
            len(manifest["files"]) != 13):
        raise ValueError("pre-answer reference identity changed")
    for name, expected in manifest["files"].items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise ValueError("reference file map is malformed")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("reference path leaves the project")
        if _sha(_read(ROOT / relative)) != expected:
            raise ValueError(f"reference-bound input changed: {name}")
    return manifest


def _source_package(store_path: Path, offline_path: Path) -> dict[str, Any]:
    reference = _reference()
    verified = verify_offline(store_path, offline_path)
    request = json.loads(_read(offline_path / "request.json", max_bytes=100_000))
    if (verified != {"status": "verified_offline", "doc_version": DOC_VERSION,
                     "request_bytes": 27_615, "anchor_count": 54, "api_calls": 0} or
            request.get("request_sha256") != REQUEST_SHA256 or
            request.get("doc_version") != DOC_VERSION or
            request.get("source_sha256") != SOURCE_SHA256 or
            reference["request_bytes"] != 27_615):
        raise ValueError("unseen source package differs from its pre-answer reference")
    messages = request.get("messages")
    if (not isinstance(messages, list) or len(messages) != 2 or
            [item.get("role") for item in messages if isinstance(item, dict)] !=
            ["system", "user"] or
            any(not isinstance(item, dict) or set(item) != {"role", "content"} or
                not isinstance(item["content"], str) for item in messages) or
            _sha(messages[0]["content"].encode("utf-8")) != SYSTEM_PROMPT_SHA256):
        raise ValueError("unseen model messages differ from the approved request")
    user = json.loads(messages[1]["content"])
    if (set(user) != {"schema_version", "doc_version", "source_sha256",
                     "numbered_source_text"} or
            user["doc_version"] != DOC_VERSION or
            user["source_sha256"] != SOURCE_SHA256):
        raise ValueError("model message contains unexpected case material")
    return request


def _body(request: dict[str, Any]) -> bytes:
    body = _bytes({"model": MODEL, "messages": request["messages"], **PARAMS})
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("provider body exceeds the independent byte limit")
    return body


def prepare_frozen(output: Path = FROZEN) -> dict[str, Any]:
    """Create a candidate package once. No live release or fee is implied."""
    request = _source_package(SOURCE_STORE, OFFLINE_PACK)
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
        raise ValueError("unseen frozen directory already exists; never overwrite")
    output.mkdir(parents=True, exist_ok=False)
    (output / "offline").mkdir()
    for name, data in inputs.items():
        (output / name).write_bytes(data)
    manifest = {
        "schema_version": SCHEMA,
        "status": "candidate_offline_no_live_release",
        "case_id": CASE_ID,
        "source_role": "unseen_before_first_provider_answer",
        "doc_version": DOC_VERSION,
        "source_sha256": SOURCE_SHA256,
        "request_sha256": REQUEST_SHA256,
        "reference_manifest_sha256": REFERENCE_MANIFEST_SHA256,
        "model": MODEL,
        "endpoint": ENDPOINT,
        "params": PARAMS,
        "request_body_bytes": len(body),
        "input_token_reserve": INPUT_TOKEN_RESERVE,
        "deadline_seconds": DEADLINE_SECONDS,
        "planned_usd_limit": None,
        "account_hard_cap": False,
        "api_calls": 0,
        "files_sha256": {name: _sha(data) for name, data in inputs.items()},
        "code_sha256": {name: _sha(_read(ROOT / name)) for name in CODE_FILES},
    }
    (output / "MANIFEST.json").write_bytes(_bytes(manifest) + b"\n")
    verify_frozen(output)
    return manifest


def verify_frozen(folder: Path = FROZEN) -> dict[str, Any]:
    folder = Path(folder)
    if (folder.is_symlink() or not folder.is_dir() or
            (folder / "offline").is_symlink()):
        raise ValueError("unseen frozen directory is missing or unsafe")
    manifest_bytes = _read(folder / "MANIFEST.json", max_bytes=100_000)
    manifest = json.loads(manifest_bytes)
    expected = {
        "schema_version": SCHEMA,
        "status": "candidate_offline_no_live_release",
        "case_id": CASE_ID,
        "source_role": "unseen_before_first_provider_answer",
        "doc_version": DOC_VERSION,
        "source_sha256": SOURCE_SHA256,
        "request_sha256": REQUEST_SHA256,
        "reference_manifest_sha256": REFERENCE_MANIFEST_SHA256,
        "model": MODEL,
        "endpoint": ENDPOINT,
        "params": PARAMS,
        "input_token_reserve": INPUT_TOKEN_RESERVE,
        "deadline_seconds": DEADLINE_SECONDS,
        "planned_usd_limit": None,
        "account_hard_cap": False,
        "api_calls": 0,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("unseen frozen rules differ from the candidate plan")
    if (manifest.get("files_sha256") !=
            {name: _sha(_read(folder / name)) for name in PACK_FILES} or
            manifest.get("code_sha256") !=
            {name: _sha(_read(ROOT / name)) for name in CODE_FILES}):
        raise ValueError("unseen frozen files or executing code changed")
    original = {
        "source-store.json": SOURCE_STORE,
        "offline/request.json": OFFLINE_PACK / "request.json",
        "offline/anchor-map.json": OFFLINE_PACK / "anchor-map.json",
        "offline/MANIFEST.json": OFFLINE_PACK / "MANIFEST.json",
    }
    if any(_read(folder / name) != _read(path) for name, path in original.items()):
        raise ValueError("unseen frozen copy differs from the saved source")
    request = _source_package(folder / "source-store.json", folder / "offline")
    body = _body(request)
    if (manifest.get("request_body_bytes") != len(body) or
            _read(folder / "provider-body.json", max_bytes=MAX_BODY_BYTES) != body):
        raise ValueError("unseen provider body is not the approved source request")
    return {"status": "verified_offline_candidate", "case_id": CASE_ID,
            "body_bytes": len(body), "body_sha256": _sha(body),
            "manifest_sha256": _sha(manifest_bytes), "api_calls": 0,
            "live_released": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FROZEN)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = verify_frozen(args.output) if args.verify else prepare_frozen(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
