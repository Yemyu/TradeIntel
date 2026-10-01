"""Feed a saved fake JSON answer through the v3 parser; no provider client."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.prepare_announcement_reading_v3_offline import verify as verify_pack
from tradeintel_ai.announcement_reading_v3 import parse_reading_answer


SCHEMA = "announcement-reading-v3-fake-run-v1"


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"fake run input must be a regular file: {path}")
    return path.read_bytes()


def run_fake(store_path: Path, pack: Path, answer_path: Path,
             output: Path) -> dict[str, Any]:
    verify_pack(store_path, pack)
    store_bytes = _read(store_path)
    store = json.loads(store_bytes)
    request = json.loads(_read(pack / "request.json"))
    sidecar = json.loads(_read(pack / "anchor-map.json"))
    package = {**request, "status": "offline_review_only",
               "anchors": sidecar["anchors"], "boundary": sidecar["boundary"]}
    raw = _read(answer_path)
    review = parse_reading_answer(raw, package, store)
    review_bytes = _encoded(review)
    manifest = {
        "schema_version": SCHEMA,
        "status": review["status"],
        "doc_version": review["doc_version"],
        "source_store_sha256": _hash(store_bytes),
        "pack_manifest_sha256": _hash(_read(pack / "MANIFEST.json")),
        "answer_sha256": _hash(raw),
        "review_sha256": _hash(review_bytes),
        "api_calls": 0,
        "provider_used": False,
        "boundary": "离线假回答，只验证合同和展示，不是模型效果。",
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "answer.json").write_bytes(raw)
    (output / "review.json").write_bytes(review_bytes)
    (output / "MANIFEST.json").write_bytes(_encoded(manifest))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--answer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_fake(args.store, args.pack, args.answer, args.output),
                     ensure_ascii=False, indent=2))
