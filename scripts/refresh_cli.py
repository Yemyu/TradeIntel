#!/usr/bin/env python3
"""Refresh CLI: controlled trade-data update check with dry-run support.

Offline by default.  Without a configured fetch source it reports the active
version, the last check time and the data cutoff month ("最近检查时间" and
"数据统计截止月"), which is exactly what the page should display.  Real
fetching is a pluggable callable; this round ships no scheduler and no
resident task.

Examples:
    python scripts/refresh_cli.py --check-only
    python scripts/refresh_cli.py --dry-run --fetch-payload tmp/next-snapshot.json
    python scripts/refresh_cli.py --confirm --fetch-payload tmp/next-snapshot.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tradeintel_ai.exposure_version_store import VersionStoreError
from src.tradeintel_ai.controlled_update import run_update_cycle, update_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true",
                        help="只报告最近检查时间与数据统计截止月，不抓取")
    parser.add_argument("--fetch-payload", type=Path, default=None,
                        help="包含新快照payload的JSON文件（离线注入的抓取结果）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true",
                        help="确认激活无需审查的候选版本")
    parser.add_argument("--versions-dir", type=Path, default=None)
    args = parser.parse_args()

    if args.check_only:
        status = update_status(ROOT, versions_dir=args.versions_dir)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    if args.fetch_payload is None:
        status = update_status(ROOT, versions_dir=args.versions_dir)
        print(json.dumps({"status": "no_fetch_source", "message":
                          "未配置真实抓取源；本轮仅报告当前版本状态。", **status},
                         ensure_ascii=False, indent=2))
        return 0
    payload = json.loads(args.fetch_payload.read_text(encoding="utf-8"))
    try:
        result = run_update_cycle(ROOT, fetch=lambda: payload, confirm=args.confirm,
                                  dry_run=args.dry_run, versions_dir=args.versions_dir)
    except VersionStoreError as exc:
        print(json.dumps({"status": "rejected", "message": str(exc)},
                         ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "activation_failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
