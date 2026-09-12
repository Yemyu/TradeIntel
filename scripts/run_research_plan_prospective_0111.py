"""Bounded, human-reviewed runner for the frozen 0111 question set.

The default is an offline preflight.  Online execution requires all of
``--execute``, ``--allow-online``, a new output directory and an interactive
reviewer.  The reference file is shown only to that human reviewer and is
never included in the model messages.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.research_models import ResearchPlannerModel, ResearchPolicyModel
from tradeintel_ai.unified_research import build_product_workflow
from scripts.preflight_research_plan_prospective_0111 import (
    QUESTIONS, REFERENCE, preflight,
)

FROZEN_PREFLIGHT = ROOT / "docs/experiments/research-plan-prospective-0111/preflight.json"

FIXED_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
FIXED_MODEL = "glm-4.7"
MAX_PLANNING_CALLS = 24
MAX_POLICY_CALLS = 8


def require_online_review():
    """0112: incomplete protocol must not reach credentials or provider code."""
    raise ValueError("0112: prospective 0111 audit failed; online execution disabled")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _config_snapshot(config: OpenAICompatibleConfig) -> dict:
    return {
        "base_url": config.base_url,
        "model": config.model,
        "timeout_seconds": config.timeout_seconds,
        "temperature": config.temperature,
        "stream": False,
    }


def validate_online_config(config: OpenAICompatibleConfig) -> None:
    if (config.base_url != FIXED_BASE_URL or config.model != FIXED_MODEL
            or config.timeout_seconds != 60 or config.temperature != 0):
        raise ValueError("0111 online run requires the frozen GLM-4.7/temperature-0/60s configuration")
    if not config.api_key or not config.api_key.isascii() or any(ch.isspace() for ch in config.api_key):
        raise ValueError("invalid model key")


def load_frozen_set() -> tuple[list[dict], dict, dict]:
    if not FROZEN_PREFLIGHT.is_file():
        raise ValueError("0111 frozen preflight report is missing")
    stored = json.loads(FROZEN_PREFLIGHT.read_text(encoding="utf-8"))
    report = preflight()
    if (stored.get("version") != report.get("version")
            or stored.get("sha256") != report.get("sha256")
            or stored.get("counts") != report.get("counts")
            or stored.get("question_count") != report.get("question_count")):
        raise ValueError("0111 frozen preflight no longer matches the current checkout")
    questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    return questions, reference, stored


def _review(interactive, *, question: dict, reference: dict, stage: str,
            artifact: dict, output: Path) -> dict:
    packet = {
        "question": deepcopy(question),
        "stage": stage,
        "reference_for_human_only": deepcopy(reference),
        "artifact": deepcopy(artifact),
        "output": str(output),
        "instruction": (
            "参考只供审查者使用，不会发送给模型。请核对问题是否被完整保留、"
            "范围/比较方向/证据/拒答边界是否正确；必须给出理由，不能只凭文件存在通过。"
        ),
    }
    decision = interactive(deepcopy(packet))
    if not isinstance(decision, dict) or set(decision) != {"approved", "reason"}:
        raise ValueError("reviewer must return exactly approved and reason")
    if type(decision["approved"]) is not bool or not isinstance(decision["reason"], str) \
            or not decision["reason"].strip():
        raise ValueError("reviewer decision requires a boolean and non-empty reason")
    return {"stage": stage, "approved": decision["approved"],
            "reason": decision["reason"], "reference_id": question["id"]}


def run_online(config: OpenAICompatibleConfig, output: Path, *, interactive,
               reviewer_id: str) -> dict:
    require_online_review()
    validate_online_config(config)
    if output.exists():
        raise ValueError("refusing to overwrite an existing prospective run")
    if not callable(interactive) or not reviewer_id.strip():
        raise ValueError("interactive reviewer and reviewer ID are required")
    questions, reference, frozen_report = load_frozen_set()
    output.mkdir(parents=True, exist_ok=False)
    ledger = {
        "version": "research-plan-prospective-0111-run-1",
        "status": "running",
        "online_run": True,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "question_count": len(questions),
        "max_planning_calls": MAX_PLANNING_CALLS,
        "max_policy_calls": MAX_POLICY_CALLS,
        "planning_calls": 0,
        "policy_calls": 0,
        "completed": 0,
        "questions": [],
        "model_adopted": False,
        "semantic_scores": None,
        "configuration": _config_snapshot(config),
        "automatic_retry": False,
        "control_b": "not_run_in_0111_main_batch",
        "reviewer_id": reviewer_id.replace(config.api_key, "[REDACTED]"),
        "frozen_preflight": deepcopy(frozen_report),
    }
    _write(output / "ledger.json", ledger)
    try:
        for question in questions:
            qid = question["id"]
            ref = reference[qid]
            case_dir = output / qid
            case_dir.mkdir()
            item = {"id": qid, "category": question["category"],
                    "question": question["question"], "status": "started",
                    "planning_attempted": False, "policy_attempted": False,
                    "reviews": []}
            ledger["questions"].append(item)
            ledger["planning_calls"] += 1
            if ledger["planning_calls"] > MAX_PLANNING_CALLS:
                raise RuntimeError("planning budget exceeded")
            planner = ResearchPlannerModel(config)
            workflow = build_product_workflow(planner, planner_source_kind="live",
                                               allow_host_gap_review=False)
            item["planning_attempted"] = True
            preview = workflow.prepare(question["question"],
                                       audit_output=case_dir / "planning",
                                       secret=config.api_key)
            _write(case_dir / "preview.json", preview)
            item["preview_status"] = preview.get("status")
            _write(output / "ledger.json", ledger)

            if question["category"] == "support":
                if preview.get("status") != "needs_confirmation":
                    item["status"] = "planning_failed"
                    raise RuntimeError(f"{qid}: support plan did not reach confirmation")
                plan_review = _review(interactive, question=question, reference=ref,
                                      stage="plan", artifact=preview, output=case_dir)
                item["reviews"].append(plan_review)
                if not plan_review["approved"]:
                    item["status"] = "plan_rejected"
                    raise RuntimeError(f"{qid}: reviewer rejected plan")
                policy = None
                if "policy" in ref.get("tasks", []):
                    ledger["policy_calls"] += 1
                    if ledger["policy_calls"] > MAX_POLICY_CALLS:
                        raise RuntimeError("policy-generation budget exceeded")
                    policy = ResearchPolicyModel(config)
                    item["policy_attempted"] = True
                result = workflow.confirm(preview["confirmation_token"],
                                          case_dir / "delivery", model=policy,
                                          source_kind="live", secret=config.api_key)
                _write(case_dir / "result.json", result)
                answer_review = _review(interactive, question=question, reference=ref,
                                        stage="answer", artifact=result, output=case_dir)
                item["reviews"].append(answer_review)
                if not answer_review["approved"]:
                    item["status"] = "answer_rejected"
                    raise RuntimeError(f"{qid}: reviewer rejected answer")
                item["status"] = "accepted_under_review"
            else:
                # Clarification and boundary questions must never be confirmed.
                if preview.get("status") in {"needs_confirmation", "research_draft", "trade_draft"}:
                    item["status"] = "unsafe_execution_path"
                    raise RuntimeError(f"{qid}: non-support question reached executable status")
                review = _review(interactive, question=question, reference=ref,
                                 stage="terminal", artifact=preview, output=case_dir)
                item["reviews"].append(review)
                if not review["approved"]:
                    item["status"] = "terminal_rejected"
                    raise RuntimeError(f"{qid}: reviewer rejected terminal handling")
                item["status"] = "accepted_under_review"
            ledger["completed"] += 1
            _write(output / "ledger.json", ledger)
    except (Exception, KeyboardInterrupt) as exc:
        ledger["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "stopped"
        ledger["stop_reason"] = type(exc).__name__ + (": " + str(exc) if str(exc) else "")
        ledger["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write(output / "ledger.json", ledger)
        return deepcopy(ledger)
    ledger["status"] = "main_batch_complete"
    ledger["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write(output / "ledger.json", ledger)
    return deepcopy(ledger)


def _interactive_reviewer(packet: dict) -> dict:
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    answer = input("逐项核对后输入 yes 通过，其他内容拒绝：").strip().lower()
    reason = input("请写出核对理由：").strip()
    return {"approved": answer == "yes" and bool(reason), "reason": reason or "未提供理由"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true", help="只做零API冻结检查")
    parser.add_argument("--execute", action="store_true", help="启动受监督在线批次")
    parser.add_argument("--allow-online", action="store_true",
                        help="额外确认允许在线调用；不会自动读取或保存密钥")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reviewer", default="interactive-user")
    args = parser.parse_args(argv)
    if args.preflight or not args.execute:
        report = preflight()
        report.update(online_eligible=False, review_decision="0112",
                      acceptance_status="audit_failed",
                      limitation="Structural/reference preflight only; question semantics and online protocol are not approved.")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if not args.allow_online:
        parser.error("在线执行必须同时提供 --execute --allow-online；本次没有询问密钥")
    try:
        require_online_review()
    except ValueError:
        print("0112审查未通过：此验收入口已禁用在线执行；无需输入密钥。")
        return 2
    if args.output is None or not sys.stdin.isatty():
        parser.error("在线批次需要全新的 --output 和交互式终端")
    key = os.environ.get("TRADEINTEL_MODEL_API_KEY") or getpass.getpass(
        "GLM API key（隐藏输入，不保存）：")
    config = OpenAICompatibleConfig.from_env({**os.environ, "TRADEINTEL_MODEL_API_KEY": key})
    try:
        result = run_online(config, args.output, interactive=_interactive_reviewer,
                            reviewer_id=args.reviewer)
    except (ValueError, OSError) as exc:
        print(f"0111运行前检查失败，未开始在线批次：{type(exc).__name__}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "main_batch_complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
