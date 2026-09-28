"""Prepare one offline wheat follow-up canary. No provider or network calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tradeintel_ai.trade_report_followup import (PROTOCOL, build_catalog,
    catalog_sha256, messages, parse, question_sha256)
from tradeintel_ai import trade_report_followup
from tradeintel_ai.trade_explanation import report_sha256


DEFAULT_REPORT = Path("evals/trade_model_v3/frozen/20260924-v2/host_artifacts/t2/report.json")
QUESTION = "最新一个月回升了，那今年以来是不是一路上涨？"


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def prepare(report_path: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"输出目录已存在，拒绝覆盖：{output}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    catalog = build_catalog(report)
    digest = catalog_sha256(catalog)
    request = messages(report, QUESTION, catalog, digest)
    # This is a syntactic dummy, not a scored model answer or a hidden gold key.
    fake = {"schema_version": PROTOCOL, "report_sha256": report_sha256(report),
            "followup_question_sha256": question_sha256(QUESTION),
            "catalog_sha256": digest, "mode": "observed", "needed_data": [],
            "points": [{"text": "最近虽有回升，但此前的逐月变化有涨有跌，不能说一直上涨。",
                        "fact_ids": ["export.change.2026-03", "export.change.2026-07"]}]}
    checked = parse(json.dumps(fake, ensure_ascii=False), report, QUESTION, catalog, digest)
    assert checked["status"] == "needs_review"
    files = {"report.json": encoded(report), "catalog.json": encoded(catalog),
             "messages.json": encoded(request), "fake_answer.json": encoded(fake)}
    output.mkdir(parents=True)
    for name, contents in files.items():
        (output / name).write_bytes(contents)
    manifest = {"schema_version": PROTOCOL, "kind": "offline-development-canary",
                "provider_calls": 0, "question": QUESTION, "report_sha256": report_sha256(report),
                "followup_question_sha256": question_sha256(QUESTION),
                "catalog_sha256": digest, "facts": len(catalog["facts"]),
                "request_utf8_bytes": len(encoded(request)),
                "data_version": report["scope"].get("dataset_version"),
                "catalog_version": report["scope"].get("catalog_version"),
                "code_sha256": hashlib.sha256(
                    Path(trade_report_followup.__file__).read_bytes()).hexdigest(),
                "files": {name: hashlib.sha256(contents).hexdigest()
                          for name, contents in files.items()}}
    # A missing manifest marks an interrupted package as incomplete.
    (output / "manifest.json").write_bytes(encoded(manifest))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(prepare(options.report, options.output), ensure_ascii=False, indent=2))
