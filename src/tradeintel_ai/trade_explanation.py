"""Evidence-bound, provider-neutral explanations for saved trade reports.

The deterministic report owns every figure and source. The model receives only
the facts selected for the user's question and may add a short explanation
without recalculating the underlying trade data.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .response_contract import canonical_response


PROTOCOL = "trade-data-explanation-v3"
MAX_INPUT_BYTES = 60_000
MAX_RAW_BYTES = 20_000
_NUMBER = re.compile(r"\d|[%％]|https?://|<[^>]*>|百分之")
_CHANGE_QUESTIONS = ("变化", "走势", "趋势", "增长", "增加", "减少", "下降", "环比",
                     "比上月", "较上月", "涨", "跌")
_PERIOD_QUESTIONS = ("累计", "合计", "总额", "总计", "共计", "一共", "总共", "全年", "全期")
_LATEST_QUESTIONS = ("最新", "最近一个月", "最近月份", "最新月", "最新月份", "最后一个月")
_CAUSE_QUESTIONS = ("为什么", "原因", "造成", "导致", "影响")


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def report_sha256(report: Mapping[str, Any]) -> str:
    """Hash the immutable program report, never a browser-supplied decoration."""
    if not isinstance(report, Mapping) or report.get("kind") not in {
        "trade-query-v1", "trade-query-both-v1", "announcement-statistics-report-v1",
        "announcement-context-report-v1"
    }:
        raise ValueError("通用贸易报告类型无效")
    return hashlib.sha256(_json_bytes(report)).hexdigest()


def _month_index(month: object) -> int | None:
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        return None
    year, number = map(int, month.split("-"))
    if not 1 <= number <= 12:
        return None
    return year * 12 + number - 1


def _is_observed(row: object) -> bool:
    return (isinstance(row, Mapping) and row.get("status") == "observed"
            and type(row.get("value_usd")) is int and row["value_usd"] >= 0
            and _month_index(row.get("month")) is not None)


def _month_words(month: str) -> str:
    year, number = month.split("-")
    return f"{year}年{int(number)}月"


def _scope_label(scope: Mapping[str, Any]) -> str:
    direction = scope.get("flow")
    partner = scope.get("partner")
    if direction == "import":
        origin = "中国" if partner == "CHINA" else "全部来源"
        return f"美国从{origin}进口{scope.get('product_label')}的消费金额"
    destination = "中国" if partner == "CHINA" else "全部目的地"
    return f"美国向{destination}出口{scope.get('product_label')}的FAS金额"


def _extreme_months(rows: list[Mapping[str, Any]], value: int) -> str:
    return "、".join(str(row["month"]) for row in rows
                    if _is_observed(row) and row["value_usd"] == value)


def _trend_observation(part: Mapping[str, Any]) -> dict[str, Any] | None:
    """Summarize the observed range and the latest contiguous run of changes."""
    scope, summary, series = part.get("scope"), part.get("summary"), part.get("series")
    if not isinstance(scope, Mapping) or not isinstance(summary, Mapping) or not isinstance(series, list):
        raise ValueError("贸易报告事实结构无效")
    observed = [row for row in series if _is_observed(row)]
    if not observed:
        return None

    complete = (len(series) > 1 and summary.get("complete_window") is True and len(observed) == len(series)
                and all(_month_index(series[index + 1].get("month")) ==
                        _month_index(series[index].get("month")) + 1
                        for index in range(len(series) - 1)))
    range_label = "完整区间" if complete else "已观察月份"
    high, low = max(row["value_usd"] for row in observed), min(row["value_usd"] for row in observed)
    high_months, low_months = _extreme_months(observed, high), _extreme_months(observed, low)
    scope_name = _scope_label(scope)
    start = scope.get("start_month")
    end = scope.get("end_month")
    bounds = f"{start}至{end}" if isinstance(start, str) and isinstance(end, str) else "所选期间"

    latest = series[-1] if series else None
    latest_month = latest.get("month") if isinstance(latest, Mapping) else None
    latest_index = _month_index(latest_month)
    latest_observed = _is_observed(latest)
    direction = "资料不足"
    consecutive = 0
    trend_text = ""
    if latest_observed and len(series) >= 2 and _is_observed(series[-2]):
        previous = series[-2]
        if latest_index is not None and _month_index(previous.get("month")) == latest_index - 1:
            delta = latest["value_usd"] - previous["value_usd"]
            direction = "增加" if delta > 0 else "减少" if delta < 0 else "持平"
            sign = (delta > 0) - (delta < 0)
            consecutive = 1
            cursor = len(series) - 1
            while cursor >= 1:
                current_row, prior_row = series[cursor], series[cursor - 1]
                if not (_is_observed(current_row) and _is_observed(prior_row)):
                    break
                current_index = _month_index(current_row.get("month"))
                prior_index = _month_index(prior_row.get("month"))
                if current_index is None or prior_index != current_index - 1:
                    break
                pair_delta = current_row["value_usd"] - prior_row["value_usd"]
                pair_sign = (pair_delta > 0) - (pair_delta < 0)
                if pair_sign != sign:
                    break
                if cursor != len(series) - 1:
                    consecutive += 1
                cursor -= 1
            if consecutive >= 2:
                trend_text = (f"截至{_month_words(str(latest_month))}已连续{consecutive}个月逐月{direction}，"
                              f"最新月较上月{direction}{abs(delta):,}美元。")
            else:
                trend_text = (f"{_month_words(str(latest_month))}较"
                              f"{_month_words(str(previous['month']))}{direction}{abs(delta):,}美元。")
    if not trend_text:
        if latest_observed and isinstance(latest_month, str):
            trend_text = f"{_month_words(latest_month)}没有相邻的已观察月份可比较，无法判断最近走势。"
        elif isinstance(latest_month, str):
            trend_text = f"最新月份{_month_words(latest_month)}没有可用金额，无法判断最近走势。"
        else:
            trend_text = "最新月份没有可用金额，无法判断最近走势。"

    high_label = "、".join(_month_words(month) for month in high_months.split("、") if month)
    low_label = "、".join(_month_words(month) for month in low_months.split("、") if month)
    high_prefix = "并列最高为" if len(high_months.split("、")) > 1 else "最高为"
    low_prefix = "并列最低为" if len(low_months.split("、")) > 1 else "最低为"
    fact = (f"{scope_name}在{bounds}的{range_label}中，{trend_text}"
            f"{high_prefix}{high_label}（{high:,}美元），{low_prefix}{low_label}（{low:,}美元）。")
    return {"id": f"{scope.get('flow')}.trend", "fact": fact,
            "direction": direction, "consecutive_changes": consecutive}


def observation_catalog(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    if report.get("kind") == "trade-query-both-v1":
        parts = (report.get("import_report"), report.get("export_report"))
    else:
        parts = (report,)
    catalog: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, Mapping) or part.get("kind") != "trade-query-v1":
            raise ValueError("贸易报告缺少方向数据")
        scope, summary, rows = part.get("scope"), part.get("summary"), part.get("series")
        if not isinstance(scope, Mapping) or not isinstance(summary, Mapping) or not isinstance(rows, list):
            raise ValueError("贸易报告事实结构无效")
        direction = scope.get("flow")
        if direction not in {"import", "export"}:
            raise ValueError("贸易报告方向无效")
        label = "进口消费额" if direction == "import" else "出口总额（FAS）"
        prefix = str(direction)
        latest = summary.get("latest_value_usd")
        if type(latest) is int and latest >= 0:
            catalog.append({"id": f"{prefix}.latest", "fact":
                            f"{summary.get('latest_month')} 的{label}为 {latest:,} 美元。"})
        change = summary.get("month_change_usd")
        if type(change) is int:
            trend = "增加" if change > 0 else "减少" if change < 0 else "持平"
            fact = (f"{summary.get('latest_month')} 的{label}较 {summary.get('previous_month')} "
                    f"{trend}了 {abs(change):,} 美元。" if change else
                    f"{summary.get('latest_month')} 的{label}与 {summary.get('previous_month')} 持平，差额为 0 美元。")
            catalog.append({"id": f"{prefix}.month_change", "fact": fact,
                            "trend": trend})
        total = summary.get("period_total_usd")
        if type(total) is int and total >= 0 and len(rows) > 1:
            catalog.append({"id": f"{prefix}.period_total", "fact":
                            f"{scope.get('start_month')} 至 {scope.get('end_month')} 的{label}合计 {total:,} 美元。"})
        trend_fact = _trend_observation(part)
        if trend_fact:
            catalog.append(trend_fact)
    if not catalog:
        raise ValueError("本报告没有可解释的已观察金额")
    return catalog


def _selected_observations(report: Mapping[str, Any], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    question = str(report.get("question", ""))
    wants_change = any(term in question for term in _CHANGE_QUESTIONS)
    wants_period = any(term in question for term in _PERIOD_QUESTIONS)
    wants_latest = any(term in question for term in _LATEST_QUESTIONS)
    wants_cause = any(term in question for term in _CAUSE_QUESTIONS)

    suffixes = tuple(suffix for suffix, enabled in (
        ("latest", wants_latest), ("trend", wants_change or wants_cause),
        ("period_total", wants_period)) if enabled)
    if not suffixes:
        # A broad question such as “大豆进口怎么样” gets a compact overview.
        suffixes = ("latest", "trend")

    selected = [item for item in catalog
                if any(item["id"].endswith(f".{suffix}") for suffix in suffixes)]
    found = {item["id"].rsplit(".", 1)[-1] for item in selected}
    missing = [suffix for suffix in suffixes if suffix not in found]
    if missing:
        labels = {"latest": "最新月金额", "trend": "可比较的走势", "period_total": "完整期间合计"}
        raise ValueError(f"当前数据没有{labels.get(missing[0], '所需事实')}，无法生成模型解释")
    return selected


def _parts(report: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    if report.get("kind") == "trade-query-both-v1":
        return report["import_report"], report["export_report"]
    return (report,)


def _group_ids(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for item in items:
        direction = item["id"].split(".", 1)[0]
        grouped.setdefault(direction, []).append(item["id"])
    return grouped


def _example_text(ids: list[str], selected: list[dict[str, Any]]) -> str:
    trend = next((item for item in selected if item["id"] in ids and item["id"].endswith(".trend")), None)
    if trend and trend.get("direction") == "资料不足":
        return "近期走势资料不足，无法判断方向，还需要等待连续月份数据。"
    if trend:
        return (f"近来的金额走势呈{trend['direction']}，仍需结合数量、价格或目的地资料理解，"
                "不能据此判断具体原因。")
    if any(item["id"] in ids and item["id"].endswith(".period_total") for item in selected):
        return "所选期间合计说明金额规模，实际贸易数量和变化原因仍需结合其他资料判断。"
    return "最新月金额反映当前贸易规模，仍需结合数量和价格资料理解。"


def messages(report: Mapping[str, Any], digest: str) -> list[dict[str, str]]:
    if report_sha256(report) != digest:
        raise ValueError("贸易报告摘要不匹配")
    catalog = observation_catalog(report)
    selected = _selected_observations(report, catalog)
    grouped = _group_ids(selected)
    evidence = []
    for part in _parts(report):
        scope = part["scope"]
        direction = scope["flow"]
        if direction not in grouped:
            continue
        evidence.append({
            "direction": direction, "product": scope["product_label"],
            "product_code": scope["product_code"], "partner": scope["partner"],
            "metric": scope["metric"], "start_month": scope["start_month"],
            "end_month": scope["end_month"], "dataset_version": scope["dataset_version"],
            "sources": part.get("sources", []),
        })
    system = (
        "你解释的是已核验的美国商品贸易金额报告，不是政策效果研究。只输出严格JSON对象，"
        "字段为schema_version、report_sha256、interpretations。每个方向恰好一条解释；"
        "每条字段恰为observation_ids、text，observation_ids必须原样包含该方向全部required_observation_ids，"
        "不得引用未提供的观察。两方向报告分开说明进口和出口，不要相减或称贸易顺差。"
        "用自然中文写一段20至160字的解释，补充用户理解这些事实所需的信息，不复述整张表，也不重复堆叠限制。"
        "走势观察要明确保留其中的增加、减少、持平或资料不足判断。金额不是数量；仅凭金额不能判定价格、数量或政策作用；"
        "用户问原因时，一次说明现有金额数据不足以判定原因，不要猜测。不要添加数字、日期、税率、编码、百分比、网址，"
        "不要给出投资建议或确定性预测。"
    )
    groups = [{"direction": direction, "required_observation_ids": ids}
              for direction, ids in grouped.items()]
    example = [{"observation_ids": ids, "text": _example_text(ids, selected)}
               for ids in grouped.values()]
    payload = {"schema_version": PROTOCOL, "report_sha256": digest,
               "question": report["question"],
               "observations": selected,
               "required_observation_ids": [item["id"] for item in selected],
               "required_by_direction": groups,
               "evidence": evidence,
               "format_example": {"schema_version": PROTOCOL, "report_sha256": digest,
                                  "interpretations": example}}
    result = [{"role": "system", "content": system},
              {"role": "user", "content": json.dumps(payload, ensure_ascii=False,
                                                       separators=(",", ":"))}]
    if len(_json_bytes(result)) > MAX_INPUT_BYTES:
        raise ValueError("模型输入超过通用报告预算，请缩小查询范围")
    return result


def parse(raw: str, report: Mapping[str, Any], digest: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_RAW_BYTES:
        raise ValueError("模型原答过大或类型无效")
    if report_sha256(report) != digest:
        raise ValueError("贸易报告摘要不匹配")
    envelope = canonical_response(raw, stage=PROTOCOL)
    answer = envelope["parsed"]
    if not isinstance(answer, dict) or set(answer) != {
        "schema_version", "report_sha256", "interpretations"
    }:
        raise ValueError("模型解释字段无效")
    if answer["schema_version"] != PROTOCOL or answer["report_sha256"] != digest:
        raise ValueError("模型解释与本次报告不匹配")
    items = answer["interpretations"]
    if not isinstance(items, list) or not 1 <= len(items) <= 2:
        raise ValueError("模型解释必须按贸易方向各有一条")
    selected = _selected_observations(report, observation_catalog(report))
    expected = _group_ids(selected)
    allowed = {item["id"] for item in selected}
    directions: set[str] = set()
    used: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    by_id = {item["id"]: item for item in selected}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"observation_ids", "text"}:
            raise ValueError("模型解释条目字段无效")
        keys, value = item["observation_ids"], item["text"]
        if (not isinstance(keys, list) or not keys or
                any(not isinstance(key, str) for key in keys) or
                len(set(keys)) != len(keys) or
                any(key not in allowed or key in used for key in keys)):
            raise ValueError("模型解释引用了不存在或重复的观察")
        direction_set = {key.split(".", 1)[0] for key in keys}
        if len(direction_set) != 1:
            raise ValueError("同一条解释不能混合进口和出口")
        direction = next(iter(direction_set))
        if direction in directions or set(keys) != set(expected.get(direction, [])):
            raise ValueError("模型解释必须完整覆盖该方向的指定观察")
        if not isinstance(value, str) or not 20 <= len(value.strip()) <= 160 or _NUMBER.search(value):
            raise ValueError("模型解释文字包含新数字、网址或长度无效")
        for key in keys:
            fact = by_id[key]
            if key.endswith(".trend"):
                expected_direction = fact.get("direction")
                if expected_direction == "资料不足":
                    if not any(term in value for term in ("资料不足", "无法判断", "无法比较")):
                        raise ValueError("走势资料不足时，解释必须明确说明无法判断")
                elif expected_direction not in value:
                    raise ValueError("走势解释没有说明程序计算的方向")
        directions.add(direction)
        used.update(keys)
        cleaned.append({"observation_ids": list(keys), "text": value.strip()})
    if directions != set(expected) or used != allowed:
        raise ValueError("模型解释没有覆盖所有指定观察")
    return {"schema_version": PROTOCOL, "report_sha256": digest,
            "raw_sha256": envelope["raw_sha256"], "interpretations": cleaned,
            "status": "needs_review"}


__all__ = ["PROTOCOL", "MAX_INPUT_BYTES", "MAX_RAW_BYTES", "report_sha256",
           "observation_catalog", "messages", "parse"]
