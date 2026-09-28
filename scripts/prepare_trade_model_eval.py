"""Prepare and verify four *offline* v3 model-evaluation candidates.

The only model-visible file for each case is requests/<id>/messages.json.
No provider client is imported or called. This does not grant permission to run
formal model evaluation; a candidate package must be reviewed and frozen first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from tradeintel_ai.trade_explanation import PROTOCOL, messages, report_sha256
from tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = Path("evals/trade_model_v3/scenarios.json")
SCHEMA = "trade-model-eval-v3-candidate-v1"
CODE_PATHS = (
    Path("src/tradeintel_ai/trade_query_flow.py"),
    Path("src/tradeintel_ai/trade_classification_catalog.py"),
    Path("src/tradeintel_ai/trade_data_repository.py"),
    Path("src/tradeintel_ai/trade_export_repository.py"),
    Path("src/tradeintel_ai/trade_explanation.py"),
    Path("src/tradeintel_ai/response_contract.py"),
    Path("scripts/prepare_trade_model_eval.py"),
    SCENARIOS,
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(out: Path, rel: str, value: object, hashes: dict[str, str]) -> None:
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(value)
    path.write_bytes(data)
    hashes[rel] = hashlib.sha256(data).hexdigest()


def _month_number(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", value):
        raise ValueError("评测月份格式无效")
    return int(value[:4]) * 12 + int(value[5:]) - 1


def _parts(report: dict) -> tuple[dict, ...]:
    if report["kind"] == "trade-query-both-v1":
        return report["import_report"], report["export_report"]
    if report["kind"] == "trade-query-v1":
        return (report,)
    raise ValueError("评测报告类型无效")


def _independent_reference(report: dict, case: dict) -> dict:
    """Recompute an answer key from report rows, independent of prompt prose."""
    reference = {"question": case["question"], "window": [case["start_month"], case["end_month"]],
                 "product_code": case["selected_product_id"].split(":", 1)[1], "directions": {}}
    expected_months = _month_number(case["end_month"]) - _month_number(case["start_month"]) + 1
    if expected_months != 12:
        raise ValueError("本组评测必须使用同一连续十二个月")
    for part in _parts(report):
        scope, rows, summary = part["scope"], part["series"], part["summary"]
        flow = scope["flow"]
        if flow in reference["directions"] or len(rows) != expected_months:
            raise ValueError("评测方向重复或月份不完整")
        if (scope["product_code"] != reference["product_code"] or
                scope["start_month"] != case["start_month"] or
                scope["end_month"] != case["end_month"]):
            raise ValueError("报告商品或月份与题目确认范围不一致")
        for index, row in enumerate(rows):
            if (row.get("status") != "observed" or type(row.get("value_usd")) is not int or
                    row["value_usd"] < 0 or
                    _month_number(row["month"]) != _month_number(case["start_month"]) + index):
                raise ValueError("评测月份缺失、未观察或顺序不连续")
        values = [row["value_usd"] for row in rows]
        change = values[-1] - values[-2]
        if (summary.get("complete_window") is not True or
                summary.get("latest_month") != case["end_month"] or
                summary.get("latest_value_usd") != values[-1] or
                summary.get("month_change_usd") != change or
                summary.get("period_total_usd") != sum(values)):
            raise ValueError("程序摘要与逐月金额复算不一致")
        reference["directions"][flow] = {
            "metric": scope["metric"], "partner": scope["partner"],
            "dataset_version": scope["dataset_version"],
            "latest_value_usd": values[-1], "month_change_usd": change,
            "month_direction": "增加" if change > 0 else "减少" if change < 0 else "持平",
            "period_total_usd": sum(values),
            "highest_value_usd": max(values), "lowest_value_usd": min(values),
        }
    expected_flows = {"import", "export"} if case["flow"] == "both" else {case["flow"]}
    if set(reference["directions"]) != expected_flows:
        raise ValueError("评测报告缺少应有的贸易方向")
    return reference


def _scenarios(root: Path) -> list[dict]:
    body = json.loads((root / SCENARIOS).read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise ValueError("四题候选清单无效")
    cases = body.get("scenarios")
    if (body.get("schema_version") != "trade-model-v3-scenarios-v1" or
            body.get("status") != "candidate_not_frozen" or
            not isinstance(cases, list) or len(cases) != 4):
        raise ValueError("四题候选清单无效")
    if not all(isinstance(case, dict) for case in cases) or [
            case.get("id") for case in cases] != ["t1", "t2", "t3", "t4"]:
        raise ValueError("四题编号或顺序无效")
    for case in cases:
        if (set(case) != {"id", "question", "flow", "selected_product_id",
                          "start_month", "end_month", "expected_observation_ids"} or
                case["flow"] not in {"import", "export", "both"} or
                not re.fullmatch(rf"{case['flow']}:\d{{4}}", case["selected_product_id"])):
            raise ValueError("候选题范围字段无效")
    return cases


def build_candidate(root: Path, output: Path) -> dict:
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("输出目录已存在，不能覆盖已有题包")
    cases = _scenarios(root)
    output.mkdir(parents=True, exist_ok=False)
    hashes: dict[str, str] = {}
    _write(output, "scenarios.json", json.loads((root / SCENARIOS).read_text(encoding="utf-8")), hashes)
    entries: dict[str, dict] = {}
    for case in cases:
        sid, question = case["id"], case["question"]
        choice = prepare_trade_question(root, question)
        candidate = next((item for item in choice.get("candidates", [])
                          if item["id"] == case["selected_product_id"]), None)
        if choice.get("status") != "needs_product_choice" or candidate is None:
            raise ValueError(f"{sid}未返回预定的可确认官方商品候选")
        proposal = prepare_trade_question(root, question, selected_flow=case["flow"],
                                          selected_product_id=candidate["id"],
                                          catalog_version=choice["catalog_version"])
        if (proposal.get("status") != "ready" or proposal.get("flow") != case["flow"] or
                (proposal.get("start_month"), proposal.get("end_month")) !=
                (case["start_month"], case["end_month"])):
            raise ValueError(f"{sid}的方向或月份没有按预定范围确认")
        report = generate_trade_report(root, question, selected_flow=case["flow"],
                                       dataset_version=proposal["dataset_version"],
                                       selected_product_id=candidate["id"],
                                       catalog_version=choice["catalog_version"])
        digest = report_sha256(report)
        prompt = messages(report, digest)
        payload = json.loads(prompt[-1]["content"])
        if payload["required_observation_ids"] != case["expected_observation_ids"]:
            raise ValueError(f"{sid}没有按问题选中指定事实")
        reference = _independent_reference(report, case)
        _write(output, f"requests/{sid}/messages.json", prompt, hashes)
        _write(output, f"host_artifacts/{sid}/choice.json", candidate, hashes)
        _write(output, f"host_artifacts/{sid}/proposal.json", proposal, hashes)
        _write(output, f"host_artifacts/{sid}/report.json", report, hashes)
        _write(output, f"references/{sid}.json", reference, hashes)
        entries[sid] = {"question": question, "flow": case["flow"],
                        "selected_product_id": candidate["id"],
                        "catalog_version": choice["catalog_version"],
                        "dataset_version": proposal["dataset_version"],
                        "report_sha256": digest, "input_bytes": len(_json_bytes(prompt)),
                        "required_observation_ids": payload["required_observation_ids"]}
    manifest = {"schema_version": SCHEMA, "status": "candidate_only_not_frozen",
                "protocol": PROTOCOL, "api_calls": 0, "scenario_ids": [case["id"] for case in cases],
                "scenarios": entries, "files_sha256": hashes,
                "code_sha256": {str(path): _hash(root / path) for path in CODE_PATHS}}
    # The manifest is last: interrupted or partially written packages are not ready.
    (output / "MANIFEST.json").write_bytes(_json_bytes(manifest))
    verify_candidate(root, output)
    return {"output": str(output), "status": manifest["status"], "api_calls": 0,
            "input_bytes": {sid: item["input_bytes"] for sid, item in entries.items()}}


def verify_candidate(root: Path, output: Path) -> dict:
    root, output = Path(root).resolve(), Path(output).resolve()
    path = output / "MANIFEST.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("题包缺少最后写入的清单；视为未就绪")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or
            manifest.get("schema_version") != SCHEMA or
            manifest.get("status") != "candidate_only_not_frozen" or
            manifest.get("protocol") != PROTOCOL or manifest.get("api_calls") != 0 or
            manifest.get("scenario_ids") != ["t1", "t2", "t3", "t4"]):
        raise ValueError("题包清单状态或协议无效")
    expected = {"scenarios.json"}
    for sid in manifest["scenario_ids"]:
        expected.update((f"requests/{sid}/messages.json", f"host_artifacts/{sid}/choice.json",
                         f"host_artifacts/{sid}/proposal.json", f"host_artifacts/{sid}/report.json",
                         f"references/{sid}.json"))
    if set(manifest.get("files_sha256", {})) != expected:
        raise ValueError("题包文件清单缺失或多出文件")
    for rel, digest in manifest["files_sha256"].items():
        file = output / rel
        if (not file.is_file() or file.is_symlink() or
                not re.fullmatch(r"[0-9a-f]{64}", digest) or _hash(file) != digest):
            raise ValueError(f"题包文件缺失或摘要不符：{rel}")
    if manifest.get("code_sha256") != {str(p): _hash(root / p) for p in CODE_PATHS}:
        raise ValueError("题包所用代码或题目已变化，不能直接续跑")
    cases = _scenarios(root)
    if json.loads((output / "scenarios.json").read_text(encoding="utf-8")) != json.loads(
            (root / SCENARIOS).read_text(encoding="utf-8")):
        raise ValueError("题包题目与项目当前题目不一致")
    for case in cases:
        sid = case["id"]
        report = json.loads((output / f"host_artifacts/{sid}/report.json").read_text(encoding="utf-8"))
        prompt = json.loads((output / f"requests/{sid}/messages.json").read_text(encoding="utf-8"))
        reference = json.loads((output / f"references/{sid}.json").read_text(encoding="utf-8"))
        digest = report_sha256(report)
        if (manifest["scenarios"][sid]["report_sha256"] != digest or
                prompt != messages(report, digest) or
                reference != _independent_reference(report, case)):
            raise ValueError(f"{sid}报告、模型输入或独立参考不一致")
    return {"output": str(output), "status": manifest["status"], "scenarios": 4,
            "api_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = (verify_candidate(args.root, args.output) if args.verify else
              build_candidate(args.root, args.output))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
