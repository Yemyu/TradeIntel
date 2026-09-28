"""Re-read every mirrored month and record a version-level verification marker."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeintel_ai.trade_mysql_loader import (  # noqa: E402
    MysqlCli, MysqlMirrorLoadError, check_connection, finalize_release,
    mysql_executable, validate_schema,
)
from tradeintel_ai.trade_mysql_mirror import (  # noqa: E402
    TradeMirrorError, inspect_export_snapshot, inspect_import_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--flow", choices=("import", "export", "both"), default="both")
    parser.add_argument("--login-path", default="tradeintel")
    parser.add_argument("--apply", action="store_true",
                        help="写入整版验收标记；未指定时只做完整复核")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "tmp/handoff-runs/mysql-mirror-finalize.json")
    args = parser.parse_args()
    report: dict[str, object] = {
        "status": "started", "action": "record_verification" if args.apply else "full_readback",
        "requested_flow": args.flow, "model_api_calls": 0, "datasets": [],
    }
    started = time.monotonic()
    try:
        datasets = (inspect_import_snapshot(args.root), inspect_export_snapshot(args.root))
        selected = [dataset for dataset in datasets
                    if args.flow == "both" or dataset.flow == args.flow]
        client = MysqlCli(mysql_executable(), login_path=args.login_path)
        report["connection"] = check_connection(client)
        validate_schema(client)
        for dataset in selected:
            print(json.dumps({"starting_full_readback": dataset.flow}, ensure_ascii=False), flush=True)
            audit_path = args.output.parent / (
                f"mysql-mirror-verification-{dataset.flow}-{dataset.data_version[:12]}.json"
            )
            result = finalize_release(client, args.root, dataset, apply=args.apply,
                                     audit_path=audit_path)
            report["datasets"].append({
                "flow": dataset.flow, "dataset_id": dataset.dataset_id,
                "data_version": dataset.data_version, **result,
            })
            print(json.dumps({"finished_full_readback": dataset.flow,
                              "action": result["action"]}, ensure_ascii=False), flush=True)
        report["status"] = "full_release_verified" if args.apply else "full_readback_passed_marker_not_written"
    except (OSError, ValueError, TradeMirrorError, MysqlMirrorLoadError) as exc:
        report["status"] = "stopped_without_verification_marker"
        report["error"] = str(exc)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {
        "full_release_verified", "full_readback_passed_marker_not_written",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
