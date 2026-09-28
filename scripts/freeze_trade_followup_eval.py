"""Build or verify a frozen, provider-free four-question trade follow-up packet."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tradeintel_ai.trade_explanation import report_sha256
from tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question
from tradeintel_ai.trade_report_followup import build_catalog, catalog_sha256, messages


ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = Path("evals/trade_followup_v1")
DEFAULT_OUTPUT = EVAL_ROOT / "frozen/20260926-v1"
SCHEMA = "trade-followup-eval-package-v1"
STATIC_FILES = (
    "README.zh-CN.md",
    "scenarios.json",
    "SCORING.json",
    "MODEL_MATRIX_TEMPLATE.json",
    "review_template.csv",
)
CODE_FILES = (
    "src/tradeintel_ai/trade_query_flow.py",
    "src/tradeintel_ai/trade_classification_catalog.py",
    "src/tradeintel_ai/trade_data_repository.py",
    "src/tradeintel_ai/trade_export_repository.py",
    "src/tradeintel_ai/trade_report_followup.py",
    "src/tradeintel_ai/trade_explanation.py",
    "src/tradeintel_ai/response_contract.py",
    "scripts/freeze_trade_followup_eval.py",
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    return _hash_bytes(path.read_bytes())


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _month_index(month: str) -> int:
    if not isinstance(month, str) or not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", month):
        raise ValueError("月份格式无效")
    year, number = map(int, month.split("-"))
    return year * 12 + number - 1


def _month_from_index(index: int) -> str:
    year, zero_based_month = divmod(index, 12)
    return f"{year:04d}-{zero_based_month + 1:02d}"


def _cases(root: Path) -> list[dict[str, Any]]:
    spec = _load_json(root / EVAL_ROOT / "scenarios.json")
    cases = spec.get("scenarios") if isinstance(spec, dict) else None
    if (spec.get("schema_version") != "trade-followup-four-questions-v1" or
            spec.get("status") != "frozen_for_review" or
            spec.get("window") != {"start_month": "2025-08", "end_month": "2026-07",
                                   "interpretation": "追问中的七月指 2026-07；今年指这份报告中已发布的 2026 年月份。"} or
            not isinstance(cases, list) or [case.get("id") for case in cases] !=
            ["f1", "f2", "f3", "f4"]):
        raise ValueError("四题评测定义的版本、月份或顺序不符")
    required = {"id", "initial_question", "followup_question", "flow",
                "selected_product_id", "expected_changes_usd", "must_not_claim"}
    for case in cases:
        if (not isinstance(case, dict) or set(case) - (required | {"comparison_window"}) or
                not required.issubset(case) or case["flow"] not in {"import", "export", "both"} or
                not isinstance(case["initial_question"], str) or
                not isinstance(case["followup_question"], str) or
                not isinstance(case["expected_changes_usd"], dict)):
            raise ValueError("评测题字段无效")
    return cases


def _parts(report: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    if report.get("kind") == "trade-query-both-v1":
        return report["import_report"], report["export_report"]
    if report.get("kind") == "trade-query-v1":
        return (report,)
    raise ValueError("报告类型无效")


def _reference(root: Path, report: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Independently recompute adjacent changes from the frozen report rows."""
    spec = _load_json(root / EVAL_ROOT / "scenarios.json")
    window = spec["window"]
    start, end = window["start_month"], window["end_month"]
    if _month_index(end) - _month_index(start) + 1 != 12:
        raise ValueError("评测期必须是连续十二个月")
    if report.get("question") != case["initial_question"]:
        raise ValueError("报告原问题与题目不一致")
    directions: dict[str, Any] = {}
    for part in _parts(report):
        scope = part.get("scope")
        rows = part.get("series")
        if not isinstance(scope, dict) or not isinstance(rows, list) or len(rows) != 12:
            raise ValueError("报告范围或逐月数据无效")
        flow = scope.get("flow")
        if (flow in directions or scope.get("product_code") != case["selected_product_id"].split(":", 1)[1] or
                scope.get("start_month") != start or scope.get("end_month") != end or
                scope.get("partner") != ("ALL_DESTINATIONS" if flow == "export" else "ALL_ORIGINS")):
            raise ValueError("报告确认范围与冻结题目不一致")
        metric = ("total_export_fas_usd" if flow == "export" else
                  "import_value_consumption_usd")
        if scope.get("metric") != metric:
            raise ValueError("报告统计口径不符合题包约定")
        values = []
        for offset, row in enumerate(rows):
            expected_month = _month_from_index(_month_index(start) + offset)
            if (not isinstance(row, dict) or row.get("month") != expected_month or
                    row.get("status") != "observed" or type(row.get("value_usd")) is not int or
                    row["value_usd"] < 0 or not row.get("source_sha256") or
                    not str(row.get("source_url", "")).startswith("https://")):
                raise ValueError("报告有缺月、未观察金额或无来源的行")
            values.append({"month": row["month"], "value_usd": row["value_usd"],
                           "source_sha256": row["source_sha256"],
                           "source_url": row["source_url"]})
        changes = []
        for previous, current in zip(values, values[1:]):
            if previous["month"][:4] != current["month"][:4]:
                continue
            delta = current["value_usd"] - previous["value_usd"]
            changes.append({"from_month": previous["month"], "to_month": current["month"],
                            "change_usd": delta,
                            "fact_id": f"{flow}.change.{current['month']}"})
        directions[flow] = {
            "metric": metric,
            "partner": scope["partner"],
            "product_code": scope["product_code"],
            "product_label": scope.get("product_label"),
            "dataset_version": scope.get("dataset_version"),
            "values": values,
            "same_year_adjacent_changes": changes,
        }
    expected_flows = {"import", "export"} if case["flow"] == "both" else {case["flow"]}
    if set(directions) != expected_flows:
        raise ValueError("报告缺少题目要求的贸易方向")
    actual_changes = {}
    for flow, details in directions.items():
        actual_changes.update({f"{flow}:{item['to_month']}": item["change_usd"]
                               for item in details["same_year_adjacent_changes"]})
    expected_changes = {}
    for key, value in case["expected_changes_usd"].items():
        if ":" in key:
            expected_changes[key] = value
        else:
            flow = "export" if case["flow"] == "export" else "import"
            expected_changes[f"{flow}:{key}"] = value
    if any(actual_changes.get(key) != value for key, value in expected_changes.items()):
        raise ValueError(f"已冻结关键差额与报告逐月金额不一致：{case['id']}")
    result = {
        "case_id": case["id"],
        "initial_question": case["initial_question"],
        "followup_question": case["followup_question"],
        "report_sha256": report_sha256(report),
        "window": [start, end],
        "directions": directions,
        "expected_changes_usd": expected_changes,
        "must_not_claim": case["must_not_claim"],
    }
    if "comparison_window" in case:
        result["comparison_window"] = case["comparison_window"]
    return result


def _make_case(root: Path, case: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    initial = prepare_trade_question(root, case["initial_question"])
    product_id = case["selected_product_id"]
    choice = next((item for item in initial.get("candidates", []) if item.get("id") == product_id), None)
    if initial.get("status") != "needs_product_choice" or choice is None:
        raise ValueError(f"{case['id']} 无法按官方目录确认预定商品")
    if initial.get("start_month") != "2025-08" or initial.get("end_month") != "2026-07":
        raise ValueError(f"{case['id']} 当前数据月份窗口与冻结窗口不同")
    proposal = prepare_trade_question(
        root, case["initial_question"], selected_flow=case["flow"],
        selected_product_id=product_id, catalog_version=initial.get("catalog_version"))
    if (proposal.get("status") != "ready" or proposal.get("flow") != case["flow"] or
            proposal.get("selected_product_id") != product_id or
            (proposal.get("start_month"), proposal.get("end_month")) != ("2025-08", "2026-07")):
        raise ValueError(f"{case['id']} 服务器确认的范围不符合冻结题目")
    report = generate_trade_report(
        root, case["initial_question"], selected_flow=case["flow"],
        dataset_version=proposal["dataset_version"], selected_product_id=product_id,
        catalog_version=initial.get("catalog_version"))
    catalog = build_catalog(report)
    digest = catalog_sha256(catalog)
    request = messages(report, case["followup_question"], catalog, digest)
    reference = _reference(root, report, case)
    return {"choice": choice, "proposal": proposal, "report": report,
            "catalog": catalog, "request": request, "reference": reference,
            "report_sha256": report_sha256(report), "catalog_sha256": digest,
            "request_bytes": len(_canonical_bytes(request))}


def _write_json(output: Path, relative: str, value: object,
                file_hashes: dict[str, str]) -> None:
    data = _json_bytes(value)
    target = output / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    file_hashes[relative] = _hash_bytes(data)


def build_package(root: Path = ROOT, output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"题包目录已存在，拒绝覆盖：{output}")
    cases = _cases(root)
    prepared_cases = {case["id"]: _make_case(root, case) for case in cases}
    output.mkdir(parents=True, exist_ok=False)
    file_hashes: dict[str, str] = {}
    for rel in STATIC_FILES:
        data = (root / EVAL_ROOT / rel).read_bytes()
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        file_hashes[rel] = _hash_bytes(data)
    case_rows: dict[str, dict[str, Any]] = {}
    for case in cases:
        sid = case["id"]
        built = prepared_cases[sid]
        _write_json(output, f"requests/{sid}/messages.json", built["request"], file_hashes)
        _write_json(output, f"host_artifacts/{sid}/choice.json", built["choice"], file_hashes)
        _write_json(output, f"host_artifacts/{sid}/proposal.json", built["proposal"], file_hashes)
        _write_json(output, f"host_artifacts/{sid}/report.json", built["report"], file_hashes)
        _write_json(output, f"host_artifacts/{sid}/catalog.json", built["catalog"], file_hashes)
        _write_json(output, f"references/{sid}.json", built["reference"], file_hashes)
        case_rows[sid] = {
            "selected_product_id": case["selected_product_id"],
            "flow": case["flow"],
            "report_sha256": built["report_sha256"],
            "catalog_sha256": built["catalog_sha256"],
            "dataset_versions": built["proposal"].get("dataset_versions"),
            "catalog_version": built["proposal"].get("catalog_version"),
            "request_bytes": built["request_bytes"],
        }
    code_hashes = {rel: _hash_file(root / rel) for rel in CODE_FILES}
    manifest = {
        "schema_version": SCHEMA,
        "status": "frozen_materials_execution_not_authorized",
        "package_id": "trade-followup-v1-four-questions-20260926",
        "protocol": "trade-report-followup-v1",
        "model_calls": 0,
        "mysql_used": False,
        "network_used": False,
        "scenario_ids": [case["id"] for case in cases],
        "scenarios": case_rows,
        "files_sha256": file_hashes,
        "code_sha256": code_hashes,
        "manifest_note": "此清单最后写入；如果生成中断或文件后来变化，验证将拒绝该题包。",
    }
    (output / "MANIFEST.json").write_bytes(_json_bytes(manifest))
    verify_package(root, output)
    return {"output": str(output), "status": manifest["status"],
            "scenarios": len(cases), "model_calls": 0,
            "request_bytes": {key: value["request_bytes"] for key, value in case_rows.items()}}


def verify_package(root: Path = ROOT, output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    root, output = root.resolve(), output.resolve()
    manifest_path = output / "MANIFEST.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("题包清单缺失或无效；视为未就绪")
    manifest = _load_json(manifest_path)
    if (manifest.get("schema_version") != SCHEMA or
            manifest.get("status") != "frozen_materials_execution_not_authorized" or
            manifest.get("package_id") != "trade-followup-v1-four-questions-20260926" or
            manifest.get("protocol") != "trade-report-followup-v1" or
            manifest.get("model_calls") != 0 or manifest.get("mysql_used") is not False or
            manifest.get("network_used") is not False or
            manifest.get("scenario_ids") != ["f1", "f2", "f3", "f4"]):
        raise ValueError("题包状态或运行边界无效")
    expected = set(manifest.get("files_sha256", {}))
    actual = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file() and
              not path.is_symlink() and path.name != "MANIFEST.json"}
    if expected != actual:
        raise ValueError("题包有文件缺失或未经登记的文件")
    if any(path.is_symlink() for path in output.rglob("*")):
        raise ValueError("题包不允许包含符号链接")
    for rel, digest in manifest["files_sha256"].items():
        path = output / rel
        if not path.is_file() or _hash_file(path) != digest:
            raise ValueError(f"题包文件摘要不符：{rel}")
    if manifest.get("code_sha256") != {rel: _hash_file(root / rel) for rel in CODE_FILES}:
        raise ValueError("数据查询、追问协议或封包脚本代码已变化；须重新建版本")
    cases = _cases(root)
    for case in cases:
        sid = case["id"]
        built = _make_case(root, case)
        if (manifest["scenarios"][sid].get("report_sha256") != built["report_sha256"] or
                _load_json(output / f"host_artifacts/{sid}/report.json") != built["report"] or
                _load_json(output / f"host_artifacts/{sid}/choice.json") != built["choice"] or
                _load_json(output / f"host_artifacts/{sid}/proposal.json") != built["proposal"] or
                _load_json(output / f"host_artifacts/{sid}/catalog.json") != built["catalog"] or
                _load_json(output / f"requests/{sid}/messages.json") != built["request"] or
                _load_json(output / f"references/{sid}.json") != built["reference"]):
            raise ValueError(f"{sid}当前报告、实际请求或程序参考不匹配")
        if built["request_bytes"] > 24_000:
            raise ValueError(f"{sid}模型输入超过已定预算")
    return {"output": str(output), "status": manifest["status"],
            "scenarios": 4, "model_calls": 0,
            "verified_files": len(manifest["files_sha256"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = (verify_package(args.root, args.output) if args.verify else
              build_package(args.root, args.output))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
