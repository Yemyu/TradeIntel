"""Prepare a production-shaped, offline four-question evaluation candidate.

The candidate uses the server scope proposal builder and the deterministic
report builder.  The model-facing directory contains only the exact messages;
the independent reference directory is computed directly from the pinned
release snapshot and never reads the generated report or model answer.
No provider is called by this script.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from tradeintel_ai.analysis_request import validate_analysis_request
from tradeintel_ai.exposure_version_store import ExposureVersionStore
from tradeintel_ai.policy_cases import CASES
from tradeintel_ai.public_brief_explanation import messages
from tradeintel_ai.scope_proposal import propose_scope
from tradeintel_ai.session_brief import build_temporal_session_brief
from tradeintel_ai.session_explanation import build_public_snapshot

POLICY = "us_301_review2025_tungsten_solar"
ROOT = Path(__file__).resolve().parents[1]
VERSION = "91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b"


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value: Any) -> str:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return _sha_bytes(raw)


def _snapshot(root: Path) -> tuple[ExposureVersionStore, dict[str, Any], str]:
    case = CASES[POLICY]
    store = ExposureVersionStore(root, root / case.versions)
    version = store.active_version()
    if version != VERSION:
        raise ValueError("活动版本与评测锁定版本不同；停止，不自动更换题包数据")
    snap = store.load_snapshot(version)
    store.release_root(version)
    return store, snap, version


def _independent_reference(release: Path, request: dict[str, Any], *, scenario: str) -> dict[str, Any]:
    """Compute reference facts from the release table, not from response/evidence."""
    window = request["window"]
    latest = window["anchor_month"]
    products = list(request["products"])
    sources = {}
    def rows_for(month: str) -> dict[str, dict[str, Any]]:
        relative = f"{CASES[POLICY].monthly}/{POLICY}_{month.replace('-', '_')}.csv"
        path = release / relative
        sources[relative] = _sha_bytes(path.read_bytes())
        totals = {}
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                code = row["canonical_hts8"]
                if code not in products:
                    continue
                if row["policy_id"] != POLICY or f"{int(row['year']):04d}-{int(row['month']):02d}" != month:
                    raise ValueError("参考明细政策/月不一致")
                value = int(row["import_value_consumption_usd"])
                if value < 0:
                    raise ValueError("参考明细含负金额")
                total = totals.setdefault(code, {"hts8": code, "all_origins_value_usd": 0, "china_value_usd": 0})
                total["all_origins_value_usd"] += value
                if row["origin_code"] == "5700":
                    total["china_value_usd"] += value
        if set(totals) != set(products):
            raise ValueError("独立参考缺少所选商品，不补零")
        for total in totals.values():
            denominator = total["all_origins_value_usd"]
            total["china_share_percent"] = (str(Decimal(total["china_value_usd"]) * 100 / denominator)
                                              if denominator else None)
        return totals
    latest_rows = rows_for(latest)
    reference: dict[str, Any] = {
        "schema_version": "public-brief-reference-v1",
        "scenario_id": scenario,
        "policy_id": request["policy_id"],
        "data_version": request["data_version"],
        "window": dict(window),
        "products": products,
        "latest_month": latest,
        "latest_rows": {code: latest_rows.get(code) for code in products},
        "requested_comparisons": list(request.get("comparisons") or []),
        "source_files_sha256": sources,
        "method": "直接累加发布CSV的HTS10/来源地金额；中国来源代码5700；份额分母为同商品全部来源金额",
        "comparison_caveat": "跨期比较是否可解释以 evidence.comparability 为准；未知不能补成趋势。",
        "price_data_available": False,
    }
    if scenario == "q2":
        prior = request["window"].get("anchor_month")
        year = int(prior[:4]) - 1
        month = prior[5:]
        reference["prior_month"] = f"{year:04d}-{month}"
        reference["prior_rows"] = {code: rows_for(reference["prior_month"]).get(code) for code in products}
        absolute = int(latest[:4]) * 12 + int(latest[5:]) - 2
        previous_month = f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
        previous = rows_for(previous_month)["38180000"]
        reference["one_month_before_latest"] = previous
        reference["mom_base_month"] = previous_month
        reference["mom_percent"] = {
            field: (str((Decimal(latest_rows['38180000'][field]) / previous[field] - 1) * 100)
                    if previous[field] else None)
            for field in ("all_origins_value_usd", "china_value_usd")}
    if scenario == "q4":
        reference["price_conclusion"] = "不可由当前进口金额、来源占比和政策原文推出终端价格涨跌。"
    return reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise SystemExit(f"output already exists: {out}")
    out.mkdir(parents=True)
    (out / "requests").mkdir()
    (out / "references").mkdir()
    (out / "host_artifacts").mkdir()
    store, snapshot, version = _snapshot(ROOT)
    scenarios = json.loads((ROOT / "evals/public_brief_v1/scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    q1_request: dict[str, Any] | None = None
    q1_response: dict[str, Any] | None = None
    manifest: dict[str, Any] = {"schema_version": "public-brief-candidate-manifest-v1", "api_calls": 0,
                                "data_version": version, "scenarios": {}}
    for item in scenarios:
        scenario = item["id"]
        parent = q1_request if scenario == "q2" else None
        override = None
        if scenario == "q2":
            override = dict(parent or {})
            override["original_question"] = item["question"]
            override["products"] = list(item["selection"])
        proposal = propose_scope(ROOT, original_question=item["question"], policy_id=POLICY,
                                 selected_products=item["selection"], parent_request=parent,
                                 request_override=override)
        request = validate_analysis_request(proposal["request"])
        if scenario == "q1":
            q1_request = request
        response = build_temporal_session_brief(ROOT, request, data_version=version)
        if scenario == "q1":
            q1_response = response
        request_context = None
        if scenario == "q2":
            if q1_request is None or q1_response is None:
                raise ValueError("Q2缺少Q1程序上下文")
            observations = q1_response["evidence"].get("observations") or []
            anchor = q1_request["window"]["anchor_month"]
            ranked = sorted(observations, key=lambda obs: (
                0 if (obs.get("scope") or {}).get("period") == anchor else 1,
                0 if obs.get("kind") == "comparison" else 1,
                str(obs.get("id"))))
            summary = [{"observation_id": obs["id"], "kind": obs["kind"],
                        "period": str((obs.get("scope") or {}).get("period") or ""),
                        "fact_sentence": str(obs.get("fact_sentence") or "")[:220]}
                       for obs in ranked if obs.get("fact_sentence")][:8]
            from tradeintel_ai.session_store import request_digest
            request_context = {
                "schema_version": "public-request-context-v1",
                "kind": "prior_program_report",
                "parent_request_digest": request_digest(q1_request),
                "parent_data_version": q1_request["data_version"],
                "parent_task_id": "candidate-q1-program-report",
                "parent_window": dict(q1_request["window"]),
                "selected_products": list(request["products"]),
                "summary": summary,
            }
        snapshot_packet = build_public_snapshot(response, question=item["question"],
                                                request_context=request_context)
        model_messages = messages(item["question"], response["report"],
                                  policy_context=response.get("policy_context"),
                                  request_context=request_context)
        if model_messages != snapshot_packet["messages"]:
            raise ValueError(f"message builder mismatch: {scenario}")
        qdir = out / "requests" / scenario
        hdir = out / "host_artifacts" / scenario
        qdir.mkdir(); hdir.mkdir()
        hashes = {
            "messages.json": _write_json(qdir / "messages.json", model_messages),
            "proposal.json": _write_json(hdir / "proposal.json", proposal),
            "request.json": _write_json(hdir / "request.json", request),
            "response.json": _write_json(hdir / "response.json", response),
            "snapshot.json": _write_json(hdir / "snapshot.json", snapshot_packet),
        }
        if request_context is not None:
            hashes["request_context.json"] = _write_json(hdir / "request_context.json", request_context)
        reference = _independent_reference(store.release_root(version), request, scenario=scenario)
        reference["required_points"] = item["required_points"]
        metrics = {metric["id"]: metric for metric in response["evidence"]["metrics"]}
        for code, row in reference["latest_rows"].items():
            for suffix, field in (("world", "all_origins_value_usd"), ("china", "china_value_usd")):
                actual = metrics[f"metric:{code}:{reference['latest_month']}:{suffix}"]["value"]
                if Decimal(str(actual)) != Decimal(row[field]):
                    raise ValueError(f"独立复算与生产证据不一致：{scenario}/{code}/{field}")
        reference["production_amount_comparison"] = "passed"
        ref_hash = _write_json(out / "references" / f"{scenario}.json", reference)
        from scripts.prepare_public_eval_diagnostic import estimate_input_tokens
        estimate = estimate_input_tokens(model_messages)
        if estimate["tokens"] > estimate["hard"]:
            raise ValueError(f"{scenario} 超过输入预算硬门")
        manifest["scenarios"][scenario] = {"question": item["question"], "hashes": hashes,
                                             "input_estimate": estimate,
                                             "reference_sha256": ref_hash,
                                             "message_bytes": (qdir / "messages.json").stat().st_size}
    # Manifest is intentionally the final file written so an interrupted run
    # cannot look complete.
    manifest["status"] = "candidate_only_not_frozen"
    manifest["blockers"] = [
        "browser_flow_not_verified",
        "service_generation_not_verified",
        "announcement_flow_not_verified",
        "provider_parameters_not_frozen",
    ]
    manifest["note"] = "候选材料未调用模型；参考与候选输入物理分开。"
    _write_json(out / "MANIFEST.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
