"""Versioned official policy document store with stable, re-usable citations.

One official document (one bulletin/notice file) is one document record with
a pinned doc_version digest, original URL, fetch metadata, parser version,
publication time and lifecycle status.  Its pages are sources; the text is
kept as contiguous paragraph sections with exact character offsets, so every
citation points to saved original text at a stable location
(``<doc_version>:<section_id>``) that never changes when new documents
arrive or a search reruns.  Nothing here truncates, summarizes or re-ranks
the text; disabling is explicit and only done by the controlled update flow.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

SCHEMA = "policy-document-store-v1"
STATUSES = ("enabled", "disabled", "superseded")
PARSER_VERSION = "paragraph-lines-v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _version_digest(payload: dict[str, Any]) -> str:
    return "docver-" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]


def compute_doc_version(document: dict[str, Any]) -> str:
    """Recompute the version digest from the stored document content.

    The digest covers the parser version, the source identities, the original
    file hash when one is known (flagged explicitly when absent), and the
    normalized hash of every saved section text -- so any change to the parsed
    text yields a NEW version even when the underlying file is unchanged.
    """
    sources = [{"source_id": item.get("source_id"),
                "document_sha256": item.get("document_sha256"),
                "document_sha256_present": bool(item.get("document_sha256")),
                "text_sha256": item.get("text_sha256"),
                "page": item.get("page")}
               for item in document.get("sources", [])]
    payload = {"doc_id": document.get("doc_id"),
               "parser_version": document.get("parser_version"),
               "offset_unit": document.get("offset_unit"),
               "sources": sources,
               "sections": [{"id": s.get("id"), "start": s.get("start"),
                             "end": s.get("end"), "text": s.get("text")}
                            for s in document.get("sections", [])]}
    return _version_digest(payload)


def split_sections(source_id: str, text: str) -> list[dict[str, Any]]:
    """Split one source page into contiguous non-empty line paragraphs.

    Offsets are byte-exact and contiguous: the first section starts at 0,
    every section ends where the next one starts (trailing blank lines stay
    inside the previous section), so joining a source's sections reproduces
    that source's text exactly and its hash stays verifiable.
    """
    matches = list(re.finditer(r"^[ \t]*\S.*$", text, re.M))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = 0 if index == 0 else match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append({"id": f"{source_id}:para{index + 1}",
                         "source_id": source_id,
                         "start": start, "end": end,
                         "text": text[start:end]})
    return sections


def build_document(policy_facts: dict[str, Any], *,
                   doc_id: str | None = None,
                   fetched_at: str | None = None,
                   publication_time: str | None = None,
                   status: str = "enabled") -> dict[str, Any]:
    """Build one document record from the registered pages of one notice."""
    if not isinstance(policy_facts, dict) or not policy_facts.get("policy_id"):
        raise ValueError("policy facts with a policy_id are required")
    if status not in STATUSES:
        raise ValueError(f"document status must be one of {STATUSES}")
    doc_id = doc_id or str(policy_facts["policy_id"])
    sections: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for source in policy_facts.get("sources", []):
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            raise ValueError("policy facts sources must be objects with ids")
        text = source.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        page = source["id"].rsplit(":p", 1)[-1] if ":p" in source["id"] else "1"
        sources.append({"source_id": source["id"], "page": page,
                        "url": source.get("url"),
                        "document_sha256": source.get("document_sha256"),
                        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        sections.extend(split_sections(source["id"], text))
    if not sections:
        raise ValueError("policy facts contain no readable source text")
    document = {
        "doc_id": doc_id,
        "doc_version": None,
        "url": sources[0].get("url"),
        "parser_version": PARSER_VERSION,
        "offset_unit": "character",
        "fetched_at": fetched_at,
        "publication_time": publication_time,
        "publication_time_status": "known" if publication_time else "unknown",
        "status": status,
        "policy_id": policy_facts["policy_id"],
        "data_version": policy_facts.get("data_version"),
        "sources": sources,
        "sections": sections,
    }
    document["doc_version"] = compute_doc_version(document)
    return document


def build_document_store(documents: list[dict[str, Any]], *,
                         policy_id: str, data_version: str | None = None,
                         limitations: list[str] | None = None) -> dict[str, Any]:
    """Assemble and validate a store from document records."""
    store = {"schema_version": SCHEMA, "policy_id": policy_id,
             "data_version": data_version,
             "documents": deepcopy(documents),
             "limitations": list(limitations or [
                 "文档存储只包含已登记公告的正文段落，不是完整法规库。",
                 "publication_time 未知时，检索不得声称该文档在给定时间点已可得。",
             ])}
    validate_document_store(store)
    return store


def validate_document_store(store: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(store, dict) or store.get("schema_version") != SCHEMA:
        raise ValueError("invalid policy document store schema")
    doc_versions: set[str] = set()
    section_keys: set[tuple[str, str]] = set()
    section_count = 0
    for document in store.get("documents", []):
        if not isinstance(document, dict):
            raise ValueError("documents must be objects")
        version = document.get("doc_version")
        if not isinstance(version, str) or not version or version in doc_versions:
            raise ValueError("doc_version must be unique non-empty strings")
        doc_versions.add(version)
        if document.get("status") not in STATUSES:
            raise ValueError("document status is invalid")
        if document.get("publication_time_status") == "known" and not document.get("publication_time"):
            raise ValueError("publication_time_status known requires a publication_time")
        if compute_doc_version(document) != version:
            raise ValueError(f"doc_version digest does not match document content: {version}")
        source_hashes = {item.get("source_id"): item.get("text_sha256")
                         for item in document.get("sources", [])}
        by_source: dict[str, list[dict[str, Any]]] = {}
        for section in document.get("sections", []):
            if not isinstance(section, dict) or not isinstance(section.get("id"), str):
                raise ValueError("sections must be objects with ids")
            key = (version, section["id"])
            if key in section_keys:
                raise ValueError(f"duplicate section key: {version}:{section['id']}")
            section_keys.add(key)
            section_count += 1
            if not isinstance(section.get("text"), str) or not section["text"].strip():
                raise ValueError("sections must retain original text")
            by_source.setdefault(section.get("source_id"), []).append(section)
        for source_id, group in by_source.items():
            cursor = 0
            joined = ""
            for section in group:
                if section.get("start") != cursor or not isinstance(section.get("end"), int) \
                        or section["end"] < section["start"]:
                    raise ValueError(f"section offsets are not contiguous: {section['id']}")
                if len(section["text"]) != section["end"] - section["start"]:
                    raise ValueError(f"section text does not match its offsets: {section['id']}")
                cursor = section["end"]
                joined += section["text"]
            if hashlib.sha256(joined.encode("utf-8")).hexdigest() != source_hashes.get(source_id):
                raise ValueError(f"source text hash mismatch: {source_id}")
    return {"status": "valid", "schema_version": SCHEMA,
            "document_count": len(store.get("documents", [])),
            "section_count": section_count}


def get_section(store: dict[str, Any], doc_version: str, section_id: str) -> dict[str, Any] | None:
    for document in store.get("documents", []):
        if document.get("doc_version") != doc_version:
            continue
        for section in document.get("sections", []):
            if section.get("id") == section_id:
                return {"document": document, "section": section}
    return None


def set_document_status(store: dict[str, Any], doc_version: str, status: str) -> None:
    """Lifecycle change for the controlled update flow (offline helper)."""
    if status not in STATUSES:
        raise ValueError(f"document status must be one of {STATUSES}")
    for document in store.get("documents", []):
        if document.get("doc_version") == doc_version:
            document["status"] = status
            return
    raise ValueError(f"unknown doc_version: {doc_version}")


def citation_id(doc_version: str, section_id: str) -> str:
    """Stable citation: document version digest plus saved location."""
    return f"{doc_version}:{section_id}"


def deep_copy_store(store: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(store)
