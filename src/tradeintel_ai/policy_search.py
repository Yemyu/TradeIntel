"""Policy search over the current registered corpus (offline; BM25 + exact HTS).

Search order is fixed by the Astra design and the R1 review (F5/F6):
  1. filter by policy_id / doc_version / publication cutoff / status
  2. exact HTS recall plus BM25 lexical scoring
  3. dependency completion from the evidence-backed required-dependency
     mapping registered on each document (effective date, origin,
     conditions, exceptions), attached complete and never cut by top_k

Isolation rules: the searcher is bound to one policy_id at construction and
every hit and dependency document must match it.  Only ``enabled`` documents
enter results; ``include_superseded`` opt-in admits ``superseded`` documents
for explicit historical reference but NEVER ``disabled`` ones, and document
status stays visible in every hit.  A missing or undetermined required
dependency yields ``incomplete_required_context`` instead of a silently
successful answer.  The 2018 ``policy_retrieval.PolicyRetriever`` and its
scope refusals stay untouched.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any

from .policy_documents import citation_id, compute_doc_version, validate_document_store

BRIDGE = {
    "钨": "tungsten", "多晶硅": "polysilicon silicon", "硅片": "wafers discs wafer",
    "税率": "rate of duty percent additional", "关税": "tariff duties duty",
    "加征": "additional percent rate", "生效": "take effect january", "实施": "take effect",
    "原产地": "china origin", "中国": "china", "入境": "entered for consumption",
    "入库": "withdrawn from warehouse", "提取消费": "withdrawn from warehouse consumption",
    "豁免": "exclusion excluded", "例外": "exception exclusion", "排除": "exclusion",
    "纯度": "percent by weight silicon", "时间": "time a.m. standard",
    "东部时间": "eastern standard time", "申报": "submit heading", "税号": "subheadings heading",
}
STOP = set("the a an of and or in on to for is are was were be by with this that what when how "
           "does it its as at from do for below following shall".split())
_HTS_PLAIN = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_HTS_DOTTED = re.compile(r"(?<!\d)(\d{4})\.(\d{2})\.(\d{2})(?!\d)")

DEPENDENCY_STATUSES = ("known", "verified_absent", "undetermined")


def tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z]+|\d+(?:\.\d+)*", text.lower()) if word not in STOP]


def normalize_hts8(text: str) -> list[str]:
    """8-digit codes in plain or dotted notation, normalized to HTS8."""
    codes = set(_HTS_PLAIN.findall(text or ""))
    for a, b, c in _HTS_DOTTED.findall(text or ""):
        codes.add(a + b + c)
    return sorted(codes)


def query_tokens(question: str) -> list[str]:
    expansion = " ".join(value for key, value in BRIDGE.items() if key in question)
    words = list(dict.fromkeys(tokens(question + " " + expansion)))
    # One/two digit numerics ("8" from "2018年8月") are query noise: they
    # match incidental digits without topical meaning.  Three-digit numbers
    # like 301/232 are tariff program numbers and stay.
    return [word for word in words
            if not (word.isdigit() and len(word) < 3)]


def _question_scope_refusal(question: str) -> str | None:
    """Current-corpus scope guard: archived bulletins, not a live tariff DB."""
    if re.search(r"现在|目前|今天|现行|实时|current|today|realtime", question, re.I):
        return "本语料是已登记公告的存档段落，不能回答实时现行税率。"
    return None


def set_required_dependencies(document: dict[str, Any],
                              mapping: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Register the evidence-backed required-dependency mapping on a document.

    Each dependency is either ``known`` (with the stable section IDs that
    carry it), ``verified_absent`` (determined absent from this document,
    with a note), or ``undetermined`` (no verified location yet -- any search
    touching this document must then report ``incomplete_required_context``).
    Section IDs are verified to exist; the mapping itself is provenance for
    the completion step and is not part of the text version digest.
    """
    sections_by_id = {section["id"] for section in document.get("sections", [])}
    cleaned: dict[str, dict[str, Any]] = {}
    for name, entry in mapping.items():
        status = entry.get("status")
        if status not in DEPENDENCY_STATUSES:
            raise ValueError(f"dependency {name} status must be one of {DEPENDENCY_STATUSES}")
        section_ids = entry.get("section_ids") or []
        if status == "known":
            if not section_ids:
                raise ValueError(f"known dependency {name} needs at least one section id")
            missing = [sid for sid in section_ids if sid not in sections_by_id]
            if missing:
                raise ValueError(f"dependency {name} cites unknown sections: {missing}")
        if status == "verified_absent" and not entry.get("note"):
            raise ValueError(f"verified_absent dependency {name} needs a note")
        cleaned[name] = {"status": status, "section_ids": list(section_ids),
                         "note": entry.get("note"),
                         "evidence": entry.get("evidence")}
    document["required_dependencies"] = cleaned
    return document


class PolicySearch:
    def __init__(self, store: dict[str, Any], *, scope_checker=None,
                 policy_id: str | None = None):
        validate_document_store(store)
        self.store = store
        self.policy_id = policy_id or store.get("policy_id")
        self.scope_checker = scope_checker or _question_scope_refusal
        self._sections = [
            {"document": document, "section": section}
            for document in store["documents"]
            for section in document.get("sections", [])
        ]
        self._term_counts = [Counter(tokens(item["section"]["text"])) for item in self._sections]
        self._lengths = [sum(counter.values()) for counter in self._term_counts]
        self._average = sum(self._lengths) / max(1, len(self._lengths))
        self._df = Counter(word for counter in self._term_counts for word in counter)

    # -- phase 1: filters -------------------------------------------------
    def _eligible(self, doc_versions: set[str] | None, as_of: str | None,
                  include_superseded: bool) -> tuple[list[dict[str, Any]], list[str]]:
        eligible: list[dict[str, Any]] = []
        excluded: list[str] = []
        for item in self._sections:
            document = item["document"]
            label = f"{document['doc_version']}:{item['section']['id']}"
            # Policy isolation first: a document from another policy never
            # enters this searcher's results, whatever its status.
            if document.get("policy_id") != self.policy_id:
                excluded.append(f"{label} (policy_id={document.get('policy_id')})")
                continue
            if document.get("status") == "enabled":
                pass
            elif document.get("status") == "superseded" and include_superseded:
                pass  # explicit historical reference only; disabled never passes
            else:
                excluded.append(f"{label} (status={document.get('status')})")
                continue
            if doc_versions is not None and document.get("doc_version") not in doc_versions:
                excluded.append(f"{label} (doc filter)")
                continue
            if as_of is not None:
                if document.get("publication_time_status") != "known":
                    excluded.append(f"{label} (publication_time unknown)")
                    continue
                if str(document.get("publication_time"))[:10] > as_of:
                    excluded.append(f"{label} (published after cutoff)")
                    continue
            eligible.append(item)
        return eligible, excluded

    # -- phase 2: recall --------------------------------------------------
    def _bm25(self, question: str, eligible: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        words = query_tokens(question)
        index = {id(item) for item in eligible}
        ranked = []
        for item, counter, length in zip(self._sections, self._term_counts, self._lengths):
            if id(item) not in index:
                continue
            score = 0.0
            for word in words:
                tf = counter.get(word, 0)
                if not tf:
                    continue
                idf = math.log(1 + (len(self._sections) - self._df[word] + 0.5) / (self._df[word] + 0.5))
                score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * length / self._average))
            if score > 0:
                ranked.append((score, item))
        # Merge key is (doc_version, section id): two versions of one
        # document may share local section ids.
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["document"]["doc_version"],
                                      pair[1]["section"]["id"]))
        return [{"score": round(score, 8), **pair} for score, pair in ranked[:top_k]]

    def _exact_hts(self, question: str, eligible: list[dict[str, Any]],
                   hts8: str | None) -> list[dict[str, Any]]:
        codes = set(normalize_hts8(question))
        if hts8:
            if not re.fullmatch(r"\d{8}", hts8):
                raise ValueError("hts8 filter must be an 8-digit string")
            codes.add(hts8)
        if not codes:
            return []
        hits = []
        for item in eligible:
            text = item["section"]["text"]
            section_codes = set(normalize_hts8(text))
            if codes & section_codes:
                hits.append({"score": None, "matched_codes": sorted(codes & section_codes), **item})
        hits.sort(key=lambda hit: (hit["document"]["doc_version"], hit["section"]["id"]))
        return hits

    # -- phase 3: dependency completion -----------------------------------
    def _required_context(self, document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        """Common clauses from the registered dependency mapping, complete.

        ``known`` dependencies contribute every registered section in full;
        ``verified_absent`` contributes an explicit absence note;
        ``undetermined`` or a missing registration makes the search incomplete.
        """
        context: list[dict[str, Any]] = []
        missing: list[str] = []
        mapping = document.get("required_dependencies")
        if not isinstance(mapping, dict) or not mapping:
            return context, [f"{document['doc_version']}:required_dependencies未登记（生效/原产地/条件/例外未确定）"]
        for name in sorted(mapping):
            entry = mapping[name]
            status = entry.get("status")
            if status == "known":
                for section_id in entry.get("section_ids", []):
                    found = next((s for s in document.get("sections", [])
                                  if s["id"] == section_id), None)
                    if found is None:
                        missing.append(f"{document['doc_version']}:{name}({section_id}缺失)")
                        continue
                    context.append({"dependency": name,
                                    "citation_id": citation_id(document["doc_version"], section_id),
                                    "section_id": section_id, "text": found["text"],
                                    "status": "known"})
            elif status == "verified_absent":
                context.append({"dependency": name, "citation_id": None,
                                "section_id": None, "text": None,
                                "status": "verified_absent", "note": entry.get("note"),
                                "evidence": entry.get("evidence")})
            else:
                missing.append(f"{document['doc_version']}:{name}(undetermined)")
        return context, missing

    # -- public API --------------------------------------------------------
    def search(self, question: str, *, hts8: str | None = None, as_of: str | None = None,
               top_k: int = 6, doc_versions: list[str] | None = None,
               include_superseded: bool = False) -> dict[str, Any]:
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError("问题须为1至2000字符")
        if type(top_k) is not int or not 1 <= top_k <= 10:
            raise ValueError("top_k须为1至10")
        result: dict[str, Any] = {
            "question": question, "policy_id": self.policy_id, "status": "no_evidence",
            "hits": [], "required_context": [], "excluded_fragments": [],
            "uncovered_codes": [],
            "limitations": list(self.store.get("limitations", [])),
            "boundary": "命中是候选证据，不是法律适用性结论；引用指向已保存原文的稳定位置。",
        }
        refusal = self.scope_checker(question)
        if refusal:
            result["status"] = "scope_refused"
            result["reason"] = refusal
            return result
        eligible, excluded = self._eligible(set(doc_versions) if doc_versions else None,
                                            as_of, include_superseded)
        result["excluded_fragments"] = excluded
        exact_hits = self._exact_hts(question, eligible, hts8)
        codes_in_question = set(normalize_hts8(question))
        if hts8:
            codes_in_question.add(hts8)
        if codes_in_question and not exact_hits:
            # An explicit HTS code that matches no section must never be
            # replaced by generic lexical hits for other products.
            result["reason"] = "问题指定了明确税号但语料中没有该税号的段落；不以其他商品的命中替代。"
            return result
        bm25_hits = self._bm25(question, eligible, top_k)
        # Exact HTS recall is precise evidence: it is never crowded out, and
        # top_k only limits the general (BM25) hits appended afterwards.
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for hit in bm25_hits:
            merged.setdefault((hit["document"]["doc_version"], hit["section"]["id"]), hit)
        covered_codes: set[str] = set()
        for hit in exact_hits:
            covered_codes.update(hit.get("matched_codes") or [])
            merged.pop((hit["document"]["doc_version"], hit["section"]["id"]), None)
        ranked = exact_hits + list(merged.values())[:top_k]
        result["uncovered_codes"] = sorted(codes_in_question - covered_codes)

        # Re-check status right before returning: a document disabled between
        # phases must never enter the result.
        hits = [hit for hit in ranked
                if hit["document"].get("status") == "enabled"
                or (hit["document"].get("status") == "superseded" and include_superseded)]
        if not hits:
            superseded_only = bool(excluded) and not eligible
            result["status"] = "no_evidence"
            result["reason"] = ("相关内容只存在于停用或已被取代的版本；默认检索不返回。" if superseded_only
                                else "限定语料内没有词法匹配；不调用模型补猜。")
            return result
        context: list[dict[str, Any]] = []
        missing: list[str] = []
        seen_docs: set[str] = set()
        for hit in hits:
            if hit["document"]["doc_version"] in seen_docs:
                continue
            seen_docs.add(hit["document"]["doc_version"])
            if hit["document"].get("status") != "enabled":
                # Superseded reference hits are historical context; the
                # dependency requirement applies to current documents.
                continue
            doc_context, doc_missing = self._required_context(hit["document"])
            context.extend(doc_context)
            missing.extend(doc_missing)
        result["hits"] = [{
            "citation_id": citation_id(hit["document"]["doc_version"], hit["section"]["id"]),
            "doc_version": hit["document"]["doc_version"],
            "doc_id": hit["document"]["doc_id"],
            "policy_id": hit["document"].get("policy_id"),
            "document_status": hit["document"].get("status"),
            "source_id": hit["section"].get("source_id"),
            "page": next((src.get("page") for src in hit["document"].get("sources", [])
                          if src.get("source_id") == hit["section"].get("source_id")), None),
            "section_id": hit["section"]["id"],
            "start": hit["section"]["start"], "end": hit["section"]["end"],
            "offset_unit": hit["document"].get("offset_unit", "character"),
            "text": hit["section"]["text"],
            "url": next((src.get("url") for src in hit["document"].get("sources", [])
                         if src.get("source_id") == hit["section"].get("source_id")),
                        hit["document"].get("url")),
            "score": hit.get("score"),
            "matched_codes": hit.get("matched_codes"),
        } for hit in hits]
        result["required_context"] = context
        if missing:
            result["status"] = "incomplete_required_context"
            result["missing_dependencies"] = missing
            result["reason"] = "命中商品的公告缺少已登记的共同条款（或依赖未确定），必须补齐后才能进入报告。"
        else:
            result["status"] = "candidate_evidence"
        return result


__all__ = ["DEPENDENCY_STATUSES", "PolicySearch", "normalize_hts8",
           "query_tokens", "set_required_dependencies", "tokens"]
