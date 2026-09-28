#!/usr/bin/env python3
"""Prepare the bounded S3 AI experiment package without calling a model.

The package contains deterministic evidence bundles, compact requests and
separate human-readable references. References are intentionally never placed
in ``messages.json``. The script refuses to overwrite an existing directory.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.announcement_flow import (load_announcement_store,
    resolve_policy_binding, load_trade_coverage)
from src.tradeintel_ai.announcement_report import (build_announcement_policy_facts,
    query_bound_trade)
from src.tradeintel_ai.brief_fact_catalog import build_fact_catalog, render_fact_catalog, validate_fact_catalog
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle

SCHEMA = "s3-experiment-package-v1"
EXPERIMENT_ID = "s3-r2-20260920"
R2_ROOT = ROOT / "tmp/r2-20260920/astra-semantic-review-2/temp-root"
R2_POLICY = "r2_semiconductor_2025"
R2_DOC = "docver-cbb131783801bd95"
R2_CANDIDATE = "d252d295ae0280ffd51ec0ed8a92c0c4b3edf1ef971055f44b76d3a52c1b3727"
R2_CODES = ["28046100", "38180000"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_r2_bundle(path: Path) -> None:
    store = load_announcement_store(R2_ROOT, R2_POLICY)
    binding = resolve_policy_binding(R2_ROOT, R2_POLICY, R2_DOC, R2_CANDIDATE,
                                     month="2026-07", requested_codes=R2_CODES)
    coverage = load_trade_coverage(store, R2_DOC, binding["trade_coverage_digest"])
    candidate = store["announcement_candidates"][R2_DOC]["candidate"]
    trade = query_bound_trade(R2_ROOT, announcement_policy_id=R2_POLICY,
                              source_case_id=coverage["source_case_id"],
                              requested_codes=R2_CODES, month="2026-07",
                              data_version=binding["data_version"])
    policy = build_announcement_policy_facts(store, R2_DOC, candidate,
                                              binding["data_version"], R2_CODES)
    bundle = build_evidence_bundle(trade, policy, focus="contrast")
    validate_fact_catalog(build_fact_catalog(bundle))
    write_json(path, bundle)


def run_prepare(bundle: Path, question: str, output: Path, *, deduplicate: bool = False) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    command = [sys.executable, str(ROOT / "scripts/prepare_brief_view_offline.py"),
               "--bundle", str(bundle), "--question", question, "--output", str(output)]
    if deduplicate:
        command.append("--deduplicate")
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True,
                               capture_output=True, check=False)
    if completed.returncode not in (0, 2):
        raise RuntimeError(f"准备 {output.name} 失败：{completed.stdout}\n{completed.stderr}")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("api_calls") != 0 or manifest.get("network_calls") != 0:
        raise RuntimeError("S3准备阶段出现模型或网络调用")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/s3-20260920")
    parser.add_argument("--deduplicate-r2", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    experiment_id = EXPERIMENT_ID + ("-dedup1" if args.deduplicate_r2 else "")
    if output.exists():
        raise SystemExit(f"拒绝覆盖已有S3目录：{output}")
    output.mkdir(parents=True)
    inputs = output / "inputs"
    packages = output / "packages"
    references = output / "references"
    inputs.mkdir(); packages.mkdir(); references.mkdir()

    specs = [
        ("D1-r2-selected", inputs / "r2-selected-evidence-bundle.json",
         "政策 r2_semiconductor_2025 在 2026-07 对已覆盖的 28046100 和 38180000 做结构化解释，必须区分本次初始 0%、既有 50%、2027 年未来未知增幅，并说明 2/18 范围。"),
        ("Q1-primary-all", ROOT / "tmp/g2-preparation-20260915-ready-inputs/primary_all/evidence-bundle.json",
         "解释 2026-06 全部五个商品的金额和中国来源占比观察，指出它们分别代表什么，不能把份额写成替代能力。"),
        ("Q2-primary-single", ROOT / "tmp/g2-preparation-20260915-ready-inputs/primary_single/evidence-bundle.json",
         "只解释 2026-05 商品 81019910 的观察；如果所选范围内占比为 100%，必须说明 100% 仅指本次所选范围，不代表整个市场。"),
        ("Q3-r2-selected", inputs / "r2-selected-evidence-bundle.json",
         "解释 R2 公告在已覆盖的两个商品上的贸易暴露，并清楚区分初始增量、既有措施、未来拟调整和 FTZ 条件；只给出证据支持的研究重点。"),
    ]
    # The R2 bundle is built once and used by D1/Q3. It is kept as an input,
    # while package manifests still bind their own catalog/view hashes.
    build_r2_bundle(specs[0][1])
    records = []
    for name, bundle, question in specs:
        package = packages / name
        manifest = run_prepare(bundle, question, package,
                               deduplicate=args.deduplicate_r2 and name in {"D1-r2-selected", "Q3-r2-selected"})
        reference = references / f"{name}.reference.zh-CN.md"
        reference.write_text(
            "# 人工参考（不进入模型请求）\n\n" +
            f"实验：{name}\n\n" +
            "下面的 A3 程序基准只用于人工逐条核对模型回答；它不是训练数据。\n\n" +
            (package / "program-report-A3.zh-CN.md").read_text(encoding="utf-8") +
            "\n## AI审阅硬门\n\n"
            "不得把美国进口写成全球进口；不得把中国份额写成替代能力；不得把事后统计写成政策发布时预测；unknown不得补零。\n"
            "必须解释一个观察为何不同或一致、给出一个有范围限制的研究重点、指出一个与数据缺口直接相关的后续数据需求。\n",
            encoding="utf-8")
        records.append({"id": name, "package": str(package.relative_to(ROOT)),
                        "question": question, "package_manifest_sha256": sha(package / "manifest.json"),
                        "reference_sha256": sha(reference), "input_estimate": manifest["input_estimate"]})

    # Q4 is deliberately a zero-call gate: it has no callable package because
    # the official 18-code scope is partial in the published July snapshot.
    q4 = references / "Q4-r2-full.blocked.json"
    write_json(q4, {"id": "Q4-r2-full", "status": "blocked_before_model_call",
                    "requested_codes": 18, "covered_codes": 2, "missing_codes": 16,
                    "required_model_calls": 0,
                    "reason": "贸易覆盖不是exact；不得删掉16个商品来制造全范围答案。"})

    package_manifest = {
        "schema_version": SCHEMA, "experiment_id": experiment_id,
        "api_calls": 0, "network_calls": 0, "credential_used": False,
        "packages": records, "blocked_case": {"id": "Q4-r2-full", "reference": str(q4.relative_to(ROOT))},
        "budget": {"development_calls": 2, "formal_c_calls": 3, "blocked_calls": 0,
                   "total_max_calls": 5, "input_hard_tokens": 16000,
                   "output_max_tokens": 2000, "timeout_seconds": 90},
        "boundary": "D1为已见迁移题；Q1-Q3是小样本功能验收，不支持泛化准确率或统计显著提升。参考答案不进入messages。",
        "ledger": {"stub": f".local/experiments/provider-ledger-{experiment_id}-stub.json",
                   "real": f".local/experiments/provider-ledger-{experiment_id}-real.json"},
    }
    write_json(output / "s3-manifest.json", package_manifest)
    print(json.dumps(package_manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
