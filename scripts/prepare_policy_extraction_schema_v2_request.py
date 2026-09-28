"""Prepare and verify the v2 structured extraction request offline.

The v2 contract keeps the frozen v1 profile intact and adds the field-aware
raw-text/JSON-text rule.  This command never reads provider credentials or
contacts a model service.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from scripts.prepare_policy_extraction_pilot import ROOT, verify_package
from tradeintel_ai.announcement_extraction_schema import function_definition, schema_hash
from tradeintel_ai.announcement_extraction_transport_v2 import (
    CONTRACT_VERSION,
    prepare_schema_request_v2,
)


CODE_FILES = (
    "src/tradeintel_ai/announcement_extraction_pilot.py",
    "src/tradeintel_ai/announcement_extraction_schema.py",
    "src/tradeintel_ai/announcement_extraction_transport_v2.py",
    "src/tradeintel_ai/policy_candidates.py",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"profile file missing or unsafe: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"profile file is not an object: {path.name}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    os.chmod(path, 0o600)


def _details(base_package: Path, *, model: str, strict: bool) -> dict[str, Any]:
    base = verify_package(base_package)
    store = _read(base_package / "document-store.json")
    prepared = prepare_schema_request_v2(store, base["doc_version"], model=model, strict=strict)
    body = prepared["body"]
    return {
        "base_package": str(base_package.resolve()),
        "base_manifest_sha256": _digest(base_package / "manifest.json"),
        "case": _read(base_package / "manifest.json")["case"],
        "doc_version": base["doc_version"],
        "body": body,
        "body_sha256": prepared["body_sha256"],
        "body_bytes": prepared["body_bytes"],
        "input_request_sha256": prepared["input_request_sha256"],
        "input_request_bytes": prepared["input_request_bytes"],
        "input_token_estimate": prepared["input_token_estimate"],
        "input_token_limit": prepared["input_token_limit"],
        "body_limit": prepared["body_limit"],
        "model": model,
        "strict": strict,
        "endpoint_profile": prepared["endpoint_profile"],
        "endpoint": prepared["endpoint"],
        "schema_sha256": schema_hash(function_definition(strict=strict)),
    }


def prepare(base_package: Path, output: Path, *, model: str,
            strict: bool = True) -> dict[str, Any]:
    base_package, output = base_package.resolve(), output.resolve()
    if output.exists():
        raise ValueError("profile output already exists; choose a new directory")
    details = _details(base_package, model=model, strict=strict)
    output.mkdir(mode=0o700, parents=True)
    body = details.pop("body")
    _write(output / "provider-body.json", body)
    _write(output / "request.json", {
        "schema_version": CONTRACT_VERSION,
        "case": details["case"],
        "doc_version": details["doc_version"],
        "messages": body["messages"],
        "input_request_sha256": details["input_request_sha256"],
        "input_request_bytes": details["input_request_bytes"],
    })
    profile = {
        "schema_version": CONTRACT_VERSION,
        "profile_kind": "structured-tool-request",
        **details,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "boundary": "offline structured transport v2; review_only only; no provider call",
    }
    _write(output / "profile.json", profile)
    files = ("provider-body.json", "request.json", "profile.json")
    _write(output / "manifest.json", {
        "schema_version": CONTRACT_VERSION,
        "profile_kind": "structured-tool-request",
        "files_sha256": {name: _digest(output / name) for name in files},
        "code_sha256": {name: _digest(ROOT / name) for name in CODE_FILES},
        "body_sha256": details["body_sha256"],
        "schema_sha256": details["schema_sha256"],
    })
    return {"status": "prepared", "profile": str(output),
            "case": profile["case"], "body_bytes": profile["body_bytes"],
            "input_token_estimate": profile["input_token_estimate"],
            "body_sha256": profile["body_sha256"],
            "schema_sha256": profile["schema_sha256"]}


def verify_profile(profile_dir: Path) -> dict[str, Any]:
    profile_dir = profile_dir.resolve()
    manifest = _read(profile_dir / "manifest.json")
    profile = _read(profile_dir / "profile.json")
    request = _read(profile_dir / "request.json")
    body = _read(profile_dir / "provider-body.json")
    if manifest.get("schema_version") != CONTRACT_VERSION \
            or profile.get("schema_version") != CONTRACT_VERSION \
            or set(manifest.get("files_sha256", {})) != {
                "provider-body.json", "request.json", "profile.json"
            } \
            or set(manifest.get("code_sha256", {})) != set(CODE_FILES):
        raise ValueError("v2 structured profile manifest is incomplete")
    if any(manifest["files_sha256"][name] != _digest(profile_dir / name)
           for name in manifest["files_sha256"]):
        raise ValueError("v2 structured profile file changed")
    if any(manifest["code_sha256"][name] != _digest(ROOT / name)
           for name in manifest["code_sha256"]):
        raise ValueError("v2 structured profile code changed")
    base_package = Path(profile["base_package"])
    details = _details(base_package, model=profile["model"], strict=profile["strict"])
    expected_body = details.pop("body")
    if body != expected_body or profile.get("body_sha256") != details["body_sha256"] \
            or profile.get("body_bytes") != details["body_bytes"] \
            or request.get("messages") != expected_body["messages"]:
        raise ValueError("v2 structured profile does not match verified source package")
    return {"status": "verified", "profile": str(profile_dir),
            "case": profile["case"], "body_bytes": profile["body_bytes"],
            "input_token_estimate": profile["input_token_estimate"],
            "body_sha256": profile["body_sha256"],
            "schema_sha256": profile["schema_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", nargs=2, metavar=("PACKAGE", "OUTPUT"))
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--non-strict", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        result = prepare(Path(args.prepare[0]), Path(args.prepare[1]),
                         model=args.model, strict=not args.non_strict)
    else:
        result = verify_profile(args.verify)
    print(json.dumps(result, ensure_ascii=False, indent=2))
