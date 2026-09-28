#!/usr/bin/env python3
"""Offline fake-mode experiment executor (no provider, ever).

Consumes an already-prepared package and verifies its manifest is present and
ready (an interrupted directory without a finished manifest is never treated
as ready), enforces the frozen budget gates, deterministically constructs a
fake answer, runs it through the real contract pipeline, and writes a run
manifest LAST so a partial run cannot look successful.

Two package schemas are supported:

- ``brief-view-offline-manifest-v1`` (actual compact protocol): the fake
  answer is built from the view's SHORT IDs, converted back through the
  trusted response adapter (``adapt_answer``) and validated against the
  original catalog -- exactly the path a real model answer would take.
- ``brief-v3-offline-manifest-v1`` (legacy v3 package, kept for the existing
  offline tests): the fake answer uses full catalog IDs directly.

Budget gates (Astra design 5.2/5.3, review F1): only the ACTUAL request passes
the input hard gate; raw sizes are diagnostic.  A fake output above the
2000-token gate blocks the success status instead of being recorded and
ignored.  Legal conditions are never dropped to fit a gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.brief_business_view import adapt_answer, view_request, restore, business_payload
from src.tradeintel_ai.brief_fact_catalog import validate_fact_catalog
from src.tradeintel_ai.evidence_linked_brief import parse_response, render_pending
from scripts.prepare_brief_v3_offline import estimate_input_tokens

PACKAGE_MANIFEST_SCHEMA = "brief-v3-offline-manifest-v1"
VIEW_MANIFEST_SCHEMA = "brief-view-offline-manifest-v1"
RUN_MANIFEST_SCHEMA = "fake-experiment-run-manifest-v1"
INPUT_TARGET_TOKENS = 8000
INPUT_HARD_TOKENS = 16000
OUTPUT_MAX_TOKENS = 2000
TIMEOUT_SECONDS = 90
MAX_FINDINGS = 3

DEFAULT_FAKE_TEXT = (
    "两个排序衡量不同问题：金额榜首适合优先核对大额贸易敞口，占比榜首适合观察该商品"
    "进口来源构成，二者可能指向不同商品；具体含义需结合政策范围与人工审阅确认。"
)


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_package(package: Path) -> tuple[dict, list[str]]:
    """Return (manifest, required_files) or refuse: interrupted dirs are not ready."""
    manifest_path = package / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"package {package} has no finished manifest.json; treat as interrupted, not ready")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"package manifest is not valid UTF-8 JSON: {exc}")
    schema = manifest.get("schema_version")
    if schema == VIEW_MANIFEST_SCHEMA:
        ready_status = "prepared_view_no_model_result"
        required = manifest.get("required_files")
    elif schema == PACKAGE_MANIFEST_SCHEMA:
        ready_status = "prepared_offline_no_model_result"
        required = sorted((manifest.get("artifact_files_sha256") or {}).keys())
    else:
        raise SystemExit("unknown package manifest schema")
    if manifest.get("status") != ready_status or manifest.get("callable") is not False:
        raise SystemExit(f"package status {manifest.get('status')!r} is not ready for execution")
    if not required:
        raise SystemExit("manifest required file set is empty; refusing to execute")
    for name in required:
        artifact = package / name
        digest = (manifest.get("artifact_files_sha256") or {}).get(name)
        if not isinstance(digest, str) or not digest:
            raise SystemExit(f"required file {name} has no recorded hash; refusing to execute")
        if not artifact.is_file() or _sha_bytes(artifact) != digest:
            raise SystemExit(f"package artifact missing or modified: {name}")
    return manifest, list(required)


def _load_catalog(package: Path) -> dict:
    catalog = json.loads((package / "catalog.json").read_text(encoding="utf-8"))
    validate_fact_catalog(catalog)
    return catalog


def _verify_view_binding(package: Path, manifest: dict, catalog: dict) -> tuple[dict, dict]:
    view = json.loads((package / "business-view.json").read_text(encoding="utf-8"))
    sidecar = json.loads((package / "business-view-sidecar.json").read_text(encoding="utf-8"))
    binding = (view.get("policy") or {}).get("catalog_sha256")
    if binding != catalog.get("catalog_sha256"):
        raise SystemExit("view is not bound to this catalog")
    if manifest.get("binding", {}).get("view_catalog_sha256") != binding:
        raise SystemExit("manifest binding does not match the view")
    if view.get("question") != manifest.get("question"):
        raise SystemExit("package question was modified after preparation")
    messages = json.loads((package / "messages.json").read_text(encoding="utf-8"))
    question = json.loads(messages[1]["content"]).get("question")
    if question != manifest.get("question"):
        raise SystemExit("actual request question does not match the manifest")
    if restore(view, sidecar) != business_payload(catalog):
        raise SystemExit("view does not restore the complete catalog business payload")
    if messages != view_request(view):
        raise SystemExit("actual request does not match the complete view and C contract")
    return view, sidecar


def _fake_answer_from_view(view: dict, text: str) -> dict:
    """Deterministic fake answer using the view's SHORT IDs (real model path)."""
    business = view["business"]
    findings = []
    for observation in business["observations"][:MAX_FINDINGS]:
        fact = next(item for item in business["facts"]
                    if observation["id"] in (item.get("observation_ids") or []))
        refs = [dict(ref) for ref in business.get("policy_refs", [])
                if ref.get("hts8") == fact.get("product_scope")]
        if not refs:
            raise SystemExit(f"no policy reference for product {fact.get('product_scope')}")
        findings.append({"observation_id": observation["id"], "fact_ids": [fact["id"]],
                         "policy_refs": refs, "interpretation": text, "limitation_ids": []})
    if not findings:
        raise SystemExit("view has no observations; fake answer cannot be constructed")
    return {"schema_version": "evidence-linked-brief-v3",
            "catalog_sha256": view["policy"]["catalog_sha256"],
            "findings": findings, "followups": []}


def _fake_answer_from_catalog(catalog: dict, text: str) -> dict:
    """Legacy path: deterministic fake answer with full catalog IDs."""
    findings = []
    for observation in catalog["observations"][:MAX_FINDINGS]:
        fact = next(item for item in catalog["facts"]
                    if observation["id"] in item["observation_ids"])
        refs = [dict(ref) for ref in catalog["policy_refs"]
                if ref["hts8"] == fact["product_scope"]]
        findings.append({"observation_id": observation["id"], "fact_ids": [fact["id"]],
                         "policy_refs": refs, "interpretation": text, "limitation_ids": []})
    if not findings:
        raise SystemExit("catalog has no observations; fake answer cannot be constructed")
    return {"schema_version": "evidence-linked-brief-v3",
            "catalog_sha256": catalog["catalog_sha256"],
            "findings": findings, "followups": []}


def _run_view_package(package: Path, output: Path, fake_text: str) -> int:
    manifest, _required = _verify_package(package)
    catalog = _load_catalog(package)
    view, sidecar = _verify_view_binding(package, manifest, catalog)

    actual_estimate = dict(manifest.get("input_estimate") or {},
                           applies_to="actual_messages")
    run: dict = {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "mode": "fake_no_provider",
        "model": "fake-deterministic-no-provider",
        "package_schema": VIEW_MANIFEST_SCHEMA,
        "api_calls": 0, "provider_calls": 0, "network_calls": 0,
        "credential_used": False, "model_result": False,
        "package": str(package.resolve()),
        "package_manifest_sha256": _sha_bytes(package / "manifest.json"),
        "catalog_sha256": catalog["catalog_sha256"],
        "budgets": {"input_target_tokens": INPUT_TARGET_TOKENS,
                    "input_hard_tokens": INPUT_HARD_TOKENS,
                    "output_max_tokens": OUTPUT_MAX_TOKENS,
                    "timeout_seconds": TIMEOUT_SECONDS},
        "input_estimate": actual_estimate,
        "boundary": "fake回答从实际view短ID生成，经同一响应适配器与正式校验；不是任何模型的输出或成绩。",
    }
    if int(actual_estimate.get("tokens", 0)) > INPUT_HARD_TOKENS:
        run["status"] = "blocked_hard_budget"
        run["return_to_astra"] = "R1"
        run["boundary"] += " 超过硬门时不删除任何法律条件，停止并返回R1。"
        output.mkdir(parents=True, exist_ok=False)
        (output / "run-manifest.json").write_text(
            json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(run, ensure_ascii=False, indent=2))
        return 2

    answer_view = _fake_answer_from_view(view, fake_text)
    raw_view_text = json.dumps(answer_view, ensure_ascii=False, indent=2) + "\n"
    converted = adapt_answer(answer_view, view, sidecar, catalog)
    output_estimate = estimate_input_tokens([{"content": raw_view_text}])
    run["output_estimate"] = dict(output_estimate, gate="model_output_max_tokens")
    run["output_within_gate"] = int(output_estimate["tokens"]) <= OUTPUT_MAX_TOKENS
    parsed = parse_response(json.dumps(converted, ensure_ascii=False) + "\n", catalog)
    report = render_pending(converted, catalog, parsed["validation"])
    run["validation_status"] = parsed["validation"]["status"]
    run["coverage"] = parsed["validation"]["task_coverage"]
    run["adapter"] = {"used": True, "id_map_size": len(sidecar["id_map"]),
                      "id_fields_only": True, "prose_untouched": True}

    if not run["output_within_gate"]:
        run["status"] = "blocked_output_budget"
        run["boundary"] += " 输出超过2000门，阻止成功状态。"
        write_artifacts = False
    else:
        run["status"] = "fake_response_validated"
        write_artifacts = True
    output.mkdir(parents=True, exist_ok=False)
    if write_artifacts:
        raw_path = output / "fake-answer.short-id.raw.json"
        converted_path = output / "fake-answer.converted.json"
        sidecar_path = output / "response-sidecar.json"
        report_path = output / "pending-report.zh-CN.md"
        sidecar_payload = dict(sidecar)
        sidecar_payload["response"] = parsed
        raw_path.write_text(raw_view_text, encoding="utf-8")
        converted_path.write_text(json.dumps(converted, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        sidecar_path.write_text(json.dumps(sidecar_payload, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        report_path.write_text(report, encoding="utf-8")
        run["artifact_files_sha256"] = {path.name: _sha_bytes(path)
                                        for path in (raw_path, converted_path, sidecar_path, report_path)}
    (output / "run-manifest.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(run, ensure_ascii=False, indent=2))
    return 0 if run["status"] == "fake_response_validated" else 2


def _run_legacy_package(package: Path, output: Path, fake_text: str) -> int:
    manifest, _required = _verify_package(package)
    catalog = _load_catalog(package)
    run: dict = {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "mode": "fake_no_provider",
        "model": "fake-deterministic-no-provider",
        "package_schema": PACKAGE_MANIFEST_SCHEMA,
        "api_calls": 0, "provider_calls": 0, "network_calls": 0,
        "credential_used": False, "model_result": False,
        "package": str(package.resolve()),
        "package_manifest_sha256": _sha_bytes(package / "manifest.json"),
        "catalog_sha256": catalog["catalog_sha256"],
        "budgets": {"input_target_tokens": INPUT_TARGET_TOKENS,
                    "input_hard_tokens": INPUT_HARD_TOKENS,
                    "output_max_tokens": OUTPUT_MAX_TOKENS,
                    "timeout_seconds": TIMEOUT_SECONDS},
        "input_estimates": {
            "v3_messages": dict(manifest.get("input_estimate") or {}, source="package manifest"),
        },
        "boundary": "fake回答只验证v3合同与预算门，不是任何模型的输出或成绩；本目录未调用模型。",
    }
    answer = _fake_answer_from_catalog(catalog, fake_text)
    raw_text = json.dumps(answer, ensure_ascii=False, indent=2) + "\n"
    parsed = parse_response(raw_text, catalog)
    report = render_pending(answer, catalog, parsed["validation"])
    output_estimate = estimate_input_tokens([{"content": raw_text}])
    run["output_estimate"] = dict(output_estimate, gate="model_output_max_tokens")
    run["output_within_gate"] = int(output_estimate["tokens"]) <= OUTPUT_MAX_TOKENS
    run["validation_status"] = parsed["validation"]["status"]
    run["coverage"] = parsed["validation"]["task_coverage"]
    if not run["output_within_gate"]:
        run["status"] = "blocked_output_budget"
    else:
        run["status"] = "fake_response_validated"
    output.mkdir(parents=True, exist_ok=False)
    raw_path = output / "fake-answer.raw.json"
    sidecar_path = output / "response-sidecar.json"
    report_path = output / "pending-report.zh-CN.md"
    sidecar_payload = dict(manifest)
    sidecar_payload["response"] = parsed
    raw_path.write_text(raw_text, encoding="utf-8")
    sidecar_path.write_text(json.dumps(sidecar_payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")
    run["artifact_files_sha256"] = {path.name: _sha_bytes(path)
                                    for path in (raw_path, sidecar_path, report_path)}
    (output / "run-manifest.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(run, ensure_ascii=False, indent=2))
    return 0 if run["status"] == "fake_response_validated" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True,
                        help="prepared offline package directory (with finished manifest.json)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fake-text", default=DEFAULT_FAKE_TEXT,
                        help="deterministic interpretation text used by the fake answer")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite an existing run directory")
    manifest_path = args.package / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"package {args.package} has no finished manifest.json; treat as interrupted, not ready")
    schema = json.loads(manifest_path.read_text(encoding="utf-8")).get("schema_version")
    if schema == VIEW_MANIFEST_SCHEMA:
        return _run_view_package(args.package, args.output, args.fake_text)
    return _run_legacy_package(args.package, args.output, args.fake_text)


if __name__ == "__main__":
    raise SystemExit(main())
