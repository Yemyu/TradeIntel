"""Freeze the four v3 candidate questions and evaluation rubric, offline only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from scripts.prepare_trade_model_eval import _hash, _json_bytes, verify_candidate


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "trade-model-eval-v3-frozen-v1"
CANDIDATE_FILES = {
    "scenarios.json",
    *(f"requests/{sid}/messages.json" for sid in ("t1", "t2", "t3", "t4")),
    *(f"host_artifacts/{sid}/{name}.json" for sid in ("t1", "t2", "t3", "t4")
      for name in ("choice", "proposal", "report")),
    *(f"references/{sid}.json" for sid in ("t1", "t2", "t3", "t4")),
}
EXTRA_FILES = {"SOURCE_CANDIDATE_MANIFEST.json", "SCORING.json", "MODEL_MATRIX.json"}
FROZEN_FILES = CANDIDATE_FILES | EXTRA_FILES
SCORING = {
    "schema_version": "trade-model-answer-rubric-v1",
    "per_question_fields": [
        "interface_result", "contract_pass", "factual_fidelity",
        "answers_the_question", "helpfulness_and_readability", "reviewer_note",
    ],
    "field_values": {
        "interface_result": ["complete", "rejected", "unknown_outcome", "not_run"],
        "boolean_fields": ["contract_pass", "factual_fidelity",
                           "answers_the_question", "helpfulness_and_readability"],
    },
    "question_pass_rule": "complete AND contract_pass AND factual_fidelity AND answers_the_question AND helpfulness_and_readability",
    "severe_failure_examples": [
        "商品或进出口方向错误", "编造金额、日期、数据来源或因果关系",
        "把贸易金额当成贸易数量", "给出确定性投资建议或预测",
    ],
    "stop_rule": "一题发生严重事实错误、合同失败或结果未知，停止该模型余题；不自动重试，不修改已保存原答。",
    "reporting_rule": "只报告完成题数/4、通过题数/完成题数及未运行数；不称总体准确率，不把程序解析拦截记成模型正确。",
    "review_rule": "结构校验与内容审阅分列；审阅者、渠道、是否盲评和备注必须记明；未由用户确认不得写用户已采纳。",
}
MODEL_MATRIX = {
    "schema_version": "trade-model-candidate-matrix-v1",
    "status": "candidate_configurations_pending_individual_preflight",
    "candidates": [
        {"id": "codex-gpt-6-luna-max", "channel": "Codex对话", "model": "GPT-6 Luna",
         "reasoning": "max", "planned_formal_questions": 4,
         "completed_formal_answers": 0, "status": "pending"},
        {"id": "codex-gpt-6-sol-high", "channel": "Codex对话", "model": "GPT-6 Sol",
         "reasoning": "high", "planned_formal_questions": 4,
         "completed_formal_answers": 0, "status": "pending"},
        {"id": "deepseek-flash-high", "channel": "DeepSeek API", "model": "deepseek-flash",
         "reasoning": "thinking enabled / high", "planned_formal_questions": 4,
         "completed_formal_answers": 0, "development_answers_excluded": 1,
         "status": "formal run pending"},
        {"id": "glm-4.6v-default", "channel": "GLM API", "model": "glm-4.6v",
         "reasoning": "default only; current product config does not expose high",
         "planned_formal_questions": 4, "completed_formal_answers": 0,
         "status": "pending parameter preflight"},
        {"id": "deepseek-v4-pro-high", "channel": "DeepSeek API", "model": "deepseek-v4-pro",
         "reasoning": "thinking enabled / high",
         "planned_formal_questions": 4, "completed_formal_answers": 0,
         "status": "conditional on availability and distinguishable response model"},
    ],
    "excluded": [
        {"model": "GLM-4.5-Air", "reason": "此前按用户决定停止"},
        {"model": "Qwen", "reason": "此前已从本轮测试计划移除"},
    ],
    "limits": "Codex对话基准与API成绩分开展示；实际返回型号别名不能证明底层模型快照。API候选最多各4题，遇停止条件立即结束。",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_manifest(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("评测清单格式无效")
    return value


def freeze(root: Path, candidate: Path, output: Path) -> dict:
    root, candidate, output = map(lambda item: Path(item).resolve(), (root, candidate, output))
    verify_candidate(root, candidate)
    candidate_manifest_path = candidate / "MANIFEST.json"
    candidate_manifest = _load_manifest(candidate_manifest_path)
    if (candidate_manifest.get("status") != "candidate_only_not_frozen" or
            candidate_manifest.get("api_calls") != 0):
        raise ValueError("输入必须是尚未调用模型的四题候选包")
    if output.exists():
        raise FileExistsError("冻结目录已存在，不能覆盖")
    output.mkdir(parents=True, exist_ok=False)
    for rel in sorted(CANDIDATE_FILES):
        source = candidate / rel
        destination = output / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination, follow_symlinks=False)
    shutil.copyfile(candidate_manifest_path, output / "SOURCE_CANDIDATE_MANIFEST.json",
                    follow_symlinks=False)
    (output / "SCORING.json").write_bytes(_json_bytes(SCORING))
    (output / "MODEL_MATRIX.json").write_bytes(_json_bytes(MODEL_MATRIX))
    file_hashes = {rel: _hash(output / rel) for rel in FROZEN_FILES}
    manifest = {
        "schema_version": SCHEMA,
        "status": "frozen_inputs_only_no_model_results",
        "frozen_at": _stamp(),
        "protocol": candidate_manifest["protocol"],
        "api_calls_in_freeze": 0,
        "source_candidate_manifest_sha256": _hash(candidate_manifest_path),
        "source_report_sha256_by_scenario": {
            sid: candidate_manifest["scenarios"][sid]["report_sha256"]
            for sid in ("t1", "t2", "t3", "t4")},
        "scenario_ids": ["t1", "t2", "t3", "t4"],
        "files_sha256": file_hashes,
        "freeze_script_sha256": _hash(root / "scripts/freeze_trade_model_eval.py"),
        "code_sha256": candidate_manifest["code_sha256"],
        "model_results": 0,
    }
    # The final manifest is the readiness marker and is written last.
    (output / "MANIFEST.json").write_bytes(_json_bytes(manifest))
    verify_frozen(root, candidate, output)
    return {"output": str(output), "status": manifest["status"],
            "scenarios": 4, "model_results": 0, "api_calls_in_freeze": 0}


def verify_frozen(root: Path, candidate: Path, output: Path) -> dict:
    root, candidate, output = map(lambda item: Path(item).resolve(), (root, candidate, output))
    verify_candidate(root, candidate)
    manifest_path = output / "MANIFEST.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("正式冻结包没有完成清单")
    manifest = _load_manifest(manifest_path)
    if (manifest.get("schema_version") != SCHEMA or
            manifest.get("status") != "frozen_inputs_only_no_model_results" or
            manifest.get("protocol") != "trade-data-explanation-v3" or
            manifest.get("api_calls_in_freeze") != 0 or manifest.get("model_results") != 0 or
            manifest.get("scenario_ids") != ["t1", "t2", "t3", "t4"] or
            set(manifest.get("files_sha256", {})) != FROZEN_FILES):
        raise ValueError("正式冻结包状态或文件清单无效")
    if _hash(candidate / "MANIFEST.json") != manifest.get("source_candidate_manifest_sha256"):
        raise ValueError("冻结包的源候选清单不一致")
    source = _load_manifest(candidate / "MANIFEST.json")
    if manifest.get("code_sha256") != source.get("code_sha256"):
        raise ValueError("冻结包代码基线与候选材料不一致")
    for rel, digest in manifest["files_sha256"].items():
        path = output / rel
        if (not path.is_file() or path.is_symlink() or _hash(path) != digest):
            raise ValueError(f"冻结材料缺失或摘要不符：{rel}")
    if json.loads((output / "SCORING.json").read_text(encoding="utf-8")) != SCORING:
        raise ValueError("冻结评分标准不一致")
    if json.loads((output / "MODEL_MATRIX.json").read_text(encoding="utf-8")) != MODEL_MATRIX:
        raise ValueError("冻结模型候选配置不一致")
    for rel in CANDIDATE_FILES:
        if (output / rel).read_bytes() != (candidate / rel).read_bytes():
            raise ValueError(f"冻结包改变了候选输入：{rel}")
    if _hash(root / "scripts/freeze_trade_model_eval.py") != manifest.get("freeze_script_sha256"):
        raise ValueError("冻结脚本已变化，需重新核验")
    return {"output": str(output), "status": manifest["status"],
            "scenarios": 4, "model_results": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = (verify_frozen(args.root, args.candidate, args.output) if args.verify else
              freeze(args.root, args.candidate, args.output))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
