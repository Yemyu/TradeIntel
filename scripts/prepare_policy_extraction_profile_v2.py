"""Prepare a versioned, offline provider profile after the first R2 truncation.

This does not call a provider and does not modify the frozen v7 packages.  It
keeps the same notice and field contract, but uses non-thinking JSON generation
with a larger output allowance so the answer has room to finish.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

from scripts.prepare_policy_extraction_pilot import ROOT, verify_package
from tradeintel_ai.announcement_extraction_pilot import (
    MAX_REQUEST_BYTES, encode_provider_request,
)


BASE_PACKAGES = {
    "r2": ROOT / "tmp/policy-extraction-dev-20260926/r2-v9",
    "d2": ROOT / "tmp/policy-extraction-dev-20260926/d2-v8",
    "h1": ROOT / "tmp/policy-extraction-dev-20260926/h1-v2",
    "h2": ROOT / "tmp/policy-extraction-dev-20260926/h2-v2",
}
PROFILE_ID = "policy-extraction-v2-no-thinking-r2-v9"
MODEL = "deepseek-flash"
MAX_OUTPUT_TOKENS = 8_192
PEAK_INPUT_PER_MILLION = 0.30
PEAK_OUTPUT_PER_MILLION = 1.20
MAX_INPUT_TOKENS_ESTIMATE = 24_000

def _write_private(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    os.chmod(path, 0o600)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile_messages(case: str) -> tuple[dict, dict]:
    base = BASE_PACKAGES[case]
    base_result = verify_package(base)
    old_request = json.loads((base / "request.json").read_text(encoding="utf-8"))
    messages = old_request["messages"]
    body = {
        "model": MODEL, "messages": messages,
        "thinking": {"type": "disabled"}, "reasoning_effort": "none",
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"}, "stream": False,
    }
    # Persisting JSON sorts keys. Canonicalize before hashing so the frozen
    # bytes are exactly what the next executor reconstructs and sends.
    body = json.loads(json.dumps(body, ensure_ascii=False, sort_keys=True))
    encoded = encode_provider_request(body, old_request)
    return ({"body": body, "encoded": encoded, "base": base_result,
             "base_manifest_sha256": _digest(base / "manifest.json"),
             "source_payload_sha256": hashlib.sha256(
                 messages[1]["content"].encode("utf-8")).hexdigest()},
            {"system_prompt_sha256": hashlib.sha256(
                messages[0]["content"].encode("utf-8")).hexdigest()})


def prepare(case: str, output: Path) -> dict:
    if case not in BASE_PACKAGES:
        raise ValueError("case must be r2, d2, h1 or h2")
    if output.exists():
        raise ValueError("profile output already exists; use a new version")
    output.mkdir(mode=0o700, parents=True)
    details, prompt_meta = _profile_messages(case)
    body = details["body"]
    encoded = details["encoded"]
    request = json.loads((BASE_PACKAGES[case] / "request.json").read_text(encoding="utf-8"))
    _write_private(output / "request.json", request)
    _write_private(output / "provider-body.json", body)
    profile = {
        "schema_version": PROFILE_ID, "case": case,
        "base_package": str(BASE_PACKAGES[case]),
        "base_manifest_sha256": details["base_manifest_sha256"],
        "source_payload_sha256": details["source_payload_sha256"],
        "system_prompt_sha256": prompt_meta["system_prompt_sha256"],
        "model": MODEL, "thinking": "disabled", "reasoning_effort": "none",
        "max_tokens": MAX_OUTPUT_TOKENS, "response_format": "json_object",
        "request_bytes": len(encoded), "provider_body_sha256": hashlib.sha256(encoded).hexdigest(),
        "estimated_peak_cost_usd": round(
            (MAX_INPUT_TOKENS_ESTIMATE * PEAK_INPUT_PER_MILLION +
             MAX_OUTPUT_TOKENS * PEAK_OUTPUT_PER_MILLION) / 1_000_000, 8),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "boundary": "新版配置实验；不覆盖v7首答，不构成模型成绩。",
    }
    _write_private(output / "profile.json", profile)
    manifest = {"schema_version": PROFILE_ID, "case": case,
                "files_sha256": {name: _digest(output / name) for name in
                                 ("request.json", "provider-body.json", "profile.json")},
                "prepare_code_sha256": _digest(Path(__file__))}
    _write_private(output / "manifest.json", manifest)
    return {"status": "prepared", "case": case, "profile": str(output),
            "request_bytes": len(encoded), "provider_body_sha256": profile["provider_body_sha256"],
            "estimated_peak_cost_usd": profile["estimated_peak_cost_usd"]}


def verify_profile(profile_dir: Path) -> dict:
    manifest = json.loads((profile_dir / "manifest.json").read_text(encoding="utf-8"))
    profile = json.loads((profile_dir / "profile.json").read_text(encoding="utf-8"))
    request = json.loads((profile_dir / "request.json").read_text(encoding="utf-8"))
    body = json.loads((profile_dir / "provider-body.json").read_text(encoding="utf-8"))
    case = profile.get("case")
    if case not in BASE_PACKAGES or manifest.get("schema_version") != PROFILE_ID \
            or manifest.get("case") != case \
            or manifest.get("prepare_code_sha256") != _digest(Path(__file__)) \
            or set(manifest.get("files_sha256", {})) != {
                "request.json", "provider-body.json", "profile.json"} \
            or any(manifest["files_sha256"][name] != _digest(profile_dir / name)
                   for name in manifest["files_sha256"]):
        raise ValueError("profile manifest changed or incomplete")
    details, _ = _profile_messages(case)
    encoded = encode_provider_request(body, {"messages": request["messages"]})
    original_request = json.loads((BASE_PACKAGES[case] / "request.json").read_text(encoding="utf-8"))
    if profile.get("schema_version") != PROFILE_ID or request != original_request \
            or body != details["body"] or request["messages"] != body["messages"] \
            or profile.get("base_manifest_sha256") != details["base_manifest_sha256"] \
            or profile.get("source_payload_sha256") != details["source_payload_sha256"] \
            or len(encoded) != profile.get("request_bytes") \
            or hashlib.sha256(encoded).hexdigest() != profile.get("provider_body_sha256") \
            or len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError("profile changed or exceeds request budget")
    return {"status": "verified", "case": case, "request_bytes": len(encoded),
            "provider_body_sha256": hashlib.sha256(encoded).hexdigest(),
            "thinking": body["thinking"], "max_tokens": body["max_tokens"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--case", choices=tuple(BASE_PACKAGES))
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify:
        if args.output:
            parser.error("--output is only used with --case")
        result = verify_profile(args.verify)
    else:
        if args.output is None:
            parser.error("--case requires --output")
        result = prepare(args.case, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
