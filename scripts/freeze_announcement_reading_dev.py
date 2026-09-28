"""Freeze one R2 reading-note development request without calling a provider.

The frozen pack carries the saved source and the existing v2 offline package.
It is a development question, not an unseen-announcement evaluation.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from scripts.prepare_announcement_reading_offline import verify as verify_offline


ROOT = Path(__file__).resolve().parents[1]
SOURCE_STORE = ROOT / "tmp/policy-extraction-dev-20260926/r2-v9/document-store.json"
OFFLINE_PACK = ROOT / "tmp/announcement-reading-dev-20260927/r2-v2"
FROZEN = ROOT / "evals/announcement_reading_v2/frozen/r2-dev-20260928-v1"
SOURCE_HTML = Path("evals/policy_extraction_v1/sources/fr-2025-23912.html")
REFERENCE = Path("evals/policy_extraction_v1/r2_reading_reference_v2.zh-CN.md")
CODE_FILES = (
    Path("src/tradeintel_ai/announcement_reading_suggestions.py"),
    Path("scripts/prepare_announcement_reading_offline.py"),
    Path("scripts/freeze_announcement_reading_dev.py"),
    Path("scripts/run_announcement_reading_dev_once.py"),
)
SCHEMA = "announcement-reading-r2-dev-freeze-v1"
MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"
PARAMS = {
    "thinking": {"type": "enabled"},
    "reasoning_effort": "high",
    "max_tokens": 12_288,
    "response_format": {"type": "json_object"},
    "stream": False,
}
MAX_BODY_BYTES = 30_000
INPUT_TOKEN_RESERVE = 30_000
PEAK_INPUT_USD_PER_M = Decimal("0.30")
PEAK_OUTPUT_USD_PER_M = Decimal("1.20")
PLANNED_USD_LIMIT = Decimal("0.03")
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
        raise ValueError(f"freeze input is not a bounded regular file: {path.name}")
    return path.read_bytes()


def _body(request: dict) -> bytes:
    if set(request) != {"schema_version", "doc_version", "source_sha256",
                        "request_sha256", "request_bytes", "messages"}:
        raise ValueError("offline request shape changed")
    messages = request["messages"]
    if (not isinstance(messages, list) or len(messages) != 2 or
            any(not isinstance(item, dict) or set(item) != {"role", "content"} or
                not isinstance(item["content"], str) for item in messages) or
            [item["role"] for item in messages] != ["system", "user"]):
        raise ValueError("offline messages changed")
    body = {"model": MODEL, "messages": messages, **PARAMS}
    encoded = _bytes(body)
    if len(encoded) > MAX_BODY_BYTES:
        raise ValueError("provider body exceeds the frozen byte limit")
    return encoded


def _budget() -> str:
    estimate = ((Decimal(INPUT_TOKEN_RESERVE) * PEAK_INPUT_USD_PER_M +
                 Decimal(PARAMS["max_tokens"]) * PEAK_OUTPUT_USD_PER_M) / Decimal(1_000_000))
    if estimate > PLANNED_USD_LIMIT:
        raise ValueError("reserved token estimate exceeds the local plan")
    return str(estimate)


def prepare_frozen(output: Path = FROZEN) -> dict:
    """Create a new pack exactly once; an interrupted pack is never overwritten."""
    verified = verify_offline(SOURCE_STORE, OFFLINE_PACK)
    source = _read(SOURCE_STORE)
    request = json.loads(_read(OFFLINE_PACK / "request.json"))
    body = _body(request)
    inputs = {
        "source-store.json": source,
        "offline/request.json": _read(OFFLINE_PACK / "request.json"),
        "offline/anchor-map.json": _read(OFFLINE_PACK / "anchor-map.json"),
        "offline/MANIFEST.json": _read(OFFLINE_PACK / "MANIFEST.json"),
        "provider-body.json": body,
    }
    official_sha = _sha(_read(ROOT / SOURCE_HTML))
    reference_sha = _sha(_read(ROOT / REFERENCE))
    code_sha = {str(name): _sha(_read(ROOT / name)) for name in CODE_FILES}
    output = Path(output)
    if output.is_symlink() or output.exists():
        raise ValueError("frozen directory already exists; do not overwrite")
    output.mkdir(parents=True, exist_ok=False)
    (output / "offline").mkdir()
    for name in PACK_FILES:
        (output / name).write_bytes(inputs[name])
    manifest = {
        "schema_version": SCHEMA,
        "status": "frozen_offline_not_authorized_for_provider",
        "case_id": "r2-reading-dev",
        "source_role": "seen_development_only",
        "doc_version": verified["doc_version"],
        "source_sha256": request["source_sha256"],
        "model": MODEL,
        "endpoint": ENDPOINT,
        "params": PARAMS,
        "request_body_bytes": len(body),
        "input_token_reserve": INPUT_TOKEN_RESERVE,
        "peak_input_usd_per_m": str(PEAK_INPUT_USD_PER_M),
        "peak_output_usd_per_m": str(PEAK_OUTPUT_USD_PER_M),
        "peak_estimate_usd": _budget(),
        "planned_usd_limit": str(PLANNED_USD_LIMIT),
        "account_hard_cap": False,
        "files_sha256": {name: _sha(inputs[name]) for name in PACK_FILES},
        "source_html_sha256": official_sha,
        "reference_sha256": reference_sha,
        "code_sha256": code_sha,
        "api_calls": 0,
    }
    (output / "MANIFEST.json").write_bytes(_bytes(manifest) + b"\n")
    verify_frozen(ROOT, output)
    return manifest


def verify_frozen(root: Path = ROOT, folder: Path = FROZEN) -> dict:
    """Rebuild the precise POST bytes and refuse changed data, code, or rules."""
    root, folder = Path(root), Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("frozen directory is missing or unsafe")
    manifest = json.loads(_read(folder / "MANIFEST.json", max_bytes=100_000))
    if (manifest.get("schema_version") != SCHEMA or
            manifest.get("status") != "frozen_offline_not_authorized_for_provider" or
            manifest.get("case_id") != "r2-reading-dev" or
            manifest.get("source_role") != "seen_development_only" or
            manifest.get("model") != MODEL or manifest.get("endpoint") != ENDPOINT or
            manifest.get("params") != PARAMS or manifest.get("api_calls") != 0 or
            manifest.get("account_hard_cap") is not False or
            manifest.get("input_token_reserve") != INPUT_TOKEN_RESERVE or
            manifest.get("peak_input_usd_per_m") != str(PEAK_INPUT_USD_PER_M) or
            manifest.get("peak_output_usd_per_m") != str(PEAK_OUTPUT_USD_PER_M) or
            manifest.get("peak_estimate_usd") != _budget() or
            manifest.get("planned_usd_limit") != str(PLANNED_USD_LIMIT)):
        raise ValueError("frozen request rules differ from the decision")
    if manifest.get("files_sha256") != {
            name: _sha(_read(folder / name)) for name in PACK_FILES}:
        raise ValueError("frozen file differs from manifest")
    if (manifest.get("source_html_sha256") != _sha(_read(root / SOURCE_HTML)) or
            manifest.get("reference_sha256") != _sha(_read(root / REFERENCE)) or
            manifest.get("code_sha256") != {
                str(name): _sha(_read(root / name)) for name in CODE_FILES}):
        raise ValueError("official source, reference, or code changed after freeze")
    result = verify_offline(folder / "source-store.json", folder / "offline")
    request = json.loads(_read(folder / "offline/request.json"))
    body = _body(request)
    if (manifest.get("doc_version") != result["doc_version"] or
            manifest.get("source_sha256") != request["source_sha256"] or
            manifest.get("request_body_bytes") != len(body) or
            _read(folder / "provider-body.json") != body):
        raise ValueError("frozen provider body does not match the saved source")
    return {"status": "verified_offline", "case_id": manifest["case_id"],
            "body_bytes": len(body), "body_sha256": _sha(body),
            "manifest_sha256": _sha(_read(folder / "MANIFEST.json")),
            "peak_estimate_usd": manifest["peak_estimate_usd"], "api_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FROZEN)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = verify_frozen(ROOT, args.output) if args.verify else prepare_frozen(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
