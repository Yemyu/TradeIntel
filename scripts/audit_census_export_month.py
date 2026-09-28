"""One-month read-only Census export ZIP audit; prints machine-readable evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tradeintel_ai.census_export_audit import ExportAuditError, audit_export_month


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    args = parser.parse_args()
    try:
        result = audit_export_month(args.archive, year=args.year, month=args.month)
    except (ExportAuditError, OSError) as exc:
        print(f"出口月包核验失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
