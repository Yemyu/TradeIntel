#!/usr/bin/env python3
"""Prepare the ACTUAL compact-protocol request package (offline; no provider).

Unlike the legacy v3 preparation, this command persists the request that is
really going to be sent: the readable compact business view plus the complete
C output contract as the system prompt.  Only this actual request passes the
budget hard gate; the raw v3 message size is recorded as a diagnostic and
never gates.  The manifest is written last and lists a non-empty required
file set with hashes, so an interrupted directory can never look ready.

Files:
    catalog.json / business-view.json / business-view-sidecar.json /
    messages.json (actual request) / program-report-A3.zh-CN.md /
    manifest.json

Never modifies old frozen packages; refuses to overwrite an existing output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.brief_business_view import build_view, view_request
from src.tradeintel_ai.brief_fact_catalog import (build_fact_catalog,
                                                  render_fact_catalog,
                                                  validate_fact_catalog)
from src.tradeintel_ai.evidence_linked_brief import messages as raw_v3_messages
from scripts.prepare_brief_v3_offline import estimate_input_tokens

MANIFEST_SCHEMA = "brief-view-offline-manifest-v1"
READY_STATUS = "prepared_view_no_model_result"
INPUT_TARGET_TOKENS = 8000
INPUT_HARD_TOKENS = 16000
OUTPUT_MAX_TOKENS = 2000
TIMEOUT_SECONDS = 90
REQUIRED_FILES = ("catalog.json", "business-view.json", "business-view-sidecar.json",
                  "messages.json", "program-report-A3.zh-CN.md")


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deduplicate", action="store_true",
                        help="Losslessly intern repeated source URLs and complete clauses")
    args = parser.parse_args()
    if not args.bundle.is_file():
        parser.error("--bundle must point to an existing evidence-bundle.json")
    if args.output.exists():
        raise SystemExit("refusing to overwrite an existing output directory")
    bundle_bytes = args.bundle.read_bytes()
    try:
        bundle = json.loads(bundle_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid UTF-8 JSON bundle: {exc}")

    catalog = build_fact_catalog(bundle)
    validate_fact_catalog(catalog)
    question = args.question
    if not isinstance(question, str) or not question.strip():
        raise SystemExit("--question must be non-empty text")
    view, sidecar = build_view(question, catalog, deduplicate=args.deduplicate)
    actual_request = view_request(view)  # full C output contract included
    actual_estimate = estimate_input_tokens(actual_request)
    # Diagnostic only: the legacy raw v3 payload size never gates this flow.
    raw_diagnostic = estimate_input_tokens(raw_v3_messages(question, catalog))
    blocked = int(actual_estimate["tokens"]) > INPUT_HARD_TOKENS

    args.output.mkdir(parents=True, exist_ok=False)
    paths = {
        "catalog.json": json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        "business-view.json": json.dumps(view, ensure_ascii=False, indent=2) + "\n",
        "business-view-sidecar.json": json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
        "messages.json": json.dumps(actual_request, ensure_ascii=False, indent=2) + "\n",
        "program-report-A3.zh-CN.md": render_fact_catalog(catalog),
    }
    for name, text in paths.items():
        (args.output / name).write_text(text, encoding="utf-8")
    artifacts = {name: _sha_bytes(args.output / name) for name in REQUIRED_FILES}

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "mode": "offline_view_preparation",
        "representation": "exact_value_dedup_v1" if args.deduplicate else "original_compact_v1",
        "status": "blocked_hard_budget" if blocked else READY_STATUS,
        "callable": False,
        "api_calls": 0, "network_calls": 0, "credential_used": False,
        "model_result": False,
        "command": "prepare_brief_view_offline.py --bundle {bundle} --question {q} --output {out}",
        "question": question,
        "required_files": list(REQUIRED_FILES),
        "artifact_files_sha256": artifacts,
        "binding": {
            "catalog_sha256": catalog["catalog_sha256"],
            "view_catalog_sha256": view["policy"]["catalog_sha256"],
            "sidecar_view_schema": sidecar["view_schema"],
            "id_map_size": len(sidecar["id_map"]),
            "view_question_matches": view["question"] == question,
        },
        "budgets": {"input_target_tokens": INPUT_TARGET_TOKENS,
                    "input_hard_tokens": INPUT_HARD_TOKENS,
                    "output_max_tokens": OUTPUT_MAX_TOKENS,
                    "timeout_seconds": TIMEOUT_SECONDS},
        "input_estimate": dict(actual_estimate, applies_to="actual_messages"),
        "raw_v3_diagnostic": dict(raw_diagnostic, applies_to="diagnostic_only_never_gates"),
        "boundary": "messages.json是带完整C输出合同的实际待发送请求；raw估算仅作诊断；本目录未调用模型。",
        "output_contract": "C响应为v3 JSON（短ID），经 adapt_answer 转回长ID后走原catalog校验。",
    }
    if blocked:
        manifest["return_to_astra"] = "R1"
        manifest["boundary"] += " 超过硬门时不删除任何法律条件，停止并返回R1。"
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if not blocked else 2


if __name__ == "__main__":
    raise SystemExit(main())
