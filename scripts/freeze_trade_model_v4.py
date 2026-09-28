"""Build or verify the current v4 trade-explanation development packet offline.

Only cases/<id>/messages.json is model-visible. No provider client is imported.
The four cases are a development value gate, not unseen/blind model accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any

from tradeintel_ai.trade_explanation import report_sha256
from tradeintel_ai.trade_explanation_v4 import (
    MAX_INPUT_BYTES, PROTOCOL, build_snapshot, messages, snapshot_sha256,
)
from tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question
from tradeintel_ai.trade_report_store import _verify as verify_record
from tradeintel_ai.trade_report_store import create_record, load_record, public_state


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = Path("evals/trade_model_v4/scenarios.json")
SCHEMA = "trade-model-v4-development-freeze-v1"
IDS = ("v4-1", "v4-2", "v4-3", "v4-4")
CASE_FILES = ("choice.json", "proposal.json", "record.json", "page_state.json",
              "messages.json", "reference.json", "baseline.zh-CN.txt")
CODE_PATHS = (
    "src/tradeintel_ai/trade_query_flow.py",
    "src/tradeintel_ai/trade_classification_catalog.py",
    "src/tradeintel_ai/trade_data_repository.py",
    "src/tradeintel_ai/trade_export_repository.py",
    "src/tradeintel_ai/trade_explanation.py",
    "src/tradeintel_ai/trade_explanation_v4.py",
    "src/tradeintel_ai/trade_report_store.py",
    "src/tradeintel_ai/response_contract.py",
    "src/tradeintel_ai/web_app.py",
    "scripts/freeze_trade_model_v4.py",
    str(SCENARIOS),
)
DATA_PATHS = (
    "data/processed/trade_hts10/manifest.json",
    "data/processed/trade_scheduleb10/manifest.json",
    "data/processed/trade_classification/manifest.json",
)
SCORING = {
    "schema_version": "trade-model-v4-development-scoring-v1",
    "status": "development_value_gate_not_blind",
    "baseline": "当前页面的月度数据、图表、程序说明和全部关系卡；不是空白页面",
    "per_answer_fields": ["interface_result", "contract_pass", "factual_fidelity",
                          "answers_question", "reading_gain_over_page", "severe_error",
                          "reviewer", "review_note"],
    "reading_gain_rule": "先写只看页面能得到的结论；模型仅换词复述关系卡、增加套话或重复免责声明记0",
    "development_gate": "四题全部完成且无严重错误，并有至少两题相对页面有明确阅读增益，才考虑横评",
    "candidate_config_rule": "横评配置四题全部完成、无严重错误、至少三题有明确阅读增益，才称本开发集候选",
    "stop_rule": "严重事实错误、合同失败或未知结果立即停止该配置余题；不自动重试",
    "reporting_rule": "逐题公开完成/合同/事实/回答/增益及失败原因；不称盲测或普遍准确率",
    "severe_errors": ["商品或方向错误", "编造数字日期或来源", "局部变化说成全期趋势",
                      "金额误称数量或价格", "相关误称政策因果", "确定性投资建议"],
}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    return _hash_bytes(path.read_bytes())


def _write(output: Path, rel: str, value: Any, hashes: dict[str, str]) -> None:
    path = output / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = value.encode("utf-8") if isinstance(value, str) else _json_bytes(value)
    path.write_bytes(body)
    hashes[rel] = _hash_bytes(body)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenarios(root: Path) -> list[dict[str, Any]]:
    body = _load_json(root / SCENARIOS)
    if not isinstance(body, dict):
        raise ValueError("v4 四题定义无效")
    cases = body.get("scenarios")
    if (body.get("schema_version") != "trade-model-v4-scenarios-v1" or
            body.get("status") != "developer_value_gate_not_blind" or
            not isinstance(cases, list) or [case.get("id") for case in cases] != list(IDS)):
        raise ValueError("v4 四题定义或顺序无效")
    for case in cases:
        if (set(case) != {"id", "question", "flow", "selected_product_id",
                          "start_month", "end_month", "expected_eligible_card_ids"} or
                case["flow"] not in {"import", "export", "both"} or
                not isinstance(case["question"], str) or
                not re.fullmatch(rf"{case['flow']}:\d{{4}}", case["selected_product_id"]) or
                (case["start_month"], case["end_month"]) != ("2025-08", "2026-07") or
                not isinstance(case["expected_eligible_card_ids"], list) or
                not case["expected_eligible_card_ids"]):
            raise ValueError(f"{case.get('id')} 范围字段无效")
    return cases


def _parts(report: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    return ((report["import_report"], report["export_report"])
            if report.get("kind") == "trade-query-both-v1" else (report,))


def _reference(report: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Recompute basic comparison facts from monthly rows, not card prose."""
    question, code = case["question"], case["selected_product_id"].split(":", 1)[1]
    if report.get("question") != question or report.get("scope", {}).get("question") != question:
        raise ValueError("顶层报告原问题与确认范围不一致")
    flows: dict[str, Any] = {}
    for part in _parts(report):
        scope, rows, summary = part["scope"], part["series"], part["summary"]
        flow = scope.get("flow")
        if (part.get("question") != question or scope.get("question") != question or
                scope.get("product_code") != code or
                (scope.get("start_month"), scope.get("end_month")) !=
                (case["start_month"], case["end_month"]) or
                flow in flows or not isinstance(rows, list) or len(rows) != 12):
            raise ValueError("子报告问题、商品、方向或月份与题目不一致")
        expected_months = [f"2025-{month:02d}" for month in range(8, 13)] + [
            f"2026-{month:02d}" for month in range(1, 8)]
        if any(row.get("month") != month or row.get("status") != "observed" or
               type(row.get("value_usd")) is not int or row["value_usd"] < 0
               for row, month in zip(rows, expected_months)):
            raise ValueError("逐月序列缺月、未观察或金额无效")
        values = [row["value_usd"] for row in rows]
        latest_change = values[-1] - values[-2]
        if (summary.get("complete_window") is not True or
                summary.get("latest_month") != "2026-07" or
                summary.get("latest_value_usd") != values[-1] or
                summary.get("month_change_usd") != latest_change or
                summary.get("period_total_usd") != sum(values)):
            raise ValueError("报告摘要与逐月金额独立复算不一致")
        flows[flow] = {
            "metric": scope["metric"], "partner": scope["partner"],
            "dataset_version": scope["dataset_version"],
            "latest_value_usd": values[-1], "latest_change_usd": latest_change,
            "last_three_months_usd": values[-3:],
            "last_two_changes_usd": [values[-2] - values[-3], latest_change],
            "period_total_usd": sum(values),
            "observed_high_usd": max(values), "observed_low_usd": min(values),
        }
    expected_flows = {"import", "export"} if case["flow"] == "both" else {case["flow"]}
    if set(flows) != expected_flows:
        raise ValueError("报告缺少预定方向")
    return {"question": question, "selected_product_id": case["selected_product_id"],
            "window": [case["start_month"], case["end_month"]], "directions": flows,
            "policy_causality": "金额变化本身不足以证明政策原因" if case["id"] == "v4-4" else None}


def _baseline(record: dict[str, Any]) -> str:
    report, snapshot = record["report"], record["relation_snapshot"]
    scope = report["scope"]
    lines = [f"问题：{report['question']}",
             f"确认商品：{scope['product_label']}（{scope['product_code']}）",
             f"方向：{scope['flow']}；月份：{scope['start_month']}—{scope['end_month']}",
             "", "页面在模型调用前已有的关系卡："]
    lines += [f"- {card['id']}：{card['fact']}" for card in snapshot["cards"]]
    lines += ["", "程序报告已有的说明："]
    for part in _parts(report):
        lines.extend(f"- {part['scope']['flow']}：{note}" for note in part.get("notes", []))
    lines += ["", "完整月度数据、图表所依赖的值和页面状态见同题 page_state.json。",
              "本文件不是模型输入；评分时先读本基线，再判断模型是否带来阅读增益。", ""]
    return "\n".join(lines)


def _expected_files() -> set[str]:
    return {"scenarios.json", "SCORING.json"} | {
        f"cases/{sid}/{name}" for sid in IDS for name in CASE_FILES}


def freeze(root: Path, output: Path) -> dict[str, Any]:
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("冻结目录已存在，不能覆盖")
    cases = _scenarios(root)
    output.mkdir(parents=True, exist_ok=False)
    hashes: dict[str, str] = {}
    _write(output, "scenarios.json", _load_json(root / SCENARIOS), hashes)
    _write(output, "SCORING.json", SCORING, hashes)
    entries: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="trade-v4-freeze-store-") as temporary:
        store_root = Path(temporary)
        for case in cases:
            sid, question, cid = case["id"], case["question"], case["selected_product_id"]
            choice_reply = prepare_trade_question(root, question)
            choice = next((item for item in choice_reply.get("candidates", [])
                           if item["id"] == cid), None)
            if choice_reply.get("status") != "needs_product_choice" or choice is None:
                raise ValueError(f"{sid} 没有返回预定商品确认候选")
            proposal = prepare_trade_question(root, question, selected_flow=case["flow"],
                                              selected_product_id=cid,
                                              catalog_version=choice_reply["catalog_version"])
            if (proposal.get("status") != "ready" or proposal.get("flow") != case["flow"] or
                    (proposal.get("start_month"), proposal.get("end_month")) !=
                    (case["start_month"], case["end_month"])):
                raise ValueError(f"{sid} 商品、方向或月份未按预定范围确认")
            report = generate_trade_report(root, question, selected_flow=case["flow"],
                                           selected_product_id=cid,
                                           catalog_version=choice_reply["catalog_version"],
                                           dataset_version=proposal["dataset_version"])
            reference = _reference(report, case)
            created = create_record(store_root, report, explanation_protocol=PROTOCOL)
            record = load_record(store_root, created["report_id"])
            snapshot = record["relation_snapshot"]
            if (record["explanation"]["status"] != "not_requested" or
                    snapshot["eligible_card_ids"] != case["expected_eligible_card_ids"]):
                raise ValueError(f"{sid} 非新 v4 记录或可解释关系卡发生变化")
            prompt = messages(report, snapshot, record["relation_snapshot_sha256"])
            if len(_json_bytes(prompt)) > MAX_INPUT_BYTES:
                raise ValueError(f"{sid} 模型请求超出输入预算")
            page = public_state(record)
            prefix = f"cases/{sid}/"
            for name, value in (("choice.json", choice), ("proposal.json", proposal),
                                ("record.json", record), ("page_state.json", page),
                                ("messages.json", prompt), ("reference.json", reference),
                                ("baseline.zh-CN.txt", _baseline(record))):
                _write(output, prefix + name, value, hashes)
            entries[sid] = {"question": question, "selected_product_id": cid,
                            "report_id": record["report_id"],
                            "report_sha256": record["report_sha256"],
                            "relation_snapshot_sha256": record["relation_snapshot_sha256"],
                            "catalog_version": choice_reply["catalog_version"],
                            "dataset_version": proposal["dataset_version"],
                            "input_bytes": len(_json_bytes(prompt)),
                            "eligible_card_ids": snapshot["eligible_card_ids"]}
    manifest = {"schema_version": SCHEMA, "status": "frozen_inputs_no_model_results",
                "protocol": PROTOCOL, "development_not_blind": True,
                "model_calls": 0, "model_results": 0, "scenario_ids": list(IDS),
                "scenarios": entries, "files_sha256": hashes,
                "code_sha256": {rel: _hash_file(root / rel) for rel in CODE_PATHS},
                "data_manifest_sha256": {rel: _hash_file(root / rel) for rel in DATA_PATHS}}
    # An interrupted package has no manifest and cannot be treated as ready.
    (output / "MANIFEST.json").write_bytes(_json_bytes(manifest))
    verify_frozen(root, output)
    return {"output": str(output), "status": manifest["status"], "model_calls": 0,
            "input_bytes": {sid: entries[sid]["input_bytes"] for sid in IDS}}


def verify_frozen(root: Path, output: Path) -> dict[str, Any]:
    root, output = Path(root).resolve(), Path(output).resolve()
    manifest_path = output / "MANIFEST.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("冻结包缺少最后写入的清单，视为未就绪")
    manifest = _load_json(manifest_path)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA or
            manifest.get("status") != "frozen_inputs_no_model_results" or
            manifest.get("protocol") != PROTOCOL or
            manifest.get("development_not_blind") is not True or
            manifest.get("model_calls") != 0 or manifest.get("model_results") != 0 or
            manifest.get("scenario_ids") != list(IDS) or
            set(manifest.get("files_sha256", {})) != _expected_files()):
        raise ValueError("冻结包状态、协议或文件清单无效")
    files = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
    if files != _expected_files() | {"MANIFEST.json"}:
        raise ValueError("冻结包有缺失或未登记文件")
    for rel, digest in manifest["files_sha256"].items():
        path = output / rel
        if (path.is_symlink() or not path.is_file() or
                not re.fullmatch(r"[0-9a-f]{64}", digest) or _hash_file(path) != digest):
            raise ValueError(f"冻结文件缺失或摘要不符：{rel}")
    if (manifest.get("code_sha256") != {rel: _hash_file(root / rel) for rel in CODE_PATHS} or
            manifest.get("data_manifest_sha256") !=
            {rel: _hash_file(root / rel) for rel in DATA_PATHS}):
        raise ValueError("冻结时所用代码或数据清单与当前工作区不一致")
    if _load_json(output / "scenarios.json") != _load_json(root / SCENARIOS):
        raise ValueError("冻结题目与当前定义不一致")
    if _load_json(output / "SCORING.json") != SCORING:
        raise ValueError("冻结评分标准不一致")
    for case in _scenarios(root):
        sid = case["id"]
        prefix = output / "cases" / sid
        choice, proposal = _load_json(prefix / "choice.json"), _load_json(prefix / "proposal.json")
        record = _load_json(prefix / "record.json")
        page, prompt = _load_json(prefix / "page_state.json"), _load_json(prefix / "messages.json")
        reference = _load_json(prefix / "reference.json")
        verify_record(record, record["report_id"])
        report = record["report"]
        if (record.get("explanation_protocol") != PROTOCOL or
                record["explanation"]["status"] != "not_requested" or
                record["relation_snapshot"]["eligible_card_ids"] !=
                case["expected_eligible_card_ids"] or
                choice["id"] != case["selected_product_id"] or
                proposal["selected_product_id"] != choice["id"] or
                proposal["catalog_version"] != manifest["scenarios"][sid]["catalog_version"] or
                proposal["dataset_version"] != manifest["scenarios"][sid]["dataset_version"] or
                record["report_sha256"] != manifest["scenarios"][sid]["report_sha256"] or
                record["relation_snapshot_sha256"] !=
                manifest["scenarios"][sid]["relation_snapshot_sha256"] or
                page != public_state(record) or
                prompt != messages(report, record["relation_snapshot"],
                                   record["relation_snapshot_sha256"]) or
                reference != _reference(report, case) or
                (prefix / "baseline.zh-CN.txt").read_text(encoding="utf-8") !=
                _baseline(record) or
                manifest["scenarios"][sid]["input_bytes"] != len(_json_bytes(prompt))):
            raise ValueError(f"{sid} 报告、范围、页面、请求或参考不一致")
    return {"output": str(output), "status": manifest["status"], "scenarios": 4,
            "model_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = (verify_frozen(args.root, args.output) if args.verify else
              freeze(args.root, args.output))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
