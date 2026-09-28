"""Build or verify a source-bound, offline reading-suggestion development pack.

This script has no provider client and never writes an announcement candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tradeintel_ai.announcement_reading_suggestions import (
    build_reading_package, verify_reading_package,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "tmp/policy-extraction-dev-20260926/r2-v9/document-store.json"
DEFAULT_OUTPUT = ROOT / "tmp/announcement-reading-dev-20260927/r2-v2"


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_store(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("saved document store must be a regular file")
    store = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(store, dict):
        raise ValueError("saved document store must be an object")
    return store


def prepare(store_path: Path, output: Path) -> dict[str, Any]:
    store_path, output = store_path.resolve(), output.resolve()
    store = _load_store(store_path)
    if len(store.get("documents", [])) != 1:
        raise ValueError("offline development pack requires exactly one saved document")
    package = build_reading_package(store, store["documents"][0]["doc_version"])
    request = {key: package[key] for key in (
        "schema_version", "doc_version", "source_sha256",
        "request_sha256", "request_bytes", "messages")}
    sidecar = {"schema_version": package["schema_version"],
               "doc_version": package["doc_version"], "anchors": package["anchors"]}
    request_bytes, sidecar_bytes = _encoded(request), _encoded(sidecar)
    manifest = {
        "schema_version": "announcement-reading-offline-pack-v2",
        "status": "offline_only_not_authorized_for_provider",
        "source_store_sha256": _hash(store_path.read_bytes()),
        "request_file_sha256": _hash(request_bytes),
        "anchor_file_sha256": _hash(sidecar_bytes),
        "source_path": str(store_path),
        "doc_version": package["doc_version"],
        "request_bytes": package["request_bytes"],
        "anchor_count": len(package["anchors"]),
        "api_calls": 0,
        "boundary": package["boundary"],
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "request.json").write_bytes(request_bytes)
    (output / "anchor-map.json").write_bytes(sidecar_bytes)
    (output / "MANIFEST.json").write_bytes(_encoded(manifest))
    verify(store_path, output)
    return manifest


def verify(store_path: Path, output: Path) -> dict[str, Any]:
    store_path, output = store_path.resolve(), output.resolve()
    store = _load_store(store_path)
    manifest = json.loads((output / "MANIFEST.json").read_text(encoding="utf-8"))
    request_bytes = (output / "request.json").read_bytes()
    sidecar_bytes = (output / "anchor-map.json").read_bytes()
    if manifest.get("schema_version") != "announcement-reading-offline-pack-v2" \
            or manifest.get("status") != "offline_only_not_authorized_for_provider" \
            or manifest.get("api_calls") != 0 \
            or manifest.get("source_store_sha256") != _hash(store_path.read_bytes()) \
            or manifest.get("request_file_sha256") != _hash(request_bytes) \
            or manifest.get("anchor_file_sha256") != _hash(sidecar_bytes):
        raise ValueError("offline reading pack differs from its manifest")
    request = json.loads(request_bytes)
    sidecar = json.loads(sidecar_bytes)
    package = {
        **request, "status": "offline_review_only",
        "anchors": sidecar["anchors"], "boundary": manifest["boundary"],
    }
    if sidecar.get("doc_version") != request.get("doc_version") \
            or sidecar.get("schema_version") != request.get("schema_version"):
        raise ValueError("reading request and anchor map are not bound together")
    verify_reading_package(store, package)
    if manifest.get("doc_version") != package["doc_version"] \
            or manifest.get("request_bytes") != package["request_bytes"] \
            or manifest.get("anchor_count") != len(package["anchors"]):
        raise ValueError("offline reading manifest has stale counts or identity")
    return {"status": "verified_offline", "doc_version": package["doc_version"],
            "request_bytes": package["request_bytes"],
            "anchor_count": len(package["anchors"]), "api_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = verify(args.store, args.output) if args.verify else prepare(args.store, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
