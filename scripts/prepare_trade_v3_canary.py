"""Prepare or verify one soybean-export v3 development case, without API calls.

This package is for checking the product/provider boundary once before the
four-question comparison. It is never a scored answer or a retry permit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradeintel_ai.trade_explanation import PROTOCOL, messages, report_sha256
from tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question

from scripts.prepare_trade_model_eval import _independent_reference, _json_bytes, _hash, _write


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "trade-v3-development-canary-v1"
CASE = {
    "id": "dev-soybean-export",
    "question": "最近美国大豆出口有什么变化？",
    "flow": "export",
    "selected_product_id": "export:1201",
    "start_month": "2025-08",
    "end_month": "2026-07",
    "expected_observation_ids": ["export.trend"],
}
MODEL_REQUEST = {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "reasoning": "high",
    "temperature": 0,
    "max_tokens": 2048,
    "thinking": "enabled",
    "total_deadline_seconds": 90,
    "maximum_api_calls": 1,
    "retry": False,
}
CODE_PATHS = (
    Path("scripts/prepare_trade_v3_canary.py"),
    Path("scripts/run_trade_v3_canary.py"),
    Path("scripts/prepare_trade_model_eval.py"),
    Path("src/tradeintel_ai/trade_query_flow.py"),
    Path("src/tradeintel_ai/trade_classification_catalog.py"),
    Path("src/tradeintel_ai/trade_data_repository.py"),
    Path("src/tradeintel_ai/trade_export_repository.py"),
    Path("src/tradeintel_ai/trade_explanation.py"),
    Path("src/tradeintel_ai/response_contract.py"),
)
FILES = {
    "case.json", "requests/messages.json", "host_artifacts/choice.json",
    "host_artifacts/proposal.json", "host_artifacts/report.json", "reference.json",
}


def build(root: Path, output: Path) -> dict:
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("开发题包目录已存在，不能覆盖")
    output.mkdir(parents=True, exist_ok=False)
    choice = prepare_trade_question(root, CASE["question"])
    candidate = next((item for item in choice.get("candidates", [])
                      if item["id"] == CASE["selected_product_id"]), None)
    if choice.get("status") != "needs_product_choice" or candidate is None:
        raise ValueError("大豆出口没有返回预定的可确认官方商品候选")
    proposal = prepare_trade_question(root, CASE["question"],
                                      selected_flow=CASE["flow"],
                                      selected_product_id=candidate["id"],
                                      catalog_version=choice["catalog_version"])
    if (proposal.get("status") != "ready" or proposal.get("flow") != CASE["flow"] or
            (proposal.get("start_month"), proposal.get("end_month")) !=
            (CASE["start_month"], CASE["end_month"])):
        raise ValueError("开发题月份或贸易方向没有按预定范围确认")
    report = generate_trade_report(root, CASE["question"], selected_flow=CASE["flow"],
                                   dataset_version=proposal["dataset_version"],
                                   selected_product_id=candidate["id"],
                                   catalog_version=choice["catalog_version"])
    digest = report_sha256(report)
    prompt = messages(report, digest)
    payload = json.loads(prompt[-1]["content"])
    if payload["required_observation_ids"] != CASE["expected_observation_ids"]:
        raise ValueError("开发题没有选中预定事实")
    reference = _independent_reference(report, CASE)
    hashes: dict[str, str] = {}
    for rel, value in (
        ("case.json", CASE), ("requests/messages.json", prompt),
        ("host_artifacts/choice.json", candidate),
        ("host_artifacts/proposal.json", proposal),
        ("host_artifacts/report.json", report), ("reference.json", reference),
    ):
        _write(output, rel, value, hashes)
    manifest = {
        "schema_version": SCHEMA,
        "status": "development_only_not_authorized_to_call",
        "protocol": PROTOCOL,
        "api_calls": 0,
        "case_id": CASE["id"],
        "report_sha256": digest,
        "dataset_version": proposal["dataset_version"],
        "catalog_version": choice["catalog_version"],
        "input_bytes": len(_json_bytes(prompt)),
        "model_request": MODEL_REQUEST,
        "files_sha256": hashes,
        "code_sha256": {str(rel): _hash(root / rel) for rel in CODE_PATHS},
    }
    # A missing manifest makes an interrupted preparation unusable.
    (output / "MANIFEST.json").write_bytes(_json_bytes(manifest))
    verify(root, output)
    return {"output": str(output), "status": manifest["status"],
            "input_bytes": manifest["input_bytes"], "api_calls": 0}


def verify(root: Path, output: Path) -> dict:
    root, output = Path(root).resolve(), Path(output).resolve()
    path = output / "MANIFEST.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("开发题包缺少完成清单；不能运行")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA or
            manifest.get("status") != "development_only_not_authorized_to_call" or
            manifest.get("protocol") != PROTOCOL or manifest.get("api_calls") != 0 or
            manifest.get("case_id") != CASE["id"] or
            manifest.get("model_request") != MODEL_REQUEST or
            not isinstance(manifest.get("files_sha256"), dict) or
            set(manifest["files_sha256"]) != FILES):
        raise ValueError("开发题包清单、预算或授权状态无效")
    for rel, digest in manifest["files_sha256"].items():
        item = output / rel
        if (not item.is_file() or item.is_symlink() or
                not isinstance(digest, str) or len(digest) != 64 or
                any(char not in "0123456789abcdef" for char in digest) or
                _hash(item) != digest):
            raise ValueError(f"开发题包文件缺失或摘要不符：{rel}")
    if manifest.get("code_sha256") != {str(rel): _hash(root / rel) for rel in CODE_PATHS}:
        raise ValueError("开发题包所用代码已变化，需要另建新包")
    case = json.loads((output / "case.json").read_text(encoding="utf-8"))
    report = json.loads((output / "host_artifacts/report.json").read_text(encoding="utf-8"))
    prompt = json.loads((output / "requests/messages.json").read_text(encoding="utf-8"))
    reference = json.loads((output / "reference.json").read_text(encoding="utf-8"))
    digest = report_sha256(report)
    if (case != CASE or manifest.get("report_sha256") != digest or
            prompt != messages(report, digest) or
            reference != _independent_reference(report, CASE) or
            manifest.get("input_bytes") != len(_json_bytes(prompt))):
        raise ValueError("开发题包的范围、报告、消息或参考不一致")
    return {"output": str(output), "status": manifest["status"],
            "api_calls": 0, "input_bytes": manifest["input_bytes"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.output) if args.verify else
                     build(args.root, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
