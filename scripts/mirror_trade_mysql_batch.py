"""Continue the approved MySQL mirror load month by month.

The command audits both snapshots once, requires an explicit ``--apply`` for
writes, and stops at the first month that cannot be completely read back.
Already matched months are checked and skipped by the single-month loader.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeintel_ai.trade_mysql_loader import (  # noqa: E402
    MysqlCli, MysqlMirrorLoadError, load_month, mysql_executable,
    check_connection, validate_schema,
)
from tradeintel_ai.trade_mysql_mirror import (  # noqa: E402
    DatasetAudit, TradeMirrorError, inspect_export_snapshot,
    inspect_import_snapshot,
)


def _month_key(value: str) -> tuple[int, int]:
    if len(value) != 7 or value[4] != "-" or not value[:4].isdigit() or not value[5:].isdigit():
        raise argparse.ArgumentTypeError("月份必须为 YYYY-MM")
    year, month = int(value[:4]), int(value[5:])
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError("月份必须为 YYYY-MM")
    return year, month


def _write(path: Path | None, report: dict[str, object], *, emit: bool = True) -> None:
    data = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
    if emit:
        print(data, end="", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--flow", choices=("import", "export", "both"), default="both")
    parser.add_argument("--from-month", type=_month_key,
                        help="只处理此月及之后的已发布月份")
    parser.add_argument("--to-month", type=_month_key,
                        help="只处理此月及之前的已发布月份")
    parser.add_argument("--login-path", default="tradeintel")
    parser.add_argument("--apply", action="store_true",
                        help="执行逐月写入；未指定时只做文件和数据库预检")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.from_month and args.to_month and args.from_month > args.to_month:
        parser.error("--from-month 不能晚于 --to-month")

    report: dict[str, object] = {
        "status": "started", "action": "batch_load" if args.apply else "read_only",
        "requested_flow": args.flow, "model_api_calls": 0,
        "completed": [], "stopped_at": None,
    }
    started = time.monotonic()
    try:
        datasets = (inspect_import_snapshot(args.root), inspect_export_snapshot(args.root))
        selected: list[DatasetAudit] = [dataset for dataset in datasets
                                        if args.flow == "both" or dataset.flow == args.flow]
        if not selected:
            raise MysqlMirrorLoadError("没有选择任何数据方向")
        client = MysqlCli(mysql_executable(), login_path=args.login_path)
        report["connection"] = check_connection(client)
        validate_schema(client)
        lo, hi = args.from_month, args.to_month
        pairs = [
            (dataset, month) for dataset in selected for month in dataset.months
            if (lo is None or (month.year, month.month) >= lo)
            and (hi is None or (month.year, month.month) <= hi)
        ]
        report["planned"] = len(pairs)
        report["offline_audit"] = [{
            "flow": dataset.flow, "dataset_id": dataset.dataset_id,
            "data_version": dataset.data_version, "audited_months": len(dataset.months),
            "audited_csv_rows": dataset.csv_rows, "audited_sql_rows": dataset.sql_rows,
            "manifest_sha256": dataset.manifest_sha256,
        } for dataset in datasets]
        if not args.apply:
            report["status"] = "read_only_preflight_passed"
            _write(args.output, report)
            return 0
        for index, (dataset, month) in enumerate(pairs, 1):
            month_started = time.monotonic()
            try:
                result = load_month(client, args.root, dataset, month, apply=True)
            except Exception as exc:  # preserve the exact stop point in the report
                report["status"] = "stopped_without_automatic_retry"
                report["stopped_at"] = {
                    "flow": dataset.flow, "dataset_id": dataset.dataset_id,
                    "month": month.month_key, "error": str(exc),
                    "completed_count": index - 1,
                }
                report["elapsed_seconds"] = round(time.monotonic() - started, 3)
                _write(args.output, report)
                return 1
            item = {
                "flow": dataset.flow, "dataset_id": dataset.dataset_id,
                "data_version": dataset.data_version, "month": month.month_key,
                **result, "elapsed_seconds": round(time.monotonic() - month_started, 3),
            }
            completed = report["completed"]
            assert isinstance(completed, list)
            completed.append(item)
            print(json.dumps({"progress": f"{index}/{len(pairs)}", **item},
                             ensure_ascii=False), flush=True)
            if args.output:
                _write(args.output, report, emit=False)
        report["status"] = "months_matched_not_full_release_verified"
    except (OSError, ValueError, TradeMirrorError, MysqlMirrorLoadError) as exc:
        report["status"] = "stopped_without_automatic_retry"
        report["error"] = str(exc)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["disk_free_after_bytes"] = shutil.disk_usage(args.root).free
    _write(args.output, report)
    return 0 if report["status"] in {
        "read_only_preflight_passed", "months_matched_not_full_release_verified",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
