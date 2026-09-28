"""Audit published trade CSVs, then optionally mirror one month into MySQL.

Default is read-only. Schema creation and monthly loading are separate explicit
actions; this command never changes old trade tables or full-release markers.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeintel_ai.trade_mysql_loader import (
    MysqlCli, MysqlMirrorLoadError, TARGET_TABLES, check_connection,
    ensure_schema, load_month, mysql_executable, validate_schema,
)
from tradeintel_ai.trade_mysql_mirror import (
    TradeMirrorError, inspect_export_snapshot, inspect_import_snapshot,
)


def _write_report(path: Path | None, report: dict[str, object]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--month", required=True, help="明确指定 YYYY-MM；不会自动加载所有月份")
    parser.add_argument("--flow", choices=("import", "export", "both"), default="both")
    parser.add_argument("--login-path", default="tradeintel")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply-schema", action="store_true", help="仅新建缺失的镜像表，不载入数据")
    action.add_argument("--apply", action="store_true", help="仅载入指定月，不自动建表")
    parser.add_argument("--output", type=Path, help="可选 JSON 审计输出路径")
    args = parser.parse_args()
    if len(args.month) != 7 or args.month[4] != "-" or not args.month[:4].isdigit() or not args.month[5:].isdigit():
        parser.error("--month 必须为 YYYY-MM")

    report: dict[str, object] = {
        "status": "started", "action": "apply_schema" if args.apply_schema else
        ("load_month" if args.apply else "read_only"),
        "month": args.month, "requested_flow": args.flow,
        "mysql_full_release_verified": False, "model_api_calls": 0,
        "datasets": [],
    }
    started = time.monotonic()
    try:
        # Both snapshots are checked before any MySQL connection or write.
        audited = (inspect_import_snapshot(args.root), inspect_export_snapshot(args.root))
        selected = [dataset for dataset in audited
                    if args.flow == "both" or dataset.flow == args.flow]
        pairs = []
        for dataset in selected:
            matches = [month for month in dataset.months if month.month_key == args.month]
            if len(matches) != 1:
                raise MysqlMirrorLoadError(
                    f"{dataset.flow} 已发布快照不含指定月份 {args.month}"
                )
            pairs.append((dataset, matches[0]))
        report["offline_audit"] = [{
            "flow": dataset.flow, "dataset_id": dataset.dataset_id,
            "data_version": dataset.data_version,
            "manifest_sha256": dataset.manifest_sha256,
            "audited_months": len(dataset.months),
            "audited_csv_rows": dataset.csv_rows,
            "audited_sql_rows": dataset.sql_rows,
        } for dataset in audited]
        report["disk_free_before_bytes"] = shutil.disk_usage(args.root).free
        client = MysqlCli(mysql_executable(), login_path=args.login_path)
        report["connection"] = check_connection(client)
        schema_file = args.root / "db/schema.sql"
        created = ensure_schema(client, schema_file, apply=args.apply_schema)
        report["schema_created"] = created
        tables = {row[0] for row in client.query(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"
        )}
        if not TARGET_TABLES.issubset(tables):
            if args.apply:
                raise MysqlMirrorLoadError("镜像表尚未建立；请先单独执行 --apply-schema")
            report["status"] = "schema_missing_no_data_loaded"
        elif args.apply_schema:
            validate_schema(client)
            report["status"] = "schema_ready_no_data_loaded"
        else:
            validate_schema(client)
            for dataset, month in pairs:
                month_started = time.monotonic()
                result = load_month(client, args.root, dataset, month, apply=args.apply)
                report["datasets"].append({
                    "flow": dataset.flow, "dataset_id": dataset.dataset_id,
                    "data_version": dataset.data_version,
                    "source_manifest_sha256": dataset.manifest_sha256,
                    "source_sha256": month.source_sha256,
                    "processed_sha256": month.processed_sha256,
                    **result, "elapsed_seconds": round(time.monotonic() - month_started, 3),
                })
            results = report["datasets"]
            assert isinstance(results, list)
            report["mysql_full_release_verified"] = bool(results) and all(
                bool(item.get("full_release_verified")) for item in results
                if isinstance(item, dict)
            )
            report["status"] = ("pilot_months_matched_not_full_release_verified"
                                if args.apply else "read_only_preview")
    except (OSError, ValueError, TradeMirrorError, MysqlMirrorLoadError,
            subprocess.TimeoutExpired) as exc:
        report["status"] = "stopped_without_automatic_retry"
        report["error"] = str(exc)
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _write_report(args.output, report)
        return 1
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["disk_free_after_bytes"] = shutil.disk_usage(args.root).free
    _write_report(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
