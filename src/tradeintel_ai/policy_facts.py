"""Load the curated policy reference used by strict acceptance.

Structural validation does not certify independent human semantic review.

This is intentionally separate from retrieval.  Retrieval proposes passages;
this file records which official passages are allowed as the independent
reference for the paired evidence/no-evidence comparison.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


REFERENCE_RELATIVE = Path("data/processed/policy/section301_list1_facts.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _validate_iso_date_or_datetime(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"独立政策facts{label}无效")
    try:
        if "T" in value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"独立政策facts{label}无效") from exc
    return value


def load_frozen_policy_reference(root: str | Path) -> dict[str, Any]:
    """Validate and return the independent policy facts and source excerpts."""

    project_root = Path(root).resolve()
    path = project_root / REFERENCE_RELATIVE
    try:
        reference = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("独立政策facts文件无法读取") from exc
    if not isinstance(reference, Mapping) or reference.get("version") != "policy-facts-0119":
        raise ValueError("独立政策facts版本不受支持")
    if (reference.get("policy_id") != "us_301_list1_2018"
            or not isinstance(reference.get("question"), str)
            or not isinstance(reference.get("reviewer"), str)
            or not reference["reviewer"].strip()):
        raise ValueError("独立政策facts身份或审查人缺失")
    try:
        cutoff = date.fromisoformat(reference["as_of"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("独立政策facts截止日无效") from exc
    if cutoff.isoformat() != reference["as_of"]:
        raise ValueError("独立政策facts截止日必须使用标准日期")
    _validate_iso_date_or_datetime(reference.get("reviewed_at"), label="审查时间")

    corpus_relative = reference.get("corpus_path")
    if not isinstance(corpus_relative, str) or not corpus_relative.strip():
        raise ValueError("独立政策facts缺少语料路径")
    corpus_path = (project_root / corpus_relative).resolve()
    if not corpus_path.is_file() or not corpus_path.is_relative_to(project_root):
        raise ValueError("独立政策facts语料路径不安全")
    try:
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("政策语料无法读取") from exc
    chunks = {item.get("id"): item for item in corpus.get("chunks", [])
              if isinstance(item, Mapping) and isinstance(item.get("id"), str)}

    source_rows = reference.get("sources")
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("独立政策facts缺少官方来源")
    sources: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
            raise ValueError("官方来源记录无效")
        source_id = row["id"]
        if source_id in sources or source_id not in chunks:
            raise ValueError("官方来源未绑定已冻结语料片段")
        chunk = chunks[source_id]
        for key in ("title", "published", "url", "path", "sha256", "quote"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"官方来源缺少{key}")
        try:
            published = date.fromisoformat(row["published"])
        except ValueError as exc:
            raise ValueError("官方来源出版日期无效") from exc
        if published.isoformat() != row["published"]:
            raise ValueError("官方来源出版日期必须使用标准日期")
        if published > cutoff:
            raise ValueError("官方来源出版日期晚于题目截止日")
        if type(row.get("page")) is not int or row["page"] <= 0:
            raise ValueError("官方来源页码无效")
        local_path = (project_root / row["path"]).resolve()
        if not local_path.is_file() or not local_path.is_relative_to(project_root):
            raise ValueError("官方来源本地路径不安全或不存在")
        if _sha256(local_path) != row["sha256"] or chunk.get("sha256") != row["sha256"]:
            raise ValueError("官方来源文件哈希与语料不一致")
        if (chunk.get("page") != row["page"] or chunk.get("published") != row["published"]
                or chunk.get("url") != row["url"] or chunk.get("local_path") != row["path"]):
            raise ValueError("官方来源元数据与语料不一致")
        if _compact(row["quote"]) not in _compact(chunk.get("text", "")):
            raise ValueError("官方来源原文摘录不在冻结语料中")
        sources[source_id] = {
            "id": source_id,
            "title": row["title"],
            "published": row["published"],
            "page": row["page"],
            "url": row["url"],
            "path": row["path"],
            "sha256": row["sha256"],
            "text": row["quote"],
            "citation_url": f"{row['url']}#page={row['page']}",
        }

    facts = reference.get("facts")
    if not isinstance(facts, list) or not facts:
        raise ValueError("独立政策facts为空")
    fact_ids: set[str] = set()
    normalized_facts: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, Mapping) or not isinstance(fact.get("id"), str):
            raise ValueError("政策fact身份无效")
        fact_id = fact["id"]
        evidence_ids = fact.get("evidence_ids")
        if (fact_id in fact_ids or not fact_id.strip()
                or not isinstance(fact.get("claim"), str) or not fact["claim"].strip()
                or not isinstance(fact.get("expected_value"), str)
                or not fact["expected_value"].strip()
                or not isinstance(fact.get("acceptable_paraphrases"), list)
                or not fact["acceptable_paraphrases"]
                or any(not isinstance(item, str) or not item.strip()
                       for item in fact["acceptable_paraphrases"])
                or not isinstance(evidence_ids, list) or not evidence_ids
                or any(not isinstance(item, str) or not item.strip()
                       for item in evidence_ids)):
            raise ValueError("政策fact字段不完整")
        if any(item not in sources for item in evidence_ids):
            raise ValueError("政策fact引用了未知官方来源")
        fact_ids.add(fact_id)
        normalized_facts.append({
            "id": fact_id,
            "required_fact": fact["claim"],
            "expected_value": fact["expected_value"],
            "acceptable_paraphrases": tuple(fact["acceptable_paraphrases"]),
            "evidence_ids": tuple(evidence_ids),
        })
    result = deepcopy(dict(reference))
    result["facts"] = normalized_facts
    result["sources"] = list(sources.values())
    result["source_catalog"] = deepcopy(sources)
    result["reference_sha256"] = _sha256(path)
    result["corpus_sha256"] = _sha256(corpus_path)
    return result


def reference_evidence(reference: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the same frozen evidence map for both policy arms."""

    catalog = reference.get("source_catalog")
    if not isinstance(catalog, Mapping):
        raise ValueError("政策参考缺少source_catalog")
    return {str(key): deepcopy(dict(value)) for key, value in catalog.items()
            if isinstance(value, Mapping)}


__all__ = ["REFERENCE_RELATIVE", "load_frozen_policy_reference", "reference_evidence"]
