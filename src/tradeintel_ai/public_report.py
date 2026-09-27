"""Reader-facing report object built from deterministic temporal evidence.

The report object is the hand-off point for the later web page.  It keeps
program facts and optional model explanations in separate fields, so a model
cannot create a number, source, or comparison that was not present in the
evidence contract.
"""
from __future__ import annotations

from copy import deepcopy
import html
import json
import re
from typing import Any, Mapping

from .temporal_evidence import (render_temporal_evidence,
                                validate_temporal_evidence)
from .policy_facts_contract import validate_policy_facts


SCHEMA_VERSION = "public-report-v1"


def _default_watchlist(evidence: Mapping[str, Any], *, has_policy: bool = False) -> list[dict[str, str]]:
    """Create bounded, non-advisory follow-ups for a program-only report."""
    items: list[dict[str, str]] = [{
        "watch_id": "next_trade_release",
        "rationale": "等待下一期官方贸易统计发布后，按同一政策范围和数据版本规则重新核对。",
    }]
    if has_policy:
        items.append({
            "watch_id": "policy_revision",
            "rationale": "若官方公告、税率、生效日或适用税号发生变化，应先登记新版本再重新分析。",
        })
    if not has_policy and any(item.get("kind") == "composition" for item in evidence.get("observations", [])):
        items.append({
            "watch_id": "origin_mix",
            "rationale": "继续观察主要来源地结构；来源排名跨期变化仍需单独核对编码口径。",
        })
    limitations = evidence.get("limitations") or []
    if limitations or any(item.get("status") == "unknown"
                          for item in evidence.get("metrics", [])):
        items.append({
            "watch_id": "coverage_gap",
            "rationale": "若补齐缺失月份或口径审核，应重新生成对应比较，不把未知当作零或趋势。",
        })
    elif not has_policy:
        items.append({
            "watch_id": "policy_revision",
            "rationale": "若官方公告、税率、生效日或适用税号发生变化，应先登记新版本再重新分析。",
        })
    elif any(item.get("kind") == "composition" for item in evidence.get("observations", [])):
        items.append({
            "watch_id": "origin_mix",
            "rationale": "继续观察主要来源地结构；来源排名跨期变化仍需单独核对编码口径。",
        })
    return items[:3]


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    import hashlib
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def _reader_status(status: Any) -> str:
    if status in {None, "unknown", "undetermined", "not_checked", "unverified"}:
        return "尚未核实"
    if status in {"verified", "known", "confirmed", "reviewed"}:
        return "已核实"
    if status == "not_applicable":
        return "不适用"
    if status in {"conflict", "incompatible"}:
        return "记录存在冲突，需进一步核对"
    return "需进一步核对"


def _policy_source_link(source_id: str, sources: Mapping[str, Mapping[str, Any]]) -> str:
    source = sources.get(source_id)
    url = source.get("url") if source else None
    if not isinstance(url, str) or not url.startswith("https://"):
        return "政策原文"
    suffix = source_id.rsplit(":", 1)[-1]
    page = re.fullmatch(r"p(\d+)", suffix)
    label = f"CBP公告第{page.group(1)}页" if page else "CBP官方公告"
    return f"[{label}]({url})"


def _observation_label(evidence: Mapping[str, Any], observation_id: str) -> str:
    observation = next((item for item in evidence.get("observations", [])
                        if item.get("id") == observation_id), None)
    if not observation:
        return "已核对的数据观察"
    scope = observation.get("scope") or {}
    product = str(scope.get("product") or "")
    label = f"HTS {product}" if product else "商品"
    period = scope.get("period")
    if observation.get("kind") == "comparison":
        base = scope.get("base_period")
        if isinstance(base, str) and isinstance(period, str):
            same_month = base[5:7] == period[5:7]
            one_year = int(period[:4]) - int(base[:4]) == 1
            comparison = "同比" if same_month and one_year else "环比" if base[:4] == period[:4] else "跨期比较"
            return f"{label}，{base}至{period}{comparison}"
        return f"{label}的跨期比较"
    if observation.get("kind") == "composition":
        return f"{label}，{period or ''}来源构成".strip("，")
    if period:
        return f"{label}，{period}贸易金额与来源份额"
    return label


def build_public_report(evidence: Mapping[str, Any], request: Mapping[str, Any], *,
                        explanations: list[Mapping[str, Any]] | None = None,
                        policy_explanations: list[Mapping[str, Any]] | None = None,
                        watchlist: list[Mapping[str, Any]] | None = None,
                        policy_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a report envelope with separately bound trade and policy prose."""
    validate_temporal_evidence(evidence, request)
    clean_policy = deepcopy(dict(policy_context or {}))
    if clean_policy:
        validate_policy_facts(clean_policy)
        if (clean_policy.get("policy_id") != request.get("policy_id")
                or clean_policy.get("data_version") != evidence.get("data_version")
                or clean_policy.get("policy_view") != request.get("policy_view")):
            raise ValueError("政策事实与报告请求绑定不一致")
    observation_ids = {item["id"] for item in evidence["observations"]}
    clean_explanations: list[dict[str, Any]] = []
    for item in explanations or []:
        if not isinstance(item, Mapping) or set(item) != {"observation_id", "kind", "text"}:
            raise ValueError("解释项字段无效")
        if item["observation_id"] not in observation_ids:
            raise ValueError("解释引用了不存在的观察")
        if item["kind"] not in {"meaning", "hypothesis"}:
            raise ValueError("解释 kind 无效")
        if not isinstance(item["text"], str) or not 1 <= len(item["text"].strip()) <= 350:
            raise ValueError("解释文字长度无效")
        clean_explanations.append(deepcopy(dict(item)))
    if len(clean_explanations) > 6:
        raise ValueError("解释项最多六条")
    policy_source_ids = {str(item.get("id")) for item in clean_policy.get("sources") or []}
    clean_policy_explanations: list[dict[str, Any]] = []
    seen_policy_topics: set[str] = set()
    for item in policy_explanations or []:
        if not isinstance(item, Mapping) or set(item) != {"topic", "source_ids", "text"}:
            raise ValueError("政策解释项字段无效")
        topic, source_ids, text = item["topic"], item["source_ids"], item["text"]
        if not isinstance(topic, str) or topic not in {"change", "applicability", "limits"} or topic in seen_policy_topics:
            raise ValueError("政策解释主题无效或重复")
        if (not policy_source_ids or not isinstance(source_ids, list) or not source_ids
                or any(not isinstance(source_id, str) or source_id not in policy_source_ids for source_id in source_ids)
                or len(set(source_ids)) != len(source_ids)):
            raise ValueError("政策解释来源未绑定政策原文")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 350:
            raise ValueError("政策解释文字长度无效")
        seen_policy_topics.add(topic)
        clean_policy_explanations.append({"topic": topic,
                                          "source_ids": list(source_ids),
                                          "text": text.strip()})
    if watchlist is None:
        watchlist = _default_watchlist(evidence, has_policy=bool(clean_policy))
    watch_ids: set[str] = set()
    clean_watchlist: list[dict[str, Any]] = []
    for item in watchlist or []:
        if not isinstance(item, Mapping) or set(item) != {"watch_id", "rationale"}:
            raise ValueError("观察清单字段无效")
        if not isinstance(item["watch_id"], str) or item["watch_id"] in watch_ids:
            raise ValueError("观察清单 ID 无效或重复")
        if item["watch_id"] not in {"next_trade_release", "origin_mix",
                                     "policy_revision", "coverage_gap"}:
            raise ValueError("观察清单类型不受支持")
        if not isinstance(item["rationale"], str) or not 1 <= len(item["rationale"].strip()) <= 200:
            raise ValueError("观察清单理由长度无效")
        watch_ids.add(item["watch_id"])
        clean_watchlist.append(deepcopy(dict(item)))
    if len(clean_watchlist) > 3:
        raise ValueError("观察清单最多三条")
    report = {
        "schema_version": SCHEMA_VERSION,
        "request": deepcopy(dict(request)),
        "request_digest": evidence["request_digest"],
        "data_version": evidence["data_version"],
        "evidence": deepcopy(dict(evidence)),
        "policy_context": clean_policy,
        "explanations": clean_explanations,
        "watchlist": clean_watchlist,
        "review_status": "explanation_draft" if clean_explanations or clean_policy_explanations else "program_only",
        "generation_channel": "deterministic",
    }
    if clean_policy_explanations:
        report["policy_explanations"] = clean_policy_explanations
    report["report_sha256"] = _sha(report)
    return report


def render_public_report(report: Mapping[str, Any]) -> str:
    """Render Markdown using the evidence renderer and separately labelled prose."""
    if not isinstance(report, Mapping) or report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("public-report-v1 版本不受支持")
    recorded_report_sha = report.get("report_sha256")
    unsigned = dict(report)
    unsigned.pop("report_sha256", None)
    if not isinstance(recorded_report_sha, str) or _sha(unsigned) != recorded_report_sha:
        raise ValueError("报告摘要与内容不一致")
    evidence = report.get("evidence")
    request = report.get("request")
    if not isinstance(evidence, Mapping) or not isinstance(request, Mapping):
        raise ValueError("报告缺少证据或请求")
    validate_temporal_evidence(evidence, request)
    if evidence.get("request_digest") != report.get("request_digest"):
        raise ValueError("报告与证据请求摘要不一致")
    policy = report.get("policy_context") or {}
    if policy:
        validate_policy_facts(policy)
        if (policy.get("policy_id") != request.get("policy_id")
                or policy.get("data_version") != report.get("data_version")
                or policy.get("policy_view") != request.get("policy_view")):
            raise ValueError("报告政策事实绑定不一致")
    lines = ["# 国际贸易政策与数据观察简报", ""]
    if policy:
        lines.extend(["## 政策背景", "",
                      "以下是该公告登记的附加税安排，并非商品当前适用的全部税费。", "",
                      f"- 生效时间：{policy.get('effective_date')} {policy.get('clock_24h')}（{policy.get('timezone')}）",
                      f"- 适用原产地：{policy.get('origin')}",
                      f"- 涉及环节：{'、'.join(policy.get('entry_events') or [])}", "",
                      "| HTS税号 | 公告登记商品 | 附加税率 |"])
        lines.append("|---|---|---:|")
        policy_rows = list(policy.get("product_rates") or [])
        all_statuses_unknown = bool(policy_rows) and all(
            _reader_status((row.get("details") or {}).get("conditions", {}).get("status")) == "尚未核实"
            and _reader_status((row.get("details") or {}).get("exceptions", {}).get("status")) == "尚未核实"
            for row in policy_rows
        )
        for row in policy.get("product_rates") or []:
            details = row.get("details") if isinstance(row.get("details"), Mapping) else {}
            name = details.get("registered_name_zh") or details.get("registered_name") or "登记商品"
            conditions = details.get("conditions") if isinstance(details.get("conditions"), Mapping) else {}
            exceptions = details.get("exceptions") if isinstance(details.get("exceptions"), Mapping) else {}
            extra = ""
            if not all_statuses_unknown:
                extra = (f"；条件：{_reader_status(conditions.get('status'))}"
                         f"；例外：{_reader_status(exceptions.get('status'))}")
            lines.append(f"| `{row.get('hts8')}` | {name} | {row.get('additional_duty_percent')}%{extra} |")
        if all_statuses_unknown:
            lines.extend(["", "公告中的具体适用条件和排除情形尚未逐项核实；未知不代表不存在。"])
        limitations = [str(item).rstrip("。；; ") for item in policy.get("limitations") or []]
        if limitations:
            lines.append("阅读提醒：" + "；".join(limitations) + "。")
        source_rows = list(policy.get("sources") or [])
        source_map = {str(source.get("id")): source for source in source_rows
                      if isinstance(source, Mapping) and isinstance(source.get("id"), str)}
        policy_urls = set()
        rendered_policy_sources = []
        for source in source_rows:
            if not isinstance(source, Mapping):
                continue
            url = source.get("url")
            if isinstance(url, str) and url.startswith("https://") and url not in policy_urls:
                policy_urls.add(url)
                rendered_policy_sources.append(f"[查看政策原文]({url})")
        if rendered_policy_sources:
            lines.append("政策原文：" + "、".join(rendered_policy_sources))
        lines.extend(["", "---", ""])
    policy_explanations = report.get("policy_explanations") or []
    if policy_explanations:
        lines.extend(["## 政策说明", ""])
        labels = {"change": "政策改了什么", "applicability": "适用范围", "limits": "局限与未知"}
        for item in policy_explanations:
            refs = "、".join(_policy_source_link(source_id, source_map)
                             for source_id in item["source_ids"])
            lines.append(f"- **{labels.get(item['topic'], item['topic'])}**（来源：{refs}）：{item['text']}")
        lines.extend(["", "---", ""])
    lines.extend([render_temporal_evidence(evidence, request).rstrip(),
                  "", "## 数据解读", ""])
    explanations = report.get("explanations") or []
    if explanations:
        for item in explanations:
            label = "可能的解释" if item["kind"] == "hypothesis" else "含义"
            observation = _observation_label(evidence, item["observation_id"])
            lines.append(f"- **{label}**（{observation}）：{item['text']}")
    else:
        lines.append("目前列出的是程序计算的贸易事实，尚无经过核对的数据解读。")
    lines.extend(["", "## 后续关注", ""])
    watchlist = report.get("watchlist") or []
    if watchlist:
        lines.extend(f"- {item['rationale']}" for item in watchlist)
    else:
        lines.append("当前没有已登记的后续观察事项。")
    return "\n".join(lines) + "\n"


def render_public_html(report: Mapping[str, Any]) -> str:
    """A small escaped HTML adapter for the later frontend, not a full page."""
    markdown = render_public_report(report)
    escaped = html.escape(markdown)
    return "<article data-report-schema=\"public-report-v1\"><pre>" + escaped + "</pre></article>"


__all__ = ["SCHEMA_VERSION", "build_public_report", "render_public_report",
           "render_public_html"]
