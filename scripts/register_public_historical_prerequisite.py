"""Register an immutable historical Q1 review as a predecessor for v3 Q2."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_public_brief_eval as runner  # noqa: E402
from src.tradeintel_ai.public_eval_ledger import (  # noqa: E402
    DuplicatePublicRun,
    HISTORICAL_PREREQUISITE_EVENT,
    LedgerStateError,
    canonical_sha,
    file_sha256,
    load,
    register_historical_prerequisite,
    validate_review_checks,
)


QUESTION_IDS = ("q1", "q2", "q3", "q4")


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON必须是对象：" + str(path))
    return value


def _material_paths(source_package: Path, target_package: Path, *, source_run: Path,
                    source_raw: Path, source_freeze: Path, target_freeze: Path,
                    source_manifest: Path, target_manifest: Path,
                    source_review: Path) -> dict[str, str]:
    paths = {
        "source_run": source_run, "source_raw": source_raw,
        "source_freeze": source_freeze, "source_manifest": source_manifest,
        "target_freeze": target_freeze, "target_manifest": target_manifest,
        "source_review": source_review,
        "source_metadata": source_run.parent / "response-metadata.json",
    }
    for qid in QUESTION_IDS:
        paths[f"source_request_{qid}"] = source_package / "requests" / qid / "messages.json"
        paths[f"source_host_{qid}"] = source_package / "host_artifacts" / qid / "response.json"
        paths[f"target_request_{qid}"] = target_package / "requests" / qid / "messages.json"
        paths[f"target_host_{qid}"] = target_package / "host_artifacts" / qid / "response.json"
    return {key: str(Path(value).resolve()) for key, value in paths.items()}


def _hashes(paths: dict[str, str]) -> dict[str, str]:
    result = {}
    for name, raw_path in paths.items():
        path = Path(raw_path)
        if not path.is_file() or path.is_symlink():
            raise ValueError("历史前置材料缺失或是符号链接：" + name)
        result[name] = file_sha256(path)
    return result


def build_record(*, source_run_dir: Path, source_freeze_path: Path,
                 source_package: Path, source_review_path: Path,
                 target_freeze_path: Path, target_package: Path,
                 matrix_path: Path, target_provider_id: str,
                 ledger_root: Path) -> tuple[str, dict]:
    source_run_path = source_run_dir / "q1" / "run.json"
    source_raw_path = source_run_dir / "q1" / "raw-response.txt"
    source_run = _json(source_run_path)
    source_freeze = _json(source_freeze_path)
    target_freeze = _json(target_freeze_path)
    review = _json(source_review_path)
    if source_run.get("question_id") != "q1" or source_run.get("status") != "blocked_output_budget":
        raise ValueError("源运行必须是Q1 blocked_output_budget")
    if source_freeze.get("status") != "ready_for_formal":
        raise ValueError("源冻结必须保留ready_for_formal历史状态")
    if source_freeze.get("params", {}).get("budget_protocol", "v2") != "v2":
        raise ValueError("源冻结必须是v2历史协议")
    if target_freeze.get("status") != "ready_for_formal":
        raise ValueError("目标冻结必须是ready_for_formal")
    if target_freeze.get("params", {}).get("budget_protocol") != "v3":
        raise ValueError("目标冻结必须是v3")
    if review.get("schema_version") != "public-brief-historical-review-v1":
        raise ValueError("审阅文件schema不正确")
    if review.get("source_run_id") != source_run.get("run_id") or review.get("verdict") not in {"pass", "minor_error"}:
        raise ValueError("审阅文件未绑定源运行或判定不可继续")
    checks = review.get("checks")
    validate_review_checks(checks, review["verdict"])
    ledger = load(ledger_root)
    events = [e for e in ledger["events"] if e.get("run_id") == source_run.get("run_id")]
    started = [e for e in events if e.get("event") == "started"]
    terminal = [e for e in events if e.get("event") == "blocked_output_budget"]
    if len(started) != 1 or len(terminal) != 1 or events[-1].get("event") != "blocked_output_budget":
        raise ValueError("源运行在项目账本中必须有唯一started和blocked_output_budget")
    source_start = started[0]
    if source_start.get("question_id") != "q1" or source_start.get("metadata", {}).get("output_dir") != str(source_run_dir.resolve()):
        raise ValueError("源运行产物路径与账本不一致")
    if terminal[0].get("raw_sha256") != source_run.get("raw_sha256"):
        raise ValueError("源账本终态与run摘要不一致")
    if source_start.get("metadata", {}).get("package_manifest_sha256") != source_freeze.get("package_manifest_sha256"):
        raise ValueError("源manifest与账本不一致")
    source_provider = source_freeze.get("provider", {})
    try:
        source_response = _json(source_package / "host_artifacts/q1/response.json")
        source_raw_text = source_raw_path.read_text(encoding="utf-8")
        source_parsed = runner.parse_public(source_raw_text, source_response["report"])
        source_metadata = _json(source_run_dir / "q1" / "response-metadata.json")
        if source_metadata != source_run.get("response_metadata") or source_metadata.get("finish_reason") != "stop":
            raise ValueError("源响应元数据不一致或未完整结束")
        source_v3_budget = runner._output_budget(
            source_raw_text, source_metadata.get("usage", {}), max_tokens=8192,
            max_bytes=65536, budget_protocol=runner.BUDGET_PROTOCOL_V3,
            body_max_chars=runner.MAX_BODY_CHARS, parsed=source_parsed)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("源Q1无法通过当前解析器和v3预算预检") from exc
    if source_parsed.get("status") != "manual_review_required" or not source_v3_budget["within_gate"]:
        raise ValueError("源Q1当前解析器或v3预算预检未通过")
    target_provider = runner.preflight(matrix_path=matrix_path, package_path=target_package,
                                       provider_id=target_provider_id)["provider"]
    runner.verify_freeze(freeze=target_freeze, provider=target_provider,
                         package_path=target_package, matrix_path=matrix_path)
    target_provider_frozen = target_freeze.get("provider", {})
    for key in ("temperature", "max_tokens", "thinking", "reasoning_effort"):
        if source_freeze.get("params", {}).get(key) != target_freeze.get("params", {}).get(key):
            raise ValueError("源/目标生成参数不一致：" + key)
    for key in ("model_id", "base_url", "request_params", "reasoning_effort"):
        if source_provider.get(key) != target_provider_frozen.get(key):
            raise ValueError("源/目标模型参数不一致：" + key)
    source_prefix = source_start.get("base_key", "").rsplit(":", 1)[0]
    source_manifest_sha = file_sha256(source_package / "MANIFEST.json")
    if source_manifest_sha != source_freeze.get("package_manifest_sha256"):
        raise ValueError("源manifest文件与源冻结不一致")
    if source_run.get("freeze_sha256") != canonical_sha(source_freeze):
        raise ValueError("源run与源冻结摘要不一致")
    if source_prefix != source_manifest_sha + ":" + source_start.get("metadata", {}).get("provider_digest", ""):
        raise ValueError("源base_key与manifest/provider摘要不一致")
    target_manifest_sha = file_sha256(target_package / "MANIFEST.json")
    target_provider_digest = runner.canonical_sha({"provider_id": target_provider["id"], "execution_channel": "real_api"})
    target_prefix = target_manifest_sha + ":" + target_provider_digest
    paths = _material_paths(source_package, target_package, source_run=source_run_path,
                            source_raw=source_raw_path, source_freeze=source_freeze_path,
                            target_freeze=target_freeze_path,
                            source_manifest=source_package / "MANIFEST.json",
                            target_manifest=target_package / "MANIFEST.json",
                            source_review=source_review_path)
    hashes = _hashes(paths)
    source_manifest = _json(source_package / "MANIFEST.json")
    for qid in QUESTION_IDS:
        for kind, relative in (("request", f"requests/{qid}/messages.json"),
                               ("host", f"host_artifacts/{qid}/response.json")):
            if source_manifest.get("files_sha256", {}).get(relative) != hashes[f"source_{kind}_{qid}"]:
                raise ValueError("历史材料与源manifest不一致：" + relative)
    if source_run.get("request_sha256") != hashes["source_request_q1"]:
        raise ValueError("历史首题实际请求与源材料不一致")
    for qid in QUESTION_IDS:
        if hashes[f"source_request_{qid}"] != hashes[f"target_request_{qid}"]:
            raise ValueError("源/目标送模消息不一致：" + qid)
        if hashes[f"source_host_{qid}"] != hashes[f"target_host_{qid}"]:
            raise ValueError("源/目标程序报告不一致：" + qid)
    # A target run in the ledger would make this registration ambiguous.
    if any(e.get("base_key", "").startswith(target_prefix + ":") for e in ledger["events"]):
        raise ValueError("目标配置已经有运行记录，不能补登记历史前置")
    record = {
        "source_run_id": source_run["run_id"],
        "source_manifest_sha256": source_manifest_sha,
        "source_freeze_sha256": canonical_sha(source_freeze),
        "target_manifest_sha256": target_manifest_sha,
        "target_freeze_sha256": canonical_sha(target_freeze),
        "target_provider_digest": target_provider_digest,
        "review_sha256": hashes["source_review"],
        "reviewer": review.get("reviewer", ""),
        "ai_assisted": bool(review.get("ai_assisted")),
        "verdict": review["verdict"],
        "checks": checks,
        "artifact_paths": paths,
        "artifact_hashes": hashes,
        "source_status": source_run["status"],
        "target_budget_protocol": "v3",
        "source_v3_budget": source_v3_budget,
    }
    return target_prefix, record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--source-freeze", type=Path, required=True)
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--source-review", type=Path, required=True)
    parser.add_argument("--target-freeze", type=Path, required=True)
    parser.add_argument("--target-package", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--target-provider-id", required=True)
    parser.add_argument("--ledger-root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true", help="仅核查材料，不写入账本")
    args = parser.parse_args()
    try:
        prefix, record = build_record(
            source_run_dir=args.source_run_dir.resolve(), source_freeze_path=args.source_freeze.resolve(),
            source_package=args.source_package.resolve(), source_review_path=args.source_review.resolve(),
            target_freeze_path=args.target_freeze.resolve(), target_package=args.target_package.resolve(),
            matrix_path=args.matrix.resolve(), target_provider_id=args.target_provider_id,
            ledger_root=args.ledger_root.resolve())
        if args.dry_run:
            print(json.dumps({"status": "preflight_passed", "target_prefix": prefix, "api_calls": 0}))
            return 0
        event = register_historical_prerequisite(args.ledger_root.resolve(), target_prefix=prefix,
                                                  question_id="q1", record=record)
    except (ValueError, OSError, json.JSONDecodeError, LedgerStateError, DuplicatePublicRun) as exc:
        print(json.dumps({"status":"error", "error":str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status":"registered", "event":HISTORICAL_PREREQUISITE_EVENT,
                      "target_prefix":prefix, "api_calls":0},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
