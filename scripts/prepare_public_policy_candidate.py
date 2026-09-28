"""Build the isolated policy Q3 candidate package without calling a provider.

This package is deliberately separate from the historical four-question
trade package.  It changes the output contract, so it gets its own manifest
and freeze instead of silently changing an old run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_public_eval_diagnostic import estimate_input_tokens  # noqa: E402
from src.tradeintel_ai.session_explanation import build_public_snapshot  # noqa: E402

PACKAGE_SCHEMA = "public-policy-service-candidate-v1"
PROTOCOL = "public-policy-explanation-prototype-v2"
QUESTION_ID = "q3"
SCENARIOS = ROOT / "evals/public_brief_v1/scenarios.json"


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _scenario() -> dict[str, object]:
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]
    item = next((item for item in scenarios if item.get("id") == QUESTION_ID), None)
    if not isinstance(item, dict):
        raise ValueError("固定材料缺少q3")
    return item


def build_candidate(*, source_package: Path, output: Path) -> dict[str, object]:
    source = Path(source_package).resolve()
    out = Path(output).resolve()
    if out.exists():
        raise ValueError("输出目录已存在；候选包不会覆盖旧材料")
    response_path = source / "host_artifacts" / QUESTION_ID / "response.json"
    if not response_path.is_file():
        raise ValueError("源服务包缺少q3程序响应")
    response = json.loads(response_path.read_text(encoding="utf-8"))
    question = str(_scenario()["question"])
    snapshot = build_public_snapshot(response, question=question, mode="policy")
    if snapshot["protocol"] != PROTOCOL or snapshot["mode"] != "policy":
        raise ValueError("政策快照协议未接入")
    estimate = estimate_input_tokens(snapshot["messages"])
    if estimate["tokens"] > estimate["hard"]:
        raise ValueError("政策q3输入超过16000硬门")
    reference_path = source / "references" / f"{QUESTION_ID}.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8")) if reference_path.is_file() else {}
    reference = {**reference, "required_points": _scenario().get("required_points", [])}
    host_artifacts = {
        "response.json": response,
        "snapshot.json": snapshot,
        "reference.json": reference,
    }
    files: dict[str, str] = {}
    files["requests/q3/messages.json"] = _write_json(out / "requests/q3/messages.json", snapshot["messages"])
    for name, value in host_artifacts.items():
        files[f"host_artifacts/q3/{name}"] = _write_json(out / f"host_artifacts/q3/{name}", value)
    manifest = {
        "schema_version": PACKAGE_SCHEMA,
        "status": "candidate_only_not_frozen",
        "protocol": PROTOCOL,
        "api_calls": 0,
        "question_ids": [QUESTION_ID],
        "question": question,
        "data_version": response.get("data_version"),
        "input_estimate": estimate,
        "files_sha256": files,
        "code_sha256": {},
    }
    code_paths = [
        ROOT / "scripts/prepare_public_policy_candidate.py",
        ROOT / "scripts/run_public_policy_eval.py",
        ROOT / "src/tradeintel_ai/public_policy_explanation.py",
        ROOT / "src/tradeintel_ai/session_explanation.py",
        ROOT / "src/tradeintel_ai/public_report.py",
        ROOT / "src/tradeintel_ai/interpretation_review_store.py",
        ROOT / "src/tradeintel_ai/model_adapter.py",
        ROOT / "src/tradeintel_ai/public_eval_ledger.py",
        ROOT / "src/tradeintel_ai/public_policy_eval_ledger.py",
        SCENARIOS,
    ]
    manifest["code_sha256"] = {
        str(path.relative_to(ROOT)): _sha_bytes(path)
        for path in sorted(code_paths)
    }
    _write_json(out / "MANIFEST.json", manifest)
    return {
        "output": str(out),
        "status": manifest["status"],
        "protocol": PROTOCOL,
        "input_tokens": estimate["tokens"],
        "api_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="已存在的离线服务包，只读取其中的q3程序响应")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_candidate(source_package=args.source, output=args.output),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
