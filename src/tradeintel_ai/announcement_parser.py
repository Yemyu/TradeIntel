"""Deterministic parser for the offline CBP announcement path.

This module deliberately does not call a model or a network service.  It
extracts only claims that have a matching substring in the saved original
text.  A field that cannot be extracted is returned as ``unknown`` with a
reason, so the K3 human confirmation gate remains the authority that enables
the document.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from .policy_candidates import REQUIRED_FIELDS
from .policy_documents import build_document
from .source_registry import load_candidate_content


_CODE_RE = re.compile(r"\b(\d{4})\.(\d{2})\.(\d{2})\b")
_RATE_RE = re.compile(r"additional\s+(\d+)\s+percent\s+rate\s+of\s+duty", re.I)


def _sections(document: dict[str, Any]) -> list[dict[str, Any]]:
    return document.get("sections", [])


def _quote(document: dict[str, Any], needle: str) -> dict[str, str]:
    for section in _sections(document):
        if needle and needle in section.get("text", ""):
            return {"doc_version": document["doc_version"],
                    "section_id": section["id"], "quote": needle}
    raise ValueError(f"parser extracted text that is not present in its document: {needle!r}")


def _line_containing(text: str, needle: str) -> str | None:
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return None


def _known(name: str, value: Any, document: dict[str, Any], quotes: list[str]) -> dict[str, Any]:
    return {"field": name, "status": "known", "value": value,
            "evidence": [_quote(document, quote) for quote in quotes]}


def _unknown(name: str, reason: str) -> dict[str, Any]:
    return {"field": name, "status": "unknown", "value": None,
            "reason": reason, "evidence": []}


def parse_announcement_text(policy_id: str, source_id: str, text: str, *,
                            url: str | None = None,
                            data_version: str = "announcement-candidate") -> dict[str, Any]:
    """Parse a CBP notice into a disabled document and candidate fields.

    The caller should save ``document`` as the disabled candidate, then pass
    ``fields`` through :func:`announcement_flow.submit_candidates`.  The
    parser makes no adoption decision and never labels trade coverage exact.
    """
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise ValueError("policy_id is required")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id is required")
    if not isinstance(text, str) or len(text.strip()) < 20:
        raise ValueError("announcement text is too short")
    document = build_document({"policy_id": policy_id, "data_version": data_version,
                               "sources": [{"id": source_id, "url": url, "text": text}]},
                              doc_id=source_id, status="disabled")

    fields: list[dict[str, Any]] = []
    # The corpus does not put a formal title in the announcement paragraphs;
    # do not invent one from a filename or policy id.
    fields.append(_unknown("title", "正文没有可核验的正式标题，需人工补充并粘贴引文。"))

    # A generic date in the body is not automatically a publication date.
    fields.append(_unknown("publication_date",
                           "正文只包含生效日期或引用日期，未明确标注公告发布日期。"))

    effective = re.search(r"take effect on\s+([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if effective:
        parsed = datetime.strptime(effective.group(1), "%B %d, %Y").date().isoformat()
        sentence = _line_containing(text, effective.group(1)) or effective.group(0)
        fields.append(_known("effective_date", parsed, document, [sentence]))
    else:
        fields.append(_unknown("effective_date", "未找到明确的 take effect on 日期句。"))

    entry_match = re.search(r"with respect to (goods entered for consumption,?\s+or withdrawn from warehouse for consumption),\s+on or after ([^.]+\.)", text, re.I)
    if entry_match:
        sentence = _line_containing(text, "goods entered for consumption") or entry_match.group(0)
        clock_field = _known("clock_24h", entry_match.group(2).split("eastern")[0].strip(),
                             document, [sentence])
        timezone_field = _known("timezone", "eastern standard time", document, [sentence])
        entry_field = _known("entry_events", entry_match.group(1), document, [sentence])
    else:
        clock_field = _unknown("clock_24h", "未找到明确的时钟时间。")
        timezone_field = _unknown("timezone", "未找到明确的时区。")
        entry_field = _unknown("entry_events", "未找到入境或仓储提取的生效事件句。")
    # Keep the order identical to REQUIRED_FIELDS; the contract is positional
    # in a few existing fixtures even though field names are also validated.
    fields.extend([clock_field, timezone_field, entry_field])

    origin_match = re.search(r"products? of ([A-Z][A-Za-z ]+?) classified", text)
    if origin_match:
        origin = origin_match.group(1).strip()
        phrase = f"products of {origin}"
        fields.append(_known("origin", origin, document, [phrase]))
    else:
        fields.append(_unknown("origin", "未找到 products of <origin> 的原产地句。"))

    code_matches = list(_CODE_RE.finditer(text))
    codes: list[dict[str, str]] = []
    code_quotes: list[str] = []
    for match in code_matches:
        code = "".join(match.groups())
        # 9903.91.05/11 are Chapter 99 reporting headings, not the covered
        # eight-digit merchandise subheadings.  Keep them only in the verbatim
        # source text, never as product exposure codes.
        if code.startswith("990391"):
            continue
        if code in {item["code"] for item in codes}:
            continue
        line = _line_containing(text, match.group(0)) or match.group(0)
        codes.append({"code": code, "precision": "whole_hts8"})
        code_quotes.append(line)
    if codes:
        fields.append(_known("hts_codes", codes, document, code_quotes))
    else:
        fields.append(_unknown("hts_codes", "未找到八位税号行；不能从六位或标题推断。"))

    rate_matches = list(_RATE_RE.finditer(text))
    rates: dict[str, int] = {}
    rate_quotes: list[str] = []
    for match in rate_matches:
        rate = int(match.group(1))
        # Associate each rate with codes in the same notice paragraph.  Never
        # let the 50% polysilicon paragraph bleed into the 25% tungsten one.
        nearby = text
        for paragraph in re.split(r"\n\s*\n", text):
            if match.group(0) in paragraph and _CODE_RE.search(paragraph):
                nearby = paragraph
                break
        nearby_codes = ["".join(item) for item in _CODE_RE.findall(nearby)
                        if not "".join(item).startswith("990391")]
        quote = _line_containing(text, match.group(0)) or match.group(0)
        for code in nearby_codes:
            rates.setdefault(code, rate)
        rate_quotes.append(quote)
    if rates:
        fields.append(_known("rates", rates, document, list(dict.fromkeys(rate_quotes))))
        fields.append(_known("rate_meaning", "additional rate of duty", document,
                             ["additional " + str(rate_matches[0].group(1)) + " percent rate of duty"]))
    else:
        fields.extend([
            _unknown("rates", "未找到 additional N percent rate of duty 句。"),
            _unknown("rate_meaning", "未找到税率含义的原文句。"),
        ])

    condition_lines = []
    for line in text.splitlines():
        if "importers shall submit heading" in line.lower() or "products of" in line.lower() and "classified" in line.lower():
            condition_lines.append(line.strip())
    if condition_lines:
        fields.append(_known("conditions", condition_lines, document,
                             list(dict.fromkeys(condition_lines))))
    else:
        fields.append(_unknown("conditions", "未找到适用条件原文。"))

    fields.append(_unknown("exceptions", "正文未给出可独立核验的例外条款；不能推断无例外。"))

    revision = re.search(r"See\s+([0-9]+\s+FR\s+[0-9]+)\.", text)
    if revision:
        fields.append(_known("revisions", revision.group(1), document, [revision.group(0)]))
    else:
        fields.append(_unknown("revisions", "正文没有可核验的修订或联邦公报引用。"))

    if [field["field"] for field in fields] != list(REQUIRED_FIELDS):
        raise AssertionError("parser field order diverged from candidate contract")
    return {"document": document, "fields": fields,
            "parser": "cbp-deterministic-v1",
            "boundary": "确定性抽取只生成候选；字段确认、启用、覆盖与研究范围重绑定仍需人工流程。"}


def parse_saved_candidate(root: Path, policy_id: str, record: dict[str, Any]) -> dict[str, Any]:
    """Decode a hash-verified source-registry candidate and parse its bytes.

    The parser never reads a URL directly.  ``load_candidate_content`` first
    verifies the saved bytes against the fetch hash; this makes the offline
    fetch → save → reload → parse chain explicit and replayable.
    """
    content = load_candidate_content(root, record)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("公告候选不是 UTF-8 文本，解析器拒绝猜测编码") from exc
    return parse_announcement_text(policy_id, record["source_id"], text,
                                   url=record.get("final_url") or record.get("url"))


__all__ = ["parse_announcement_text", "parse_saved_candidate"]
