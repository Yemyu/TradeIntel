"""Verify the small set of local artifacts omitted from a Git checkout.

Read-only: it never downloads, edits, deletes, or copies data. A non-zero
exit means the offline demo/data-dependent entry should not be described as
ready. The manifest contains public source URLs and hashes, never credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/PORTABLE_DATA_MANIFEST.json"
REQUIRED = {
    'policy-initial-pdf': 'data/raw/policy/ustr-section301-list1-2018.pdf',
    'policy-amendment-pdf': 'data/raw/policy/ustr-section301-list1-amendment-2018-08-16.pdf',
    'policy-source-manifest': 'data/raw/policy/source_manifest.json',
    'causal-hs6-panel': 'data/processed/causal/causal_trade_hs6_monthly.csv',
}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path = ROOT, manifest_path: Path = MANIFEST) -> dict:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file() or not manifest_path.is_relative_to(root):
        raise ValueError("manifest must be a file inside the project root")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError('manifest must be an object')
    artifacts = value.get("artifacts")
    if value.get("version") != "portable-data-manifest-1" or not isinstance(artifacts, list):
        raise ValueError("unsupported portable data manifest")
    if (len(artifacts) != len(REQUIRED)
            or any(not isinstance(item, dict) for item in artifacts)
            or {item.get('id') for item in artifacts if isinstance(item.get('id'), str)} != set(REQUIRED)):
        raise ValueError('manifest must include all four unique required artifacts')
    rows = []
    for item in artifacts:
        relative = item.get("path")
        expected_hash = item.get("sha256")
        expected_bytes = item.get("bytes")
        if (relative != REQUIRED[item['id']] or not isinstance(relative, str) or Path(relative).is_absolute()
                or ".." in Path(relative).parts or not isinstance(expected_hash, str)
                or not re.fullmatch(r'[0-9a-f]{64}', expected_hash)
                or type(expected_bytes) is not int or expected_bytes <= 0):
            raise ValueError("invalid portable data manifest artifact")
        path = (root / relative).resolve()
        row = {"id": item.get("id"), "path": relative, "status": "missing"}
        if not path.is_file() or not path.is_relative_to(root):
            rows.append(row)
            continue
        actual_bytes = path.stat().st_size
        actual_hash = _digest(path)
        row.update({"bytes": actual_bytes, "sha256": actual_hash})
        if actual_bytes != expected_bytes:
            row["status"] = "size_mismatch"
        elif actual_hash != expected_hash:
            row["status"] = "sha256_mismatch"
        else:
            row["status"] = "verified"
        rows.append(row)
    counts = {status: sum(row["status"] == status for row in rows)
              for status in ("verified", "missing", "size_mismatch", "sha256_mismatch")}
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path.relative_to(root)),
        "status": "ready" if counts["verified"] == len(rows) else "incomplete",
        "artifact_count": len(rows), "counts": counts, "artifacts": rows,
        "network_calls": 0,
        "scope": "four_manifest_artifacts_only",
        "full_application_readiness_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="checkout or data bundle root")
    parser.add_argument("--manifest", type=Path,
                        help="manifest path; defaults to ROOT/data/PORTABLE_DATA_MANIFEST.json")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest or (root / "data/PORTABLE_DATA_MANIFEST.json")
    try:
        report = verify(root=root, manifest_path=manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_manifest", "error": str(exc)},
                         ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
