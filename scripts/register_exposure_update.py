"""Register a verified exposure replay and activate it atomically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeintel_ai.exposure_version_store import ExposureVersionStore, VersionStoreError


def register(input_dir: Path, *, root: Path = ROOT) -> dict[str, object]:
    input_dir = Path(input_dir).resolve()
    before = json.loads((input_dir / "before.json").read_text(encoding="utf-8"))
    after = json.loads((input_dir / "after.json").read_text(encoding="utf-8"))
    difference = json.loads((input_dir / "difference.json").read_text(encoding="utf-8"))
    store = ExposureVersionStore(root)
    active = store.active_version()
    if active is None:
        store.bootstrap(before, source=f"replay:{input_dir.name}")
        active = before["version"]
    if active == after["version"]:
        store.prepare_release(active)
        return {
            "status": "already_active",
            "active_version": active,
            "candidate_version": after["version"],
            "idempotent": True,
        }
    if active != before["version"]:
        raise VersionStoreError("回放的 before 版本不是当前活动版本")
    store.prepare_release(active)
    staged = store.stage(
        before,
        after,
        difference,
        source=f"replay:{input_dir.name}",
    )
    store.prepare_release(after['version'])
    activated = store.activate(after["version"])
    return {
        "status": "activated",
        "active_version": activated["version"],
        "previous_version": activated.get("previous_version"),
        "candidate": staged,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="replay_exposure_update.py 的输出目录")
    args = parser.parse_args()
    print(json.dumps(register(args.input), ensure_ascii=False, indent=2))
