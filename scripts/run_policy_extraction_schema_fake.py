"""Run an offline fake tool call through the structured extraction route.

The fake response exercises the same parser and ``adapt_suggestion`` gate as a
provider response.  It never reads an API key or opens a network connection.
Each output directory is single-use so a partial/unknown run cannot be silently
replayed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from scripts.prepare_policy_extraction_schema_request import verify_profile
from tradeintel_ai.announcement_extraction_pilot import adapt_suggestion
from tradeintel_ai.announcement_extraction_schema import (
    FUNCTION_NAME,
    normalise_transport_answer,
    parse_tool_response,
)
from tradeintel_ai.policy_candidates import REQUIRED_FIELDS

MAX_RESPONSE_BYTES = 1_000_000
SCENARIOS = ("valid", "wrong_function", "multiple_calls", "duplicate_keys",
             "truncated", "oversize")


def _write(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".schema-fake-", dir=path.parent)
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


def _write_bytes(path: Path, value: bytes) -> str:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if path.exists():
            path.unlink()
        raise
    return hashlib.sha256(value).hexdigest()


def _unknown_arguments(version: str) -> dict[str, Any]:
    return {
        "doc_version": version,
        "fields": [
            {"field": name, "status": "unknown",
             "value": {"present": False, "data": ""},
             "reason": "fake 响应未提供足够证据", "evidence": []}
            for name in REQUIRED_FIELDS
        ],
    }


def _fake_response(profile_record: dict[str, Any], doc_version: str,
                   scenario: str) -> bytes:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown fake scenario: {scenario}")
    args = _unknown_arguments(doc_version)
    function_name = FUNCTION_NAME if scenario != "wrong_function" else "other_function"
    call = {"id": "fake-call-1", "type": "function",
            "function": {"name": function_name,
                          "arguments": json.dumps(args, ensure_ascii=False)}}
    calls = [call]
    finish_reason = "tool_calls"
    content = ""
    if scenario == "multiple_calls":
        calls.append({"id": "fake-call-2", "type": "function",
                      "function": {"name": FUNCTION_NAME,
                                    "arguments": json.dumps(args, ensure_ascii=False)}})
    elif scenario == "duplicate_keys":
        call["function"]["arguments"] = (
            '{"doc_version":"' + doc_version + '","doc_version":"tampered",'
            '"fields":[]}')
    elif scenario == "truncated":
        finish_reason = "length"
        calls = []
    elif scenario == "oversize":
        return b"{" + (b"x" * MAX_RESPONSE_BYTES) + b"}"
    return json.dumps({
        "id": "offline-fake-schema-call",
        "model": profile_record["model"],
        "choices": [{"finish_reason": finish_reason, "message": {
            "content": content, "tool_calls": calls}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def run(profile_dir: Path, output: Path, *, scenario: str = "valid") -> dict[str, Any]:
    profile = verify_profile(profile_dir)
    profile_record = json.loads((profile_dir / "profile.json").read_text(encoding="utf-8"))
    output = output.resolve()
    if output.exists():
        raise ValueError("fake output already exists; never overwrite a prior run")
    base_package = Path(json.loads((profile_dir / "profile.json").read_text())["base_package"])
    store = json.loads((base_package / "document-store.json").read_text(encoding="utf-8"))
    output.mkdir(mode=0o700, parents=True)
    version = profile["case"]
    doc_version = json.loads((profile_dir / "request.json").read_text(encoding="utf-8"))["doc_version"]
    raw = _fake_response(profile_record, doc_version, scenario)
    started = {
        "schema_version": "policy-extraction-schema-fake-run-v1",
        "status": "started",
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": str(profile_dir.resolve()),
        "profile_sha256": hashlib.sha256((profile_dir / "manifest.json").read_bytes()).hexdigest(),
        "case": version,
        "model": profile_record["model"],
        "scenario": scenario,
        "api_calls": 0,
    }
    _write(output / "ledger.json", started)
    if len(raw) > MAX_RESPONSE_BYTES:
        started.update(status="blocked_output_budget", response_bytes=len(raw),
                       finished_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       validation_error_type="ResponseTooLarge")
        _write(output / "ledger.json", started)
        return {"status": started["status"], "output": str(output),
                "api_calls": 0, "response_bytes": len(raw)}
    raw_hash = _write_bytes(output / "response.json", raw)
    started.update(status="raw_saved", response_sha256=raw_hash, response_bytes=len(raw))
    _write(output / "ledger.json", started)
    try:
        parsed = parse_tool_response(raw)
        answer = normalise_transport_answer(parsed["arguments"])
        draft = adapt_suggestion(answer, store, doc_version)
    except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
        started.update(status="invalid_answer", finished_at_utc=datetime.now(timezone.utc).isoformat(
            timespec="seconds"), validation_error_type=type(exc).__name__,
                       validation_error=str(exc)[:200])
        _write(output / "ledger.json", started)
        return {"status": started["status"], "output": str(output),
                "api_calls": 0, "response_sha256": raw_hash,
                "validation_error_type": type(exc).__name__}
    _write(output / "draft.json", draft)
    started.update(status="review_only", finished_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   draft_status=draft["status"], response_model=parsed.get("model"),
                   finish_reason=parsed["finish_reason"])
    _write(output / "ledger.json", started)
    return {"status": started["status"], "output": str(output),
            "draft_status": draft["status"], "response_sha256": raw_hash,
            "api_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="valid")
    args = parser.parse_args()
    print(json.dumps(run(args.profile, args.output, scenario=args.scenario),
                     ensure_ascii=False, indent=2))
