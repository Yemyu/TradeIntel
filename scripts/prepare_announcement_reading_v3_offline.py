"""Build/verify an offline v3 announcement-reading package; never call a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tradeintel_ai.announcement_reading_v3 import (
    MAX_POST_BYTES, build_reading_package, verify_reading_package,
)


PACK_SCHEMA = "announcement-reading-offline-pack-v3"


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular file: {path}")
    return path.read_bytes()


def _load_store(path: Path) -> tuple[dict[str, Any], bytes]:
    source = _read_regular(path)
    store = json.loads(source)
    if not isinstance(store, dict) or not isinstance(store.get("documents"), list) \
            or len(store["documents"]) != 1:
        raise ValueError("v3 offline pack requires one saved document")
    return store, source


def prepare(store_path: Path, output: Path) -> dict[str, Any]:
    store, source = _load_store(store_path)
    package = build_reading_package(store, store["documents"][0]["doc_version"])
    request = {key: package[key] for key in (
        "schema_version", "doc_version", "source_sha256", "request_sha256",
        "request_bytes", "messages", "check_ids",
    )}
    sidecar = {key: package[key] for key in (
        "schema_version", "doc_version", "source_sha256", "anchors", "boundary",
    )}
    request_bytes, sidecar_bytes = _encoded(request), _encoded(sidecar)
    manifest = {
        "schema_version": PACK_SCHEMA,
        "status": "offline_only_not_authorized_for_provider",
        "source_store_sha256": _hash(source),
        "request_file_sha256": _hash(request_bytes),
        "anchor_file_sha256": _hash(sidecar_bytes),
        "doc_version": package["doc_version"],
        "source_sha256": package["source_sha256"],
        "request_bytes": package["request_bytes"],
        "anchor_count": len(package["anchors"]),
        "post_body_budget_bytes": MAX_POST_BYTES,
        "post_body_status": "not_built_or_verified",
        "api_calls": 0,
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "request.json").write_bytes(request_bytes)
    (output / "anchor-map.json").write_bytes(sidecar_bytes)
    # The manifest is written last; a partial directory is never ready.
    (output / "MANIFEST.json").write_bytes(_encoded(manifest))
    verify(store_path, output)
    return manifest


def verify(store_path: Path, output: Path) -> dict[str, Any]:
    store, source = _load_store(store_path)
    manifest = json.loads(_read_regular(output / "MANIFEST.json"))
    request_bytes = _read_regular(output / "request.json")
    sidecar_bytes = _read_regular(output / "anchor-map.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != PACK_SCHEMA \
            or manifest.get("status") != "offline_only_not_authorized_for_provider" \
            or manifest.get("api_calls") != 0 \
            or manifest.get("post_body_status") != "not_built_or_verified" \
            or manifest.get("post_body_budget_bytes") != MAX_POST_BYTES \
            or manifest.get("source_store_sha256") != _hash(source) \
            or manifest.get("request_file_sha256") != _hash(request_bytes) \
            or manifest.get("anchor_file_sha256") != _hash(sidecar_bytes):
        raise ValueError("v3 offline pack differs from its manifest")
    request = json.loads(request_bytes)
    sidecar = json.loads(sidecar_bytes)
    if not isinstance(request, dict) or not isinstance(sidecar, dict) \
            or request.get("schema_version") != sidecar.get("schema_version") \
            or request.get("doc_version") != sidecar.get("doc_version") \
            or request.get("source_sha256") != sidecar.get("source_sha256"):
        raise ValueError("v3 request and anchor map are not bound together")
    package = {
        **request, "status": "offline_review_only",
        "anchors": sidecar["anchors"], "boundary": sidecar["boundary"],
    }
    verify_reading_package(store, package)
    if manifest.get("doc_version") != package["doc_version"] \
            or manifest.get("source_sha256") != package["source_sha256"] \
            or manifest.get("request_bytes") != package["request_bytes"] \
            or manifest.get("anchor_count") != len(package["anchors"]):
        raise ValueError("v3 manifest identity or counts differ")
    return {"status": "verified_offline", "doc_version": package["doc_version"],
            "request_bytes": package["request_bytes"],
            "anchor_count": len(package["anchors"]), "api_calls": 0,
            "post_body_status": "not_built_or_verified"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = verify(args.store, args.output) if args.verify else prepare(args.store, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
