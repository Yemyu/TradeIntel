"""Keep policy hits and their version-bound common clauses together."""
from __future__ import annotations

from copy import deepcopy

from .policy_search import PolicySearch


def evidence_bundles(store: dict, result: dict) -> list[dict]:
    """Only complete, enabled document evidence may become a report source."""
    search = PolicySearch(store)
    bundles = []
    for hit in result.get("hits", []):
        document = next((doc for doc in store["documents"]
                         if doc["doc_version"] == hit["doc_version"]
                         and doc["doc_id"] == hit["doc_id"]), None)
        if document is None or document.get("status") != "enabled":
            continue
        context, missing = search._required_context(document)
        if missing:
            continue
        enriched = []
        for clause in context:
            entry = deepcopy(clause)
            entry.update(policy_id=document.get("policy_id"),
                         doc_id=document["doc_id"], doc_version=document["doc_version"])
            if clause["status"] == "known":
                section = next(s for s in document["sections"] if s["id"] == clause["section_id"])
                source = next((s for s in document.get("sources", [])
                               if s.get("source_id") == section.get("source_id")), {})
                entry.update(source_id=section.get("source_id"), page=source.get("page"),
                             url=source.get("url") or document.get("url"),
                             start=section["start"], end=section["end"],
                             offset_unit=document.get("offset_unit", "character"))
            else:
                entry["boundary"] = "仅指本份登记文档的核验结果，不代表其他文件不存在例外。"
            enriched.append(entry)
        bundles.append({"policy_id": hit.get("policy_id"), "doc_id": hit["doc_id"],
                        "doc_version": hit["doc_version"], "hit": deepcopy(hit),
                        "required_context": enriched,
                        "scope": "candidate_related_evidence_not_applicability"})
    return bundles


def evidence_summary(searches: list[dict], bundles: list[dict]) -> dict:
    statuses = {item["status"] for item in searches}
    if bundles:
        status = "partial" if statuses - {"candidate_evidence", "no_evidence"} else "candidate_evidence"
    elif "limited" in statuses:
        status = "limited"
    elif "incomplete_required_context" in statuses:
        status = "incomplete_required_context"
    elif "scope_refused" in statuses:
        status = "scope_refused"
    elif "candidate_evidence" in statuses:
        # Evidence was retrieved, but none was selected for this report.
        # Do not rewrite that historical fact as a zero-hit search.
        status = "partial"
    else:
        status = "no_evidence" if searches else "not_searched"
    return {"schema": "trade-policy-evidence-v1", "status": status,
            "searches": deepcopy(searches), "evidence_bundles": deepcopy(bundles)}
