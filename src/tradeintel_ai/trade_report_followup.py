"""Offline, report-bound facts and a strict contract for one trade-report follow-up.

This module does not select products, query a provider, or approve model prose.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .response_contract import canonical_response
from .trade_explanation import report_sha256


PROTOCOL = "trade-report-followup-v1"
MAX_INPUT_BYTES = 24_000
MAX_RAW_BYTES = 8_000
NEEDED_DATA = {"quantity", "unit_value", "product_composition", "comparable_trade_balance", "other"}
_MONTH = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])\Z")
_NEW_NUMBER = re.compile(r"[0-9０-９]|[%％]|https?://|<[^>]*>|百分之", re.I)


def _bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def question_sha256(question: str) -> str:
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 300:
        raise ValueError("追问不能为空或过长")
    return hashlib.sha256(question.strip().encode("utf-8")).hexdigest()


def catalog_sha256(catalog: Mapping[str, Any]) -> str:
    return _sha(catalog)


def _month_index(month: str) -> int:
    year, number = map(int, month.split("-"))
    return year * 12 + number - 1


def _part(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if report.get("kind") == "trade-query-v1":
        return [report]
    if report.get("kind") == "trade-query-both-v1":
        parts = [report.get("import_report"), report.get("export_report")]
        if (any(not isinstance(p, Mapping) or p.get("kind") != "trade-query-v1" for p in parts)
                or [p.get("scope", {}).get("flow") for p in parts] != ["import", "export"]):
            raise ValueError("双方向报告结构无效")
        return parts
    raise ValueError("报告类型无效")


def _facts_for_question(catalog: Mapping[str, Any], question: str) -> list[dict[str, Any]]:
    """Keep the prompt bounded without removing facts from the signed catalog.

    Peak-gap facts are generated for every observed month so they remain
    auditable.  The model only needs the explicitly requested month; when a
    question has no machine-readable month, use the latest peak-gap fact for
    each flow as the conservative default.  All other fact types are retained.
    """
    facts = list(catalog["facts"])
    peak = [fact for fact in facts if ".year_peak_gap." in fact["id"]]
    if not peak:
        return facts
    requested = set(re.findall(r"\d{4}-(?:0[1-9]|1[0-2])", question))
    if requested:
        selected = [fact for fact in peak if any(fact["id"].endswith(month) for month in requested)]
    else:
        selected = []
        latest_by_flow: dict[str, dict[str, Any]] = {}
        for fact in peak:
            flow = fact["id"].split(".", 1)[0]
            latest_by_flow[flow] = fact
        selected = list(latest_by_flow.values())
    selected_ids = {fact["id"] for fact in selected}
    return [fact for fact in facts if ".year_peak_gap." not in fact["id"] or fact["id"] in selected_ids]


def _rows(part: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = part.get("series")
    scope = part.get("scope")
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 24 or
            not isinstance(scope, Mapping) or scope.get("flow") not in {"import", "export"} or
            not isinstance(scope.get("product_code"), str) or not scope["product_code"] or
            not isinstance(scope.get("metric"), str) or not scope["metric"]):
        raise ValueError("报告逐月结构或范围无效")
    previous: str | None = None
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("month"), str) or not _MONTH.fullmatch(row["month"]):
            raise ValueError("报告月份无效")
        if previous is not None and _month_index(row["month"]) != _month_index(previous) + 1:
            raise ValueError("报告月份顺序或连续性无效")
        if row.get("status") == "observed":
            if (type(row.get("value_usd")) is not int or row["value_usd"] < 0 or
                    not isinstance(row.get("source_url"), str) or
                    not row["source_url"].startswith("https://")):
                raise ValueError("已观察金额或来源无效")
        elif row.get("value_usd") is not None:
            raise ValueError("未观察金额不得填零或其他数值")
        previous = row["month"]
    if scope.get("start_month") != rows[0]["month"] or scope.get("end_month") != rows[-1]["month"]:
        raise ValueError("报告月份与确认范围不一致")
    return rows


def build_catalog(report: Mapping[str, Any]) -> dict[str, Any]:
    """Derive exact facts only from observed months of one saved report."""
    digest = report_sha256(report)
    facts: list[dict[str, Any]] = []
    scopes: list[dict[str, str]] = []

    def add(flow: str, suffix: str, fact: str, months: list[str], sources: list[str]) -> None:
        facts.append({"id": f"{flow}.{suffix}", "fact": fact, "months": months,
                      "sources": list(dict.fromkeys(sources))})

    parts = _part(report)
    for part in parts:
        scope, rows = part["scope"], _rows(part)
        flow = scope["flow"]
        direction = "进口" if flow == "import" else "出口"
        metric_name = "进口消费金额" if flow == "import" else "出口FAS金额"
        metric = "import_value_consumption_usd" if flow == "import" else "total_export_fas_usd"
        # Report generators may evolve the metric label. Do not silently turn
        # an unknown basis into the known import/export basis.
        if scope["metric"] != metric:
            raise ValueError("报告统计口径未获当前追问协议支持")
        scopes.append({"flow": flow, "product_code": scope["product_code"],
                       "product_label": str(scope.get("product_label") or ""),
                       "metric": scope["metric"], "partner": str(scope.get("partner") or ""),
                       "start_month": rows[0]["month"], "end_month": rows[-1]["month"]})
        add(flow, "basis", f"{direction}逐月数据的口径是{metric_name}，金额不能单独说明数量或单价。", [], [])
        for row in rows:
            if row["status"] != "observed":
                continue
            add(flow, f"month.{row['month']}",
                f"{row['month']}的{direction}金额为{row['value_usd']:,}美元。",
                [row["month"]], [row["source_url"]])
        changes: dict[str, tuple[int, list[str]]] = {}
        for prior, current in zip(rows, rows[1:]):
            if (prior["status"] != "observed" or current["status"] != "observed" or
                    prior["month"][:4] != current["month"][:4]):
                continue  # No unverified cross-year commodity-classification comparison.
            delta = current["value_usd"] - prior["value_usd"]
            verb = "增加" if delta > 0 else "减少" if delta < 0 else "持平"
            sources = [prior["source_url"], current["source_url"]]
            add(flow, f"change.{current['month']}",
                f"{prior['month']}至{current['month']}的{direction}金额{verb}{abs(delta):,}美元。",
                [prior["month"], current["month"]], sources)
            changes[current["month"]] = (delta, sources)
        for month, (delta, sources) in changes.items():
            year_changes = {m: item for m, item in changes.items() if m[:4] == month[:4]}
            rank = 1 + sum(abs(value) > abs(delta) for value, _ in year_changes.values())
            leaders = [m for m, (value, _) in year_changes.items() if abs(value) ==
                       max(abs(item[0]) for item in year_changes.values())]
            add(flow, f"rank.{month}",
                f"{month[:4]}年已观察的{len(year_changes)}次同年相邻月{direction}金额变化中，"
                f"截至{month}的这次变化按绝对金额排第{rank}；最大变化截至{'、'.join(leaders)}。",
                [month], sources)
        # Publish a report-bound fact for every observed month.  This lets a
        # follow-up ask about any month without asking the model to calculate
        # a difference; missing months are not treated as zero.
        by_year: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            if row["status"] == "observed":
                by_year.setdefault(row["month"][:4], []).append(row)
        for year, year_rows in by_year.items():
            if len(year_rows) < 2:
                continue
            high = max(row["value_usd"] for row in year_rows)
            peak_rows = [row for row in year_rows if row["value_usd"] == high]
            peak_months = [row["month"] for row in peak_rows]
            for row in year_rows:
                gap = high - row["value_usd"]
                comparison = "与该峰值相同" if gap == 0 else f"低于该峰值{gap:,}美元"
                add(flow, f"year_peak_gap.{row['month']}",
                    f"{year}年已观察月份中，最高为{'、'.join(peak_months)}的{high:,}美元；"
                    f"{row['month']}为{row['value_usd']:,}美元，{comparison}。",
                    [row["month"], *peak_months],
                    [row["source_url"], *(item["source_url"] for item in peak_rows)])
    if len(parts) == 2:
        left, right = scopes
        if (left["product_code"] != right["product_code"] or
                left["start_month"] != right["start_month"] or
                left["end_month"] != right["end_month"]):
            raise ValueError("进出口报告范围不一致")
        add("both", "balance_limit", "进口消费金额与出口FAS金额是不同统计口径；不能把两者直接相减，"
            "也不能仅凭两方向同升判断贸易差额改善。", [], [])
    result = {"schema_version": PROTOCOL, "report_sha256": digest,
              "scopes": scopes, "facts": facts}
    if len({fact["id"] for fact in facts}) != len(facts):
        raise ValueError("事实ID重复")
    return result


def _check_catalog(report: Mapping[str, Any], catalog: Mapping[str, Any], digest: str) -> None:
    if not isinstance(catalog, Mapping) or catalog_sha256(catalog) != digest or catalog != build_catalog(report):
        raise ValueError("事实目录与原报告不匹配")


def messages(report: Mapping[str, Any], question: str, catalog: Mapping[str, Any],
             digest: str) -> list[dict[str, str]]:
    _check_catalog(report, catalog, digest)
    qdigest = question_sha256(question)
    payload = {"schema_version": PROTOCOL, "report_sha256": catalog["report_sha256"],
               "followup_question_sha256": qdigest, "catalog_sha256": digest,
               "original_question": report.get("question"), "followup_question": question.strip(),
               "scopes": catalog["scopes"], "facts": _facts_for_question(catalog, question)}
    instruction = ("你只回答读者对已确认贸易数据报告的这一个追问。只使用给定事实，不搜索或猜测。"
                   "请选择能回答问题的事实ID，最多两点；不要把金额当成数量、单价或贸易差额，"
                   "不要推断原因、政策效果、预测或投资建议。数据不足时直接说明当前不能判断。"
                   "只输出严格JSON，字段恰好为schema_version、report_sha256、followup_question_sha256、"
                   "catalog_sha256、mode、points、needed_data。mode为observed或cannot_infer；"
                   "points是text和fact_ids构成的列表；needed_data只可选quantity、unit_value、"
                   "product_composition、comparable_trade_balance、other。"
                   "解释文字不写任何数字、日期、税号、网址，具体数值和来源由页面按事实ID显示。")
    result = [{"role": "system", "content": instruction},
              {"role": "user", "content": _bytes(payload).decode("utf-8")}]
    if len(_bytes(result)) > MAX_INPUT_BYTES:
        raise ValueError("追问模型输入超过预算")
    return result


def parse(raw: str, report: Mapping[str, Any], question: str,
          catalog: Mapping[str, Any], digest: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_RAW_BYTES:
        raise ValueError("追问原答过大或无效")
    _check_catalog(report, catalog, digest)
    envelope = canonical_response(raw, stage=PROTOCOL)
    answer = envelope["parsed"]
    expected = {"schema_version", "report_sha256", "followup_question_sha256",
                "catalog_sha256", "mode", "points", "needed_data"}
    if not isinstance(answer, dict) or set(answer) != expected:
        raise ValueError("追问回答字段无效")
    if (answer["schema_version"] != PROTOCOL or
            answer["report_sha256"] != catalog["report_sha256"] or
            answer["followup_question_sha256"] != question_sha256(question) or
            answer["catalog_sha256"] != digest):
        raise ValueError("追问回答与报告、问题或事实目录不匹配")
    if answer["mode"] not in {"observed", "cannot_infer"}:
        raise ValueError("追问回答模式无效")
    needed = answer["needed_data"]
    if (not isinstance(needed, list) or len(needed) > 4 or
            any(not isinstance(item, str) or item not in NEEDED_DATA for item in needed) or
            len(set(needed)) != len(needed) or
            (answer["mode"] == "observed" and needed) or
            (answer["mode"] == "cannot_infer" and not needed)):
        raise ValueError("缺失资料清单无效")
    points = answer["points"]
    if not isinstance(points, list) or not 1 <= len(points) <= 2:
        raise ValueError("追问回答条数无效")
    valid_ids = {fact["id"] for fact in catalog["facts"]}
    seen: set[str] = set()
    total_length = 0
    for point in points:
        if not isinstance(point, dict) or set(point) != {"text", "fact_ids"}:
            raise ValueError("追问回答条目字段无效")
        value, ids = point["text"], point["fact_ids"]
        if not isinstance(value, str) or not value.strip() or _NEW_NUMBER.search(value):
            raise ValueError("解释文字为空或含未经核对的数字、日期、网址")
        total_length += len(value)
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 3 or
                any(not isinstance(item, str) or item not in valid_ids or item in seen for item in ids)):
            raise ValueError("解释引用了未知、重复或过多事实ID")
        seen.update(ids)
    if total_length > 400:
        raise ValueError("解释文字超长")
    # Syntactic validity is deliberately not semantic approval.
    return {"status": "needs_review", "raw_sha256": envelope["raw_sha256"],
            "answer": answer}
