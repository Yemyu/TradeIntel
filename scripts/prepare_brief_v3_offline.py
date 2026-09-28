#!/usr/bin/env python3
"""Prepare a v3 fact catalog and model request without network or credentials.

The command is deliberately an offline preparation step.  It never calls an
LLM.  When the conservative request estimate exceeds the configured budget,
the manifest says ``blocked_budget`` and the output must not be presented as a
callable model run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.brief_fact_catalog import build_fact_catalog, render_fact_catalog, validate_fact_catalog
from src.tradeintel_ai.evidence_linked_brief import messages


INPUT_TOKEN_THRESHOLD = 8000


def estimate_input_tokens(request: list[dict[str, str]]) -> dict[str, int | str]:
    """Use the project's conservative, provider-independent token estimate.

    It intentionally overestimates non-ASCII text because the Chinese policy
    clauses are the expensive part of the context.  This is a planning
    estimate, not a provider billing record.
    """
    text = "\n".join(str(item.get("content", "")) for item in request)
    ascii_chars = sum(ord(char) < 128 for char in text)
    non_ascii_chars = len(text) - ascii_chars
    estimate = math.ceil(1.25 * (ascii_chars / 3 + non_ascii_chars * 2 + 128))
    return {"tokens": estimate, "method": "ceil(1.25*(ASCII/3 + nonASCII*2 + 128))",
            "threshold": INPUT_TOKEN_THRESHOLD}


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--output", type=Path, required=True)
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
    validation = validate_fact_catalog(catalog)
    request = messages(args.question, catalog)
    estimate = estimate_input_tokens(request)
    blocked_budget = int(estimate["tokens"]) > INPUT_TOKEN_THRESHOLD

    # Refuse overwrite before creating anything; write the manifest last so a
    # partial run cannot look like a successful delivery.
    args.output.mkdir(parents=True, exist_ok=False)
    catalog_path = args.output / "catalog.json"
    messages_path = args.output / "messages.json"
    report_path = args.output / "program-report.zh-CN.md"
    _write(catalog_path, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    _write(messages_path, json.dumps(request, ensure_ascii=False, indent=2) + "\n")
    _write(report_path, render_fact_catalog(catalog))

    artifacts = {path.name: _sha_bytes(path) for path in (catalog_path, messages_path, report_path)}
    manifest = {
        "schema_version": "brief-v3-offline-manifest-v1",
        "mode": "offline_fixture_preparation",
        "status": "blocked_budget" if blocked_budget else "prepared_offline_no_model_result",
        "callable": False,
        "api_calls": 0,
        "network_calls": 0,
        "credential_used": False,
        "model_result": False,
        "bundle": str(args.bundle.resolve()),
        "input_bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "evidence_sha256": catalog["evidence_sha256"],
        "catalog_sha256": catalog["catalog_sha256"],
        "catalog_validation": validation,
        "message_count": len(request),
        "input_estimate": estimate,
        "artifact_files_sha256": artifacts,
        "raw_response_sidecar": None,
        "parsed_response_sidecar": None,
        "pending_report_sidecar": None,
        "boundary": "messages.json是带完整政策业务证据的待发送请求，不是模型成绩；program-report是程序基准；本目录未调用模型。",
    }
    manifest_path = args.output / "manifest.json"
    _write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
