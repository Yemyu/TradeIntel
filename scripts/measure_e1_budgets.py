#!/usr/bin/env python3
"""Measure real main-case input budgets for E1 (offline; no model calls).

Builds the v3 fact catalog for the frozen primary case exactly like the
existing preparation pipeline, then estimates both the raw v3 messages and
the new compact business view request.  Results are written as a JSON
measurement record under tmp/handoff-runs/ for the R1 review packet.

This script does not touch the old G2 packages, ledgers or frozen inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tradeintel_ai.policy_cases import CASES
from tradeintel_ai.repository import EvidenceRepository, DataPaths
from tradeintel_ai.exposure_version_store import ExposureVersionStore, pin_repository
from tradeintel_ai.policy_exposure_tools import get_policy_exposure_series
from tradeintel_ai.exposure_policy import retrieve_exposure_policy
from tradeintel_ai.primary_fact_sheet import build_primary_fact_sheet
from tradeintel_ai.evidence_bundle import build_evidence_bundle
from src.tradeintel_ai.brief_fact_catalog import build_fact_catalog, render_fact_catalog, validate_fact_catalog
from src.tradeintel_ai.evidence_linked_brief import messages as v3_messages
from src.tradeintel_ai.brief_business_view import build_view, view_request
from scripts.prepare_brief_v3_offline import estimate_input_tokens

PRIMARY = "us_301_review2025_tungsten_solar"


def build_primary_catalog(month: str, product: str | None, focus: str) -> tuple[dict, dict]:
    case = CASES[PRIMARY]
    repo = pin_repository(EvidenceRepository(DataPaths(ROOT)), policy_id=PRIMARY)
    store = ExposureVersionStore(ROOT, ROOT / case.versions)
    version = store.active_version()
    if version is None:
        raise SystemExit("primary case has no active version; refusing to guess")
    task = dict(policy_id=PRIMARY, month=month, product=product or "all", focus=focus,
                task="monthly_exposure", schema_version="research-request-v2",
                policy_view="archived_event")
    from tradeintel_ai.structured_task import compile_task
    question, _ = compile_task(task)
    trade = get_policy_exposure_series(policy_id=PRIMARY, hts8=product,
                                       start=month, end=month, repository=repo)
    evidence = retrieve_exposure_policy(repo.paths.root, question, as_of="2026-09-15")
    facts = build_primary_fact_sheet(evidence, repo.exposure_version, root=repo.paths.root)
    bundle = build_evidence_bundle(trade, facts, focus=focus)
    return build_fact_catalog(bundle), {"question": question, "version": version}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default="2026-07")
    parser.add_argument("--product", default=None)
    parser.add_argument("--focus", default="contrast",
                        choices=["china_amount", "china_share", "contrast"])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    catalog, meta = build_primary_catalog(args.month, args.product, args.focus)
    validate_fact_catalog(catalog)
    question = meta["question"]
    raw = v3_messages(question, catalog)
    view, sidecar = build_view(question, catalog)
    view_messages = view_request(view)
    raw_estimate = estimate_input_tokens(raw)
    view_estimate = estimate_input_tokens(view_messages)

    record = {
        "schema_version": "e1-budget-measurement-v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "offline_measurement_no_model",
        "api_calls": 0,
        "case": {"policy_id": PRIMARY, "month": args.month, "product": args.product or "all",
                 "focus": args.focus, "active_version": meta["version"]},
        "catalog_sha256": catalog["catalog_sha256"],
        "fact_count": len(catalog["facts"]),
        "observation_count": len(catalog["observations"]),
        "source_count": len(catalog["sources"]),
        "estimates": {
            "v3_messages_raw": raw_estimate,
            "business_view_request": view_estimate,
            "gates": {"input_target_tokens": 8000, "input_hard_tokens": 16000,
                      "output_max_tokens": 2000, "timeout_seconds": 90},
        },
        "view_sidecar_summary": {
            "id_map_size": len(sidecar["id_map"]),
            "removed_machine_fields": len(sidecar["removed_fields"]),
            "shared_fields": len(sidecar["shared_fields"]),
            "hoisted_fields": [entry["field"] for entry in sidecar["hoisted"]],
            "shared_clauses": len(view["shared_clauses"]),
        },
        "restore_verified": __import__("src.tradeintel_ai.brief_business_view", fromlist=["restore"]).restore(view, sidecar)
        == __import__("src.tradeintel_ai.brief_business_view", fromlist=["business_payload"]).business_payload(catalog),
        "boundary": "保守token估算（非供应商usage）；未调用模型；不改旧G2。",
    }
    output = args.output
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        output = ROOT / "tmp/handoff-runs" / f"{stamp}-e1-budget-measurement"
    output.mkdir(parents=True, exist_ok=True)
    (output / "measurement.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    catalog_path = output / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    view_path = output / "business-view.json"
    view_path.write_text(json.dumps(view, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sidecar_path = output / "business-view-sidecar.json"
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = output / "program-report-A3.zh-CN.md"
    report_path.write_text(render_fact_catalog(catalog), encoding="utf-8")
    record["artifact_files_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (catalog_path, view_path, sidecar_path, report_path)
    }
    (output / "measurement.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["estimates"], ensure_ascii=False, indent=2))
    print(json.dumps({"restore_verified": record["restore_verified"],
                      "output_dir": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
