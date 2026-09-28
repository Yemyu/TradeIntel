"""Verify and publish one official Census export ZIP; never downloads or calls AI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tradeintel_ai.census_export_audit import ExportAuditError
from tradeintel_ai.census_export_publish import publish_export_month


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    args = parser.parse_args()
    try:
        result = publish_export_month(args.root, args.archive, year=args.year, month=args.month)
    except (ExportAuditError, OSError, ValueError) as exc:
        print(f"出口月份未发布：{exc}", file=sys.stderr)
        return 2
    record = result["record"]
    print(json.dumps({"dataset_version": result["dataset_version"],
                      "month": f"{record['year']}-{record['month']:02d}",
                      "processed_file": record["processed_file"],
                      "processed_rows": record["processed_rows"],
                      "processed_sha256": record["processed_sha256"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
