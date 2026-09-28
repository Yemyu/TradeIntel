"""Offline development check for five already-seen official notices.

Provide downloaded originals; this script never fetches, calls a model, or
publishes a report.  The field choices are development annotations, NOT an
independent legal review or a new-announcement holdout result.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile

from pypdf import PdfReader

from tradeintel_ai.announcement_flow import (REQUIRED_FIELDS, confirm_and_enable,
                                             save_announcement_store, submit_candidates)
from tradeintel_ai.announcement_linkage import (confirm_linkage_assessment,
                                                prepare_linkage_scope,
                                                validate_prepared_linkage_scope)
from tradeintel_ai.policy_documents import build_document, build_document_store


class _PreText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "pre":
            self.inside = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self.inside = False

    def handle_data(self, data: str) -> None:
        if self.inside:
            self.parts.append(data)


_R2_CODES = (
    "28046100", "38180000", "85411000", "85412100", "85412900", "85413000",
    "85414910", "85414970", "85414980", "85414995", "85415100", "85415900",
    "85419000", "85423100", "85423200", "85423300", "85423900", "85429000",
)

_SOURCES = (
    ("r2", "2025-23912.html",
     "a2b8d9ddeada1a7e0a97926a70da545eb40e883ec547c02e5d52221bf2b6ed78",
     "https://www.govinfo.gov/content/pkg/FR-2025-12-29/html/2025-23912.htm"),
    ("parent", "2026-17925.htm",
     "07301a97a51c523324be511c766a84cc60f755b2fce56ffecd047043cb7143fd",
     "https://www.govinfo.gov/content/pkg/FR-2026-09-02/html/2026-17925.htm"),
    ("country", "2025-02293.pdf",
     "787b89ab57dd71abd8b319d5d55a5662ac4f427d83ec38d3cc4e51dca4bce563",
     "https://www.govinfo.gov/content/pkg/FR-2025-02-05/pdf/2025-02293.pdf"),
    ("postal", "2025-07325.pdf",
     "989965fd9323d2f6b07558fc5901ada96ca7d6b46d3d0bb1b5386f18143ec191",
     "https://www.govinfo.gov/content/pkg/FR-2025-04-28/pdf/2025-07325.pdf"),
    ("pharma", "2026-19498.htm",
     "611a1725cf02db02c1e79697295e4fccd7603e0410ef3924b4369dd319320092",
     "https://www.govinfo.gov/content/pkg/FR-2026-09-23/html/2026-19498.htm"),
)


def _original_text(path: Path, expected_sha: str) -> str:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha:
        raise ValueError(f"official source digest mismatch: {path.name}: {actual}")
    if path.suffix == ".pdf":
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(raw)).pages)
    else:
        parser = _PreText()
        parser.feed(raw.decode("utf-8"))
        text = "".join(parser.parts)
    if not text.strip():
        raise ValueError(f"official source has no extractable text: {path.name}")
    return text


def _citation(document: dict, needle: str) -> dict[str, str]:
    for section in document["sections"]:
        if needle in section["text"]:
            return {"doc_version": document["doc_version"],
                    "section_id": section["id"], "quote": needle}
    raise ValueError(f"source text lacks the development annotation: {needle}")


def _field(name: str, value: object, citations: list[dict]) -> dict:
    return {"field": name, "status": "known", "value": value, "evidence": citations}


def _case_fields(kind: str, document: dict) -> list[dict]:
    known: dict[str, dict] = {}
    if kind != "pharma":
        known["origin"] = _field("origin", "China", [_citation(document, "China")])
    if kind == "r2":
        known["hts_codes"] = _field(
            "hts_codes", [{"code": code, "precision": "whole_hts8"} for code in _R2_CODES],
            [_citation(document, code) for code in _R2_CODES])
    elif kind == "parent":
        known["hts_codes"] = _field(
            "hts_codes", [{"code": "8413919039", "precision": "hts10_partial"}],
            [_citation(document, "8413.91.9039")])
    elif kind == "country":
        known["conditions"] = _field("conditions", "按原文入境时间与申报事件适用",
                                     [_citation(document, "entered")])
        known["exceptions"] = _field("exceptions", "存在原文列出的法定例外",
                                     [_citation(document, "1702")])
    return [known.get(name) or {"field": name, "status": "unknown", "value": None,
                                "reason": "本开发检查未独立核对这一字段，不能推定其缺失"}
            for name in REQUIRED_FIELDS]


def _proposal(kind: str, document: dict) -> dict:
    kind_to_relation = {"r2": "code_aligned", "parent": "parent_context",
                        "country": "country_context", "postal": "no_statistical_link",
                        "pharma": "no_statistical_link"}
    anchors = {
        "r2": ["28046100", "China"],
        "parent": ["8413.91.9039", "China"],
        "country": ["Hong Kong", "China", "1702"],
        "postal": ["postal", "$800"],
        "pharma": ["approval"],
    }
    conditions = {
        "r2": [("entry_event", True, "贸易月表无法逐票核对入境条件")],
        "parent": [("exception_status", True, "十位排除不等于整个八位父码")],
        "country": [("exception_status", False, "法定例外与入境事件不能由月表逐项识别")],
        "postal": [("shipping_method", True, "必须区分国际邮政网络"),
                   ("shipment_value", True, "必须核对每件包裹金额")],
        "pharma": [("firm_qualification", True, "须核对个别企业及审批决定"),
                   ("approved_use", True, "须核对药品用途")],
    }
    return {"relation": kind_to_relation[kind],
            "origin_alignment": "mainland_subset_of_china_hk" if kind == "country"
                                else ("unknown" if kind == "pharma" else "mainland_only"),
            "context_code": "84139190" if kind == "parent" else None,
            "policy_scope_summary": {
                "r2": "开发已见 R2 的十八个完整八位码；不代表实际应税额",
                "parent": "已见修订中的十位排除货品；八位码只是更宽的商品背景",
                "country": "广泛中国货品但有法定、入境及香港范围条件",
                "postal": "按邮政方式与单件价值界定的低值包裹",
                "pharma": "按药品用途、司法辖区及个别审批界定的进口",
            }[kind],
            "unobserved_eligibility": [
                {"dimension": dim, "defines_population": defines, "description": description}
                for dim, defines, description in conditions[kind]],
            "evidence": [_citation(document, needle) for needle in anchors[kind]]}


def check_seen_cases(source_root: Path, r2_html: Path, trade_root: Path) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory(prefix="policy-linkage-seen-") as temporary:
        store_root = Path(temporary)
        for kind, name, expected_sha, url in _SOURCES:
            path = r2_html if kind == "r2" else source_root / name
            text = _original_text(path, expected_sha)
            policy_id = f"seen-linkage-{kind}"
            document = build_document(
                {"policy_id": policy_id,
                 "sources": [{"id": f"official:{kind}:p1", "url": url,
                              "text": text, "document_sha256": expected_sha}]},
                status="disabled")
            version = document["doc_version"]
            save_announcement_store(store_root, policy_id,
                                    build_document_store([document], policy_id=policy_id))
            fields = _case_fields(kind, document)
            submitted = submit_candidates(store_root, policy_id, version, fields)
            confirm_and_enable(store_root, policy_id, version, fields,
                               confirmed_by="development-annotation-not-legal-approval",
                               expected_candidate_digest=submitted["candidate_digest"])
            assessment = confirm_linkage_assessment(
                store_root, policy_id, version, _proposal(kind, document),
                confirmed_by="development-annotation-not-legal-approval",
                expected_candidate_digest=submitted["candidate_digest"])
            dates = {"start_month": "2026-07", "end_month": "2026-07"} if kind in {
                "r2", "parent", "country"} else {}
            prepared = prepare_linkage_scope(store_root, policy_id, version,
                                             trade_root=trade_root, **dates)
            validate_prepared_linkage_scope(store_root, prepared, trade_root=trade_root)
            if kind == "country" and prepared.get("hong_kong_included_in_statistics") is not False:
                raise AssertionError("country background mistakenly includes Hong Kong")
            if kind in {"postal", "pharma"} and (prepared["months"] or prepared["statistical_population"]):
                raise AssertionError("non-linkable notice received a trade population")
            results.append({"case": kind, "source_url": url,
                            "source_sha256": expected_sha, "doc_version": version,
                            "candidate_digest": submitted["candidate_digest"],
                            "assessment_digest": assessment["assessment_digest"],
                            "route": prepared["route"], "months": prepared["months"],
                            "context_code": prepared["context_code"],
                            "policy_amount_status": prepared["policy_amount_status"]})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--r2-html", type=Path, required=True)
    parser.add_argument("--trade-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = check_seen_cases(args.source_root, args.r2_html, args.trade_root)
    report = {"schema": "policy-linkage-seen-development-v1", "cases": results,
              "model_calls": 0, "mysql_writes": 0,
              "boundary": "Already-seen originals with curated development fields; not independent legal review, "
                          "not a holdout, no trade amount or new report."}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({item["case"]: item["route"] for item in results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
