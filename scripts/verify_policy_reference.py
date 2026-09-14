#!/usr/bin/env python3
"""Independently re-check the frozen policy facts against the local official PDF.

This is an AI-assisted structural check.  It deliberately leaves the human
review status pending; matching text is not a substitute for a person reading
the source and recording an independent review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = ROOT / "data/raw/policy/ustr-section301-list1-2018.pdf"
DEFAULT_FACTS = ROOT / "data/processed/policy/section301_list1_facts.json"
EXPECTED_SHA256 = "3e27dfb420dc308a079e7a71f2715fa29ed00fbbd84dbec4514f2cd66b9cf301"
EXPECTED_URL = "https://ustr.gov/sites/default/files/2018-13248.pdf"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _fact_by_id(facts: dict[str, Any], fact_id: str) -> dict[str, Any] | None:
    for fact in facts.get("facts", []):
        if isinstance(fact, dict) and fact.get("id") == fact_id:
            return fact
    return None


def run_check(*, pdf_path: Path = DEFAULT_PDF, facts_path: Path = DEFAULT_FACTS) -> dict[str, Any]:
    """Return a source comparison without changing either input file."""

    checks: dict[str, bool] = {}
    reasons: list[str] = []
    facts: dict[str, Any] = {}

    checks["source_exists"] = pdf_path.is_file()
    checks["facts_exists"] = facts_path.is_file()
    if not checks["source_exists"]:
        reasons.append(f"official PDF is missing: {pdf_path}")
    if not checks["facts_exists"]:
        reasons.append(f"facts file is missing: {facts_path}")
    if not all(checks.values()):
        return {
            "status": "blocked_before_human_review",
            "checks": checks,
            "reasons": reasons,
            "human_review": {"status": "pending_independent_human_review"},
        }

    try:
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        checks["facts_json_readable"] = False
        reasons.append(f"facts JSON cannot be read: {type(exc).__name__}")
    else:
        checks["facts_json_readable"] = isinstance(facts, dict)
        if not checks["facts_json_readable"]:
            reasons.append("facts JSON root is not an object")

    actual_sha256 = _sha256(pdf_path)
    checks["source_sha256_matches"] = actual_sha256 == EXPECTED_SHA256
    if not checks["source_sha256_matches"]:
        reasons.append("local PDF SHA-256 differs from the frozen official source")

    checks["facts_review_status_is_pending"] = (
        facts.get("review_status") == "pending_independent_human_review"
    )
    if not checks["facts_review_status_is_pending"]:
        reasons.append("facts file is not explicitly pending independent human review")

    checks["question_and_cutoff_match"] = (
        facts.get("question") == "第一批关税何时生效，额外税率是多少？"
        and facts.get("as_of") == "2018-07-06"
    )
    if not checks["question_and_cutoff_match"]:
        reasons.append("question or cutoff differs from the frozen review question")

    sources = {
        source.get("id"): source
        for source in facts.get("sources", [])
        if isinstance(source, dict) and source.get("id")
    }
    checks["source_catalog_matches"] = bool(sources) and all(
        source.get("url") == EXPECTED_URL
        and source.get("sha256") == EXPECTED_SHA256
        and source.get("path") == "data/raw/policy/ustr-section301-list1-2018.pdf"
        for source in sources.values()
    )
    if not checks["source_catalog_matches"]:
        reasons.append("facts source catalog does not point to the frozen PDF")

    try:
        reader = PdfReader(str(pdf_path))
        page_one = _compact(reader.pages[0].extract_text() or "")
        page_two = _compact(reader.pages[1].extract_text() or "")
        checks["effective_date_phrase_on_pdf_page_1"] = bool(
            re.search(r"Applicable date of duties: .*?on or after July 6, 2018", page_one)
        )
        checks["additional_rate_phrase_on_pdf_page_2"] = bool(
            re.search(r"Products of China .*?additional duty of 25 percent ad valorem", page_two)
        )
        checks["consumption_scope_phrase_on_pdf_page_1"] = (
            "entered for consumption, or withdrawn from warehouse for consumption"
            in page_one
        )
    except Exception as exc:  # the error class is intentionally not persisted
        checks["official_pdf_text_readable"] = False
        reasons.append(f"official PDF text could not be read: {type(exc).__name__}")
    else:
        checks["official_pdf_text_readable"] = True
        for name in (
            "effective_date_phrase_on_pdf_page_1",
            "additional_rate_phrase_on_pdf_page_2",
            "consumption_scope_phrase_on_pdf_page_1",
        ):
            if not checks[name]:
                reasons.append(f"expected source phrase not found: {name}")

    date_fact = _fact_by_id(facts, "effective_date")
    rate_fact = _fact_by_id(facts, "additional_rate")
    checks["effective_date_fact_matches_source_record"] = bool(
        date_fact
        and date_fact.get("expected_value") == "2018-07-06"
        and date_fact.get("evidence_ids") == ["initial_notice:p1:c4668"]
        and date_fact.get("evidence_ids", [None])[0] in sources
        and sources[date_fact["evidence_ids"][0]].get("page") == 1
    )
    checks["additional_rate_fact_matches_source_record"] = bool(
        rate_fact
        and rate_fact.get("expected_value") == "25%"
        and rate_fact.get("evidence_ids") == ["initial_notice:p2:c5100"]
        and rate_fact.get("evidence_ids", [None])[0] in sources
        and sources[rate_fact["evidence_ids"][0]].get("page") == 2
    )
    if not checks["effective_date_fact_matches_source_record"]:
        reasons.append("effective-date fact is not bound to the expected page/source")
    if not checks["additional_rate_fact_matches_source_record"]:
        reasons.append("additional-rate fact is not bound to the expected page/source")

    structural_pass = all(checks.values())
    return {
        "status": (
            "ai_assisted_check_passed_pending_human_review"
            if structural_pass
            else "blocked_before_human_review"
        ),
        "source": {
            "url": EXPECTED_URL,
            "local_path": str(pdf_path),
            "sha256": actual_sha256,
        },
        "checks": checks,
        "reasons": reasons,
        "human_review": {
            "status": "pending_independent_human_review",
            "must_record": [
                "reviewer identity",
                "review timestamp",
                "file version or SHA-256",
                "effective date fact: correct/incorrect and reason",
                "additional rate fact: correct/incorrect and reason",
                "consumption/warehouse scope limitation: complete/incomplete and reason",
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-check frozen policy facts against the local official PDF."
    )
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    args = parser.parse_args(argv)
    report = run_check(pdf_path=args.pdf.resolve(), facts_path=args.facts.resolve())
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.resolve().write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "ai_assisted_check_passed_pending_human_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())

