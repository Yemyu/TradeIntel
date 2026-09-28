"""Offline-only preflight for mirroring published trade CSVs into MySQL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeintel_ai.trade_mysql_mirror import TradeMirrorError, audit_trade_mysql_files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path,
                        help="可选：将逐月审计明细保存为 JSON 文件")
    args = parser.parse_args()
    try:
        report = audit_trade_mysql_files(args.root)
    except (OSError, TradeMirrorError) as exc:
        print(json.dumps({"status": "offline_file_audit_failed", "error": str(exc)},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        summary = {
            "status": report["status"],
            "database_checked": report["database_checked"],
            "audit_sha256": report["audit_sha256"],
            "datasets": [
                {key: dataset[key] for key in
                 ("dataset_id", "data_version", "month_count", "csv_rows", "sql_rows")}
                for dataset in report["datasets"]
            ],
            "report_file": str(args.output),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
