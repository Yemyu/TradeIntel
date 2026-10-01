"""Read-only, bounded tools for the local trade research assistant."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .trade_classification_catalog import (ClassificationCatalog, ZH_HS4, ZH_SEARCH_SYNONYMS,
    REVIEWED_HEADINGS, reviewed_heading_matches, validate_reviewed_heading_scope)
from .trade_data_repository import TradeDataError, TradeDataRepository, TradeQuery
from .trade_export_repository import ExportDataRepository, ExportTradeQuery
from .trade_query_flow import _add_month, _report_from_facts
from .trade_report_store import create_record
from .trade_explanation_v4 import PROTOCOL as EXPLANATION_PROTOCOL
from .trade_agent_request import (derive_constraints, validate_query_constraints,
                                 validate_finished_scope, RequestConstraintError)


FLOWS = {"import", "export", "both"}
_DIRECT_SYNONYMS = {"稻米", "稻谷", "大米", "乘用车", "轿车", "卡车", "原油"}
_LAST_MONTH = re.compile(r"上个月|上月|上一个月|\blast month\b", re.I)
_MONTH_COMPARISON = re.compile(r"同比|环比|相比|对比|比较|较|比|变化|趋势|以来|至今|去年|前月|过去", re.I)


def _policy_evidence_identity(bundle: dict) -> dict:
    stable = deepcopy(bundle)
    for key in ("score", "matched_codes"):
        stable["hit"].pop(key, None)
    return stable


@dataclass(frozen=True)
class CalendarMonthAnchor:
    month: str
    single_month: bool


class RequestedMonthUnavailable(TradeDataError):
    def __init__(self, month: str, latest: str | None):
        self.month = month
        self.latest = latest
        super().__init__(f"用户指定的是日历上月；缺少 {month} 的已核验可查询数据。"
                         f"最新可用月为 {latest or '无'}。如需改查最新可用月，请明确提出。")


def _calendar_month_anchor(question: str, today: date) -> CalendarMonthAnchor | None:
    """Bind a narrow, explicit last-calendar-month phrase; not general date NLU."""
    match = _LAST_MONTH.search(question)
    if not match:
        return None
    prefix = question[max(0, match.start() - 8):match.start()]
    if re.search(r"(?:不是|并非|不要(?:查)?|不查|别(?:查)?|not)\s*$", prefix, re.I):
        return None
    month = _add_month(f"{today.year:04d}-{today.month:02d}", -1)
    return CalendarMonthAnchor(month, not bool(_MONTH_COMPARISON.search(question)))


def _direct_product_match(term: str, candidate: dict[str, Any]) -> bool:
    """Only promote an unambiguous name/code, never mere substring overlap.

    Official descriptions and extracted Chinese headings are useful for
    discovery, but they may mention a commodity as an ingredient, an example,
    or an exclusion. A related result remains visible for clarification.
    """
    code = candidate["code"]
    if term.strip().casefold() in {str(candidate.get("official_en", "")).casefold(),
                                  str(candidate.get("zh_label") or "").casefold()}:
        return True
    if term.strip() == code or re.search(
            rf"(?:hs\s*\d*|税号|编码)\s*[:：]?\s*{re.escape(code)}(?!\d)", term, re.I):
        return True
    entry = ZH_HS4.get(code)
    if entry and code != "2101" and any(alias in term for alias in entry[2]):
        return True
    if any(word in term and code in ZH_SEARCH_SYNONYMS[word]
           for word in _DIRECT_SYNONYMS):
        return True
    english = term.strip().lower()
    if re.fullmatch(r"[a-z][a-z\s-]{1,60}", english):
        label = candidate["official_en"].lower()
        if english == label:
            return True
        reviewed = {"corn": "1005", "maize": "1005", "tea": "0902", "rice": "1006",
                    "wheat": "1001", "coffee": "0901"}
        return reviewed.get(english) == code
    return False


def _question_product_anchors(question: str) -> set[str]:
    """Protect explicit user commodity names from a model's different search.

    This is deliberately a small, high-confidence guard, not a general intent
    parser. An unrecognised product still goes through candidate discovery.
    """
    remaining = question.lower()
    anchors: set[str] = reviewed_heading_matches(question)
    # A full registered heading is stronger than a shared everyday alias.
    normalized = remaining.replace("的", "")
    for code, (heading, _, _) in ZH_HS4.items():
        full = heading.replace("的", "")
        if len(full) > 2 and full in normalized:
            anchors.add(code)
            normalized = normalized.replace(full, " ")
    remaining = normalized
    for pattern, code in ((r"大豆油|(?<!可可)豆油|soybean\s+oil", "1507"),
                          (r"豆粕|soybean\s+meal", "2304")):
        if re.search(pattern, remaining):
            anchors.add(code)
            remaining = re.sub(pattern, " ", remaining)
    # These processed names must not accidentally promote the raw commodity.
    remaining = re.sub(r"玉米淀粉|corn\s+starch|玉米片|corn\s+flakes", " ", remaining)
    for code, (_, _, aliases) in ZH_HS4.items():
        if code != "2101" and any(alias in remaining for alias in aliases):
            anchors.add(code)
    for word in _DIRECT_SYNONYMS:
        if word in remaining:
            anchors.update(ZH_SEARCH_SYNONYMS[word])
    for word, code in (("soybean", "1201"), ("corn", "1005"),
                       ("rice", "1006"), ("tea", "0902")):
        if re.search(rf"\b{word}s?\b", remaining):
            anchors.add(code)
    explicit = re.findall(r"(?:hs\s*4|税号|编码)\s*[:：]?\s*(\d{4})(?!\d)", remaining)
    anchors.update(explicit)
    shared: dict[str, set[str]] = {}
    for code, (_, _, aliases) in ZH_HS4.items():
        if code != "2101":
            for alias in aliases:
                shared.setdefault(alias, set()).add(code)
    for alias, codes in shared.items():
        if alias in remaining and codes.intersection(explicit):
            anchors.difference_update(codes - set(explicit))
    return anchors


def _months(root: Path, flow: str) -> tuple[list[str], dict[str, str]]:
    versions: dict[str, str] = {}
    sets: list[set[str]] = []
    if flow in {"import", "both"}:
        catalog = TradeDataRepository(root).catalog()
        versions["import"] = catalog["dataset_version"]
        sets.append({row.get("month_key") or row["month"] for row in catalog["months"]
                     if row["status"] == "queryable_aggregate"})
    if flow in {"export", "both"}:
        catalog = ExportDataRepository(root).catalog()
        versions["export"] = catalog["dataset_version"]
        sets.append({row.get("month_key") or row["month"] for row in catalog["months"]
                     if row["status"] == "queryable_aggregate"})
    return sorted(set.intersection(*sets)) if sets else [], versions


def _period(value: dict[str, Any], months: list[str], today: date) -> tuple[str, str]:
    if not months:
        raise TradeDataError("没有已核验的可查询月份")
    if not isinstance(value, dict) or value.get("type") not in {
        "latest_contiguous", "absolute", "calendar_relative"
    }:
        raise TradeDataError("月份范围类型无效")
    kind = value["type"]
    if kind == "latest_contiguous":
        count = value.get("count", 12)
        if type(count) is not int or not 1 <= count <= 24:
            raise TradeDataError("最近月份数量须为1至24")
        end = months[-1]
        start = end
        for _ in range(count - 1):
            previous = _add_month(start, -1)
            if previous not in months:
                break
            start = previous
    elif kind == "absolute":
        start, end = value.get("start"), value.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            raise TradeDataError("请提供明确的起止月份")
    else:
        unit, offset = value.get("unit"), value.get("offset")
        if unit not in {"month", "year"} or type(offset) is not int or offset not in {-2, -1, 0}:
            raise TradeDataError("相对日历月份或年份无效")
        if unit == "month":
            start = end = _add_month(f"{today.year:04d}-{today.month:02d}", offset)
        else:
            start, end = f"{today.year + offset:04d}-01", f"{today.year + offset:04d}-12"
            if offset == 0:
                end = f"{today.year:04d}-{today.month:02d}"
    if not (re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", start or "") and
            re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", end or "")):
        raise TradeDataError("月份必须使用 YYYY-MM")
    first, last = int(start[:4]) * 12 + int(start[5:]), int(end[:4]) * 12 + int(end[5:])
    if last < first or last - first >= 24:
        raise TradeDataError("单次查询最多24个月")
    missing = [_add_month(start, index) for index in range(last - first + 1)
               if _add_month(start, index) not in months]
    if missing:
        raise TradeDataError(f"{start} 至 {end} 无法完整查询；缺少 {', '.join(missing[:4])}。最新已发布月为 {months[-1]}")
    return start, end


class TradeAgentTools:
    def __init__(self, data_root: Path, code_root: Path, *, today: date | None = None,
                 question: str = "", previous_scope: dict | None = None):
        self.data_root = Path(data_root)
        self.code_root = Path(code_root)
        self.today = today or date.today()
        self.question = question
        self.request_constraints = derive_constraints(question, previous_scope, self.today)
        self.request_constraints["product_anchors"] = sorted(_question_product_anchors(question))
        aliases: dict[str, set[str]] = {}
        for code, (_, _, names) in ZH_HS4.items():
            if code != "2101":
                for name in names:
                    aliases.setdefault(name, set()).add(code)
        for alias, codes in aliases.items():
            anchored = set(self.request_constraints["product_anchors"]) & codes
            if alias in question and len(anchored) > 1 and not re.search(r"税号|编码|hs\s*4", question, re.I):
                names = "、".join(f"{ZH_HS4[code][0]}（{code}）" for code in sorted(anchored))
                self.request_constraints["issues"].append(f"商品“{alias}”对应多个范围：{names}；请说明要查询哪一种。")
        self.calendar_month_anchor = _calendar_month_anchor(question, self.today)
        self.catalog = ClassificationCatalog(self.data_root)
        self.candidates: dict[str, dict[str, Any]] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self.policy_sources: dict[str, dict[str, Any]] = {}
        self.policy_bundles: dict[str, dict[str, Any]] = {}
        self.policy_searches: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []

    def coverage(self) -> dict[str, Any]:
        coverage = {}
        for flow in ("import", "export", "both"):
            months, _ = _months(self.data_root, flow)
            coverage[flow] = {"latest": months[-1] if months else None,
                              "earliest": months[0] if months else None,
                              "count": len(months)}
        return {"status": "ok", "reporter": "US", "partners": ["all", "china"],
                "today": self.today.isoformat(), "coverage": coverage,
                "note": "贸易统计按已发布月提供；政策资料不会自动联网更新。"}

    def search_products(self, term: str, flow: str) -> dict[str, Any]:
        if (not isinstance(term, str) or not term.strip() or len(term) > 120
                or flow not in FLOWS):
            raise TradeDataError("商品搜索参数无效")
        compound = re.search(r"大豆油|(?<!可可)豆油|豆粕|soybean\s+(?:oil|meal)|玉米淀粉|corn\s+starch",
                             term, re.I)
        search_term = term.strip()
        preferred = None
        raw_soy = bool(re.fullmatch(r"soybeans?|soya\s+beans?", search_term, re.I))
        if raw_soy:
            search_term, preferred = "soybeans", "1201"
        elif compound:
            word = compound.group().lower()
            if word in {"大豆油", "豆油", "soybean oil"}:
                search_term, preferred = "soybean oil", "1507"
            elif word in {"豆粕", "soybean meal"}:
                search_term, preferred = "soybean oilcake", "2304"
            else:
                search_term = "corn starch"
        candidates = self.catalog.search(search_term, flow)
        if compound or raw_soy:
            fallback = self.catalog.search(term.strip(), flow)
            known = {item["id"] for item in candidates}
            candidates.extend(item for item in fallback if item["id"] not in known)
            candidates.sort(key=lambda item: (item["code"] != preferred, item["code"]))
        for item in candidates:
            item["match_type"] = ("exact_product" if item["code"] == preferred or
                                  (not compound and not raw_soy and _direct_product_match(search_term, item))
                                  else "heading_family" if item["code"] in reviewed_heading_matches(term)
                                  else "related_candidate")
            if item["match_type"] != "related_candidate" and item["code"] in REVIEWED_HEADINGS:
                _, item["scope_note"], item["scope_note_en"] = REVIEWED_HEADINGS[item["code"]]
            item["supported_flows"] = ["both", "import", "export"] if flow == "both" else [flow]
        candidates.sort(key=lambda item: {"exact_product": 0, "heading_family": 1, "related_candidate": 2}[item["match_type"]])
        for item in candidates:
            self.candidates[item["id"]] = item
        return {"status": "ok" if candidates else "no_match", "flow": flow,
                "catalog_version": self.catalog.version,
                "candidates": [{key: item.get(key) for key in
                                ("id", "code", "level", "official_en", "zh_label",
                                 "description_kind", "child_codes", "match_type", "scope_note",
                                 "scope_note_en", "supported_flows")} for item in candidates],
                "note": "准确商品排在前面，相关候选随后；请核对加工形态，不能只凭排名选定。"}

    def query_trade(self, candidate_id: str, flow: str, partner: str,
                    period: dict[str, Any]) -> dict[str, Any]:
        if flow not in FLOWS or partner not in {"all", "china"}:
            raise TradeDataError("贸易方向或伙伴参数无效")
        candidate = self.candidates.get(candidate_id)
        projected = bool(candidate and candidate["flow"] == "both" and flow in {"import", "export"}
                         and len(candidate["code"]) in {4, 6})
        if not candidate or (candidate["flow"] != flow and not projected):
            raise TradeDataError("须先从本轮目录结果选出相同方向的商品")
        if candidate.get("match_type") not in {"exact_product", "heading_family"}:
            raise TradeDataError("这只是相关商品，不能自动当作用户所问商品；请澄清具体范围或明确税号")
        anchors = _question_product_anchors(self.question)
        validate_reviewed_heading_scope(self.question, candidate["code"])
        if anchors and candidate["code"] not in anchors:
            raise TradeDataError("商品与用户原问题不一致；请重新搜索或澄清具体范围")
        if (candidate["code"] in {"1201", "1005"} and re.search(
                r"大豆油|(?<!可可)豆油|豆粕|soybean\s+(?:oil|meal)|玉米淀粉|corn\s+starch",
                self.question, re.I)):
            raise TradeDataError("这只是相关商品，不能自动当作用户所问商品；请澄清具体范围")
        months, versions = _months(self.data_root, flow)
        anchor = self.calendar_month_anchor
        if anchor and anchor.month not in months:
            raise RequestedMonthUnavailable(anchor.month, months[-1] if months else None)
        start, end = _period(period, months, self.today)
        validate_query_constraints(self.request_constraints, candidate, flow, partner, start, end)
        if anchor and anchor.single_month and (start, end) != (anchor.month, anchor.month):
            raise TradeDataError(f"用户问的是日历上月 {anchor.month}，不能改为 {start} 至 {end}")
        required = []
        current = start
        while current <= end:
            required.append(current)
            current = _add_month(current, 1)
        selected_id = f"{flow}:{candidate['code']}" if projected else candidate_id
        selected = self.catalog.validate_choice(selected_id, candidate["catalog_version"], flow, required)
        code = selected["code"]
        if partner == "china":
            partner_value = "CHINA"
        else:
            partner_value = "ALL_DESTINATIONS" if flow == "export" else "ALL_ORIGINS"
        version = (hashlib.sha256(json.dumps(versions, sort_keys=True).encode()).hexdigest()
                   if flow == "both" else versions[flow])
        scope = {"status": "ready", "kind": "trade-query-v1", "reporter": "US", "flow": flow,
                 "product_code": code, "product_label": selected["zh_label"] or selected["official_en"],
                 "official_product_en": selected["official_en"],
                 "selected_product_id": selected_id, "source_candidate_id": candidate_id,
                 "catalog_version": self.catalog.version,
                 "start_month": start, "end_month": end, "latest_available_month": months[-1],
                 "partner": partner_value, "dataset_version": version,
                 "dataset_versions": versions, "metric": "mixed_separate" if flow == "both" else
                 "total_export_fas_usd" if flow == "export" else "import_value_consumption_usd",
                 "classification_source_urls": list(dict.fromkeys(
                     self.catalog.entries[(direction, month)]["source_url"]
                     for month in required for direction in
                     (("import", "export") if flow == "both" else (flow,)))),
                 "coverage_note": candidate.get("scope_note"),
                 "coverage_note_en": candidate.get("scope_note_en")}
        if flow in {"export", "both"} and 1 < len(required) < 12:
            zh = f"出口本次只含{len(required)}个月，不能据此判断长期趋势。"
            en = f"This query covers only {len(required)} export months and cannot establish a long-term trend."
            scope["coverage_note"] = " ".join(filter(None, [scope["coverage_note"], zh]))
            scope["coverage_note_en"] = " ".join(filter(None, [scope["coverage_note_en"], en]))
        question = f"美国{scope['product_label']}{'进出口' if flow == 'both' else '进口' if flow == 'import' else '出口'}"
        def read(direction: str) -> dict[str, Any]:
            dest = "CHINA" if partner == "china" else (
                "ALL_ORIGINS" if direction == "import" else "ALL_DESTINATIONS")
            if direction == "import":
                return TradeDataRepository(self.data_root).query(TradeQuery(
                    "US", "import", code, start, end, dest, versions["import"]))
            return ExportDataRepository(self.data_root).query(ExportTradeQuery(
                "US", "export", code, start, end, dest, versions["export"]))
        if flow == "both":
            report = {"kind": "trade-query-both-v1", "question": question, "scope": scope,
                      "import_report": _report_from_facts(question, dict(scope, flow="import",
                          partner="CHINA" if partner == "china" else "ALL_ORIGINS",
                          metric="import_value_consumption_usd"), read("import")),
                      "export_report": _report_from_facts(question, dict(scope, flow="export",
                          partner="CHINA" if partner == "china" else "ALL_DESTINATIONS",
                          metric="total_export_fas_usd"), read("export")),
                      "ai_status": "not_run",
                      "notes": ["进口消费额与出口 FAS 总额口径不同，不能相减称为贸易差额。"]}
        else:
            report = _report_from_facts(question, scope, read(flow))
        saved = create_record(self.code_root, report, explanation_protocol=EXPLANATION_PROTOCOL)
        self.reports[saved["report_id"]] = saved
        parts = [saved["import_report"], saved["export_report"]] if flow == "both" else [saved]
        summaries = [{"flow": part["scope"]["flow"], "summary": part["summary"],
                      "sources": part["sources"][:8]} for part in parts]
        return {"status": "ok", "report_id": saved["report_id"],
                "product": scope["product_label"], "code": code, "flow": flow,
                "period": {"start": start, "end": end, "latest_available": months[-1]},
                "scope_note": scope["coverage_note"], "scope_note_en": scope["coverage_note_en"],
                "results": summaries,
                "note": "图表和金额已经由程序计算；仅凭金额变化不能推断政策影响。"}

    def validate_finish_period(self, report_ids: list[str]) -> None:
        validate_finished_scope(self.request_constraints, [self.reports[item] for item in report_ids])
        anchors = set(self.request_constraints["product_anchors"])
        if len(anchors) > 1:
            answered = {self.reports[item]["scope"]["product_code"] for item in report_ids}
            if not anchors.issubset(answered):
                raise RequestConstraintError("问题涉及多个明确商品，当前报告没有涵盖全部商品；请补查或澄清范围。", "product")
        anchor = self.calendar_month_anchor
        if not anchor:
            return
        scopes = [self.reports[item]["scope"] for item in report_ids]
        if anchor.single_month:
            valid = all((scope["start_month"], scope["end_month"]) ==
                        (anchor.month, anchor.month) for scope in scopes)
        else:
            valid = any(scope["start_month"] <= anchor.month <= scope["end_month"]
                        for scope in scopes)
        if not valid:
            raise TradeDataError(f"报告没有回答用户指定的日历上月 {anchor.month}；不能用其他月份代替")

    def search_policy(self, query: str, candidate_id: str | None = None) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise TradeDataError("政策检索问题无效")
        candidate = self.candidates.get(candidate_id) if candidate_id else None
        if candidate_id and not candidate:
            raise TradeDataError("政策检索的商品须来自本轮目录结果")
        from .announcement_store import load_announcement_store
        from .policy_search import PolicySearch
        from .trade_agent_policy_evidence import evidence_bundles, evidence_summary
        directory = self.code_root / ".local" / "announcement-docs"
        hits = []
        accepted = []
        diagnostics = []
        limited = False
        if directory.is_dir():
            paths = sorted(directory.glob("*.json"))
            limited = len(paths) > 40
            for path in paths[:40]:
                if path.is_symlink() or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", path.stem):
                    continue
                store = load_announcement_store(self.code_root, path.stem)
                if not any(doc.get("status") == "enabled" for doc in store["documents"]):
                    continue
                hts8 = candidate["code"] if candidate and len(candidate["code"]) == 8 else None
                result = PolicySearch(store).search(query, hts8=hts8, top_k=3)
                diagnostic = {key: result.get(key) for key in
                              ("status", "reason", "policy_id", "missing_dependencies",
                               "limitations", "uncovered_codes")}
                diagnostic.update(query=query, candidate_id=candidate_id,
                                  doc_versions=sorted({h["doc_version"] for h in result["hits"]}))
                diagnostics.append(diagnostic)
                for bundle in evidence_bundles(store, result):
                    if len(hits) >= 6:
                        limited = True
                        break
                    entry = bundle["hit"]
                    proposed = {"hits": hits + [entry], "policy_evidence":
                                evidence_summary(diagnostics, accepted + [bundle])}
                    if (len(json.dumps(bundle, ensure_ascii=False)) > 12_000 or
                            len(json.dumps(proposed, ensure_ascii=False)) > 20_000):
                        limited = True
                        continue
                    citation = entry["citation_id"]
                    same_call = next((item for item in accepted
                                      if item["hit"]["citation_id"] == citation), None)
                    existing = self.policy_bundles.get(citation) or same_call
                    if existing is not None and _policy_evidence_identity(existing) != _policy_evidence_identity(bundle):
                        raise TradeDataError("同一政策引用对应不同原文或依赖，不能合并。")
                    if same_call is not None:
                        continue
                    accepted.append(bundle)
                    hits.append(entry)
        if not diagnostics:
            diagnostics.append({"query": query, "status": "no_evidence",
                                "reason": "本地没有可检索的已启用公告。"})
        if limited:
            diagnostics.append({"query": query, "status": "limited",
                                "reason": "达到文档、命中或完整证据预算上限；未截断法律条款。"})
        self.policy_searches.extend(diagnostics)
        evidence = evidence_summary(diagnostics, accepted)
        payload = {"status": evidence["status"], "hits": hits,
                "policy_evidence": evidence,
                "note": "只检索本地已启用公告；无命中不代表不存在政策。命中也不是适用性结论。"}
        if len(json.dumps(payload, ensure_ascii=False)) > 25_000:
            # Keep the complete diagnostics in the ledger, but send no legal
            # evidence unit if the whole transport would exceed its limit.
            accepted = []
            notice = {"query": query, "status": "limited",
                      "reason": "完整检索诊断超过工具预算，未向模型发送证据；原诊断仍保留。"}
            self.policy_searches.append(notice)
            payload = {"status": "limited", "hits": [],
                       "policy_evidence": evidence_summary([notice], [])}
        for bundle in accepted:
            entry = bundle["hit"]
            self.policy_sources.setdefault(entry["citation_id"], entry)
            self.policy_bundles.setdefault(entry["citation_id"], bundle)
        return payload
