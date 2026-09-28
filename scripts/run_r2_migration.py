"""Run the frozen FR 2025-23912 announcement through the offline product path.

This is an R2 migration rehearsal, not a model evaluation.  It imports the
saved official HTML into a temporary root, confirms a manually reviewed
candidate, performs a full 18-code coverage check, then performs an explicit
two-code check for the only products present in the current published trade
snapshot.  No production registry, source file, or model endpoint is touched.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import shutil

from tradeintel_ai.announcement_flow import (
    REQUIRED_FIELDS,
    check_trade_coverage,
    confirm_and_enable,
    load_announcement_store,
    resolve_policy_binding,
    submit_candidates,
)
from tradeintel_ai.announcement_report import build_announcement_session_brief
from tradeintel_ai.repository import DataPaths, EvidenceRepository
from tradeintel_ai.session_store import create_session, load_session
from tradeintel_ai.web_app import _handle_announcement_import, _handle_session_post


SOURCE_SHA256 = "a2b8d9ddeada1a7e0a97926a70da545eb40e883ec547c02e5d52221bf2b6ed78"

POLICY_ID = "r2_semiconductor_2025"
SOURCE_ID = "fr202523912"
SOURCE_URL = "https://www.govinfo.gov/content/pkg/FR-2025-12-29/html/2025-23912.htm"
MONTH = "2026-07"
CODES = [
    "28046100", "38180000", "85411000", "85412100", "85412900",
    "85413000", "85414910", "85414970", "85414980", "85414995",
    "85415100", "85415900", "85419000", "85423100", "85423200",
    "85423300", "85423900", "85429000",
]
SELECTED = ["28046100", "38180000"]


class OriginalText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_pre = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "pre":
            self.in_pre = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self.in_pre = False

    def handle_data(self, text: str) -> None:
        if self.in_pre:
            self.parts.append(text)


def extract_text(source: Path) -> str:
    raw = source.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != SOURCE_SHA256:
        raise ValueError("R2 官方原文 SHA256 不一致；拒绝替换验收材料")
    parser = OriginalText()
    parser.feed(raw.decode("utf-8"))
    text = "".join(parser.parts)
    if not text.strip():
        raise ValueError("R2 官方 HTML 没有可保存的原文")
    return text


def build_fields(store: dict, doc_version: str) -> list[dict]:
    sections = store["documents"][0]["sections"]

    def evidence(needle: str) -> list[dict[str, str]]:
        section = next((item for item in sections if needle in item["text"]), None)
        if section is None:
            raise ValueError(f"R2 原文缺少预期引文：{needle}")
        return [{"doc_version": doc_version, "section_id": section["id"], "quote": needle}]

    def span(start: str, end: str) -> str:
        text = "".join(section["text"] for section in sections)
        left = text.index(start)
        right = text.index(end, left) + len(end)
        return text[left:right]

    action = span("Pursuant to Sections 301(b) and (c)", "any additional action.")
    applicability = span("Products of China that are provided", "under the applicable HTSUS subheading.")
    revision = span("Subdivision (f) of U.S. note 31", "is issued at least 30 days prior to that date.''")
    table = span("This action applies to the following 8-digit subheadings:", "Parts of electronic integrated\n                                        circuits and microassemblies.")

    def span_evidence(text: str) -> list[dict[str, str]]:
        # Preserve every intersecting source section, including wrapped lines.
        original = "".join(section["text"] for section in sections)
        left = original.index(text)
        right = left + len(text)
        return [{"doc_version": doc_version, "section_id": section["id"],
                 "quote": section["text"]}
                for section in sections if section["start"] < right and section["end"] > left]

    fields = {
        "title": ("known", "Notice of Action: China's Acts, Policies, and Practices Related to Targeting of the Semiconductor Industry for Dominance", "Notice of Action: China's Acts, Policies, and Practices Related"),
        "publication_date": ("known", "2025-12-29", "Federal Register Volume 90, Number 245 (Monday, December 29, 2025)"),
        "effective_date": ("known", "2025-12-23", "December 23, 2025: The effective date of the action."),
        "clock_24h": ("unknown", None, "公告只确定日期，没有确定24小时制时刻。"),
        "timezone": ("unknown", None, "公告只确定日期，没有确定适用时区。"),
        "entry_events": ("unknown", None, "公告确定 action effective date，但没有完整给出统计查询所需入境事件边界。"),
        "origin": ("known", "China", "Products of China that are provided"),
        "hts_codes": ("known", [{"code": code, "precision": "whole_hts8"} for code in CODES], "This action applies to the following 8-digit subheadings:"),
        "rates": ("known", {code: 0 for code in CODES}, "initial tariff level of 0 percent"),
        "rate_meaning": ("known", "additional duty", "additional rate of duty"),
        "conditions": ("known", ["increasing in 18 months on June 23, 2027", "would be additional to the existing 50 percent Section 301 tariff"], ["increasing in 18 months on June 23, 2027", "would be additional to the existing 50 percent Section 301 tariff"]),
        "exceptions": ("known", ["except any product that is"], "except any product that is"),
        "revisions": ("known", "The additional rate of duty under heading 9903.91.05 shall be increased on June 23, 2027.", "The additional rate of duty under heading 9903.91.05 shall"),
    }
    result: list[dict] = []
    full_spans = {"hts_codes": [table], "rates": [action],
                  "rate_meaning": [action, revision],
                  "conditions": [action, applicability, revision],
                  "exceptions": [applicability], "revisions": [revision]}
    fields["conditions"] = ("known", [action, applicability, revision], [])
    fields["exceptions"] = ("known", ["仅为下列 FTZ 入区身份规则的 domestic status 例外，不是一般关税豁免：\n" + applicability], [])
    fields["revisions"] = ("known", revision, [])
    for name in REQUIRED_FIELDS:
        status, value, quote = fields[name]
        item = {"field": name, "status": status, "value": value, "evidence": []}
        if status == "known":
            quotes = quote if isinstance(quote, list) else [quote]
            item["evidence"] = ([ref for text in full_spans[name] for ref in span_evidence(text)]
                                if name in full_spans else
                                [ref for needle in quotes for ref in evidence(needle)])
        else:
            item["reason"] = quote
        result.append(item)
    return result


def copy_published_data(project_root: Path, target_root: Path) -> None:
    for relative in ("data/processed/policy", "data/processed/policy_exposure"):
        source = project_root / relative
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project-root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"验收输出已存在，为保护首跑结果拒绝覆盖：{output}")
    output.mkdir(parents=True)
    temp_root = output / "temp-root"
    copy_published_data(args.project_root.resolve(), temp_root)
    text = extract_text(args.source.resolve())
    imported = _handle_announcement_import(temp_root, {
        "policy_id": POLICY_ID, "source_id": SOURCE_ID, "url": SOURCE_URL,
        "text": text, "sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
    })
    doc_version = imported["doc_version"]
    store = load_announcement_store(temp_root, POLICY_ID)
    fields = build_fields(store, doc_version)
    submitted = submit_candidates(temp_root, POLICY_ID, doc_version, fields)
    enabled = confirm_and_enable(
        temp_root, POLICY_ID, doc_version, fields, confirmed_by="r2-migration-review",
        expected_candidate_digest=submitted["candidate_digest"])
    full = check_trade_coverage(temp_root, POLICY_ID, doc_version, month=MONTH)
    selected = check_trade_coverage(temp_root, POLICY_ID, doc_version, month=MONTH,
                                    requested_codes=SELECTED)
    store = load_announcement_store(temp_root, POLICY_ID)
    full_binding = resolve_policy_binding(temp_root, POLICY_ID, doc_version,
                                          enabled["candidate_digest"], month=MONTH)
    full_refusal = None
    try:
        build_announcement_session_brief(
            temp_root, {"policy_id": POLICY_ID, "month": MONTH, "product": "all",
                        "focus": "contrast"}, full_binding, store=store,
            candidate=store["announcement_candidates"][doc_version]["candidate"],
            coverage=store["trade_coverage_history"][doc_version][full["trade_coverage"]["coverage_digest"]])
    except ValueError as exc:
        full_refusal = str(exc)
    selected_binding = resolve_policy_binding(
        temp_root, POLICY_ID, doc_version, enabled["candidate_digest"], month=MONTH,
        requested_codes=SELECTED)
    selected_coverage = store["trade_coverage_history"][doc_version][selected["trade_coverage"]["coverage_digest"]]
    brief = build_announcement_session_brief(
        temp_root, {"policy_id": POLICY_ID, "month": MONTH, "product": "all",
                    "products": SELECTED, "focus": "contrast"}, selected_binding,
        store=store, candidate=store["announcement_candidates"][doc_version]["candidate"],
        coverage=selected_coverage)
    # Rehearse the same start -> confirm -> evidence -> generate order used by
    # the browser page.  In particular, the task starts before confirmation;
    # set_request must then propagate the server binding into that task.
    repository = EvidenceRepository(DataPaths(temp_root))
    page_session = create_session(temp_root)
    page_request = {"policy_id": POLICY_ID, "month": MONTH, "product": "all",
                    "products": SELECTED, "focus": "contrast"}
    page_started = _handle_session_post(
        temp_root, "/api/session/task/start",
        {"session_id": page_session["session_id"], "model": "deterministic",
         "prompt_digest": "r2-page", "request": page_request}, repository)
    _handle_session_post(
        temp_root, "/api/session/request",
        {"session_id": page_session["session_id"], "request": page_request,
         "policy_binding": selected_binding}, repository)
    page_evidence = _handle_session_post(
        temp_root, "/api/session/task/evidence",
        {"session_id": page_session["session_id"], "task_id": page_started["task_id"]}, repository)
    page_generated = _handle_session_post(
        temp_root, "/api/session/task/generate",
        {"session_id": page_session["session_id"], "task_id": page_started["task_id"]}, repository)
    page_state = load_session(temp_root, page_session["session_id"])
    page_task = next(item for item in page_state["tasks"].values()
                     if item["task_id"] == page_started["task_id"])
    history = store["trade_coverage_history"][doc_version]
    # Acceptance covers complete legal qualifications, not merely the presence
    # of a rate/date keyword. The old migration report failed these checks.
    report = brief["a3_markdown"]
    required = ["initial tariff level of 0 percent", "existing 50 percent",
                "at least 30 days prior", "domestic status", "privileged foreign status",
                "antidumping, countervailing", "2/18"]
    semantic_checks = {text: text in report for text in required}
    if not all(semantic_checks.values()):
        raise AssertionError(f"R2 报告丢失必要限定：{semantic_checks}")
    result = {
        "source_sha256": SOURCE_SHA256,
        "policy_id": POLICY_ID,
        "doc_version": doc_version,
        "candidate_digest": enabled["candidate_digest"],
        "candidate_field_status": {field["field"]: field["status"] for field in fields},
        "full_18": {
            "availability": full["trade_coverage"]["availability"],
            "requested_codes": full["trade_coverage"]["requested_codes"],
            "covered_codes": full["trade_coverage"]["covered_codes"],
            "missing_codes": full["trade_coverage"]["missing_codes"],
            "coverage_digest": full["trade_coverage"]["coverage_digest"],
            "report_refusal": full_refusal,
        },
        "selected_2": {
            "availability": selected["trade_coverage"]["availability"],
            "requested_codes": selected["trade_coverage"]["requested_codes"],
            "covered_codes": selected["trade_coverage"]["covered_codes"],
            "missing_codes": selected["trade_coverage"]["missing_codes"],
            "coverage_digest": selected["trade_coverage"]["coverage_digest"],
            "report_kind": brief["kind"],
            "report_catalog_sha256": brief["catalog_sha256"],
            "report_mentions_subset": "2/18" in brief["a3_markdown"],
            "page_flow": {
                "evidence_state": page_evidence["status"],
                "generation_state": page_generated["status"],
                "final_task_state": page_task["state"],
                "final_kind": (page_task.get("response") or {}).get("kind"),
            },
        },
        "coverage_history_count": len(history),
        "model_calls": 0,
        "semantic_checks": semantic_checks,
        "production_store_touched": False,
        "boundary": "R2迁移回归，不是盲测、不证明自动解析泛化、不代表未来政策预测。",
    }
    (output / "migration-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "selected-report.zh-CN.md").write_text(brief["a3_markdown"], encoding="utf-8")
    (output / "source-text.txt").write_text(text, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
