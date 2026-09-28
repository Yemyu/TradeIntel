"""Deterministic, report-bound relation cards for optional trade explanations."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .response_contract import canonical_response
from .trade_explanation import report_sha256


PROTOCOL = "trade-data-explanation-v4"
CALCULATOR = "trade-relations-v1"
MAX_INPUT_BYTES = 60_000
MAX_RAW_BYTES = 20_000
_NUMBER = re.compile(r"\d|[%％]|https?://|<[^>]*>|百分之")
_CAUSE = ("为什么", "原因", "政策", "关税", "导致", "造成")


def _encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
    return hashlib.sha256(_encoded(snapshot)).hexdigest()


def _month(month: object) -> int | None:
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        return None
    year, number = map(int, month.split("-"))
    return year * 12 + number - 1


def _observed(row: object) -> bool:
    return (isinstance(row, Mapping) and row.get("status") == "observed" and
            type(row.get("value_usd")) is int and row["value_usd"] >= 0 and
            _month(row.get("month")) is not None)


def _pair(rows: list, index: int) -> bool:
    return (index > 0 and _observed(rows[index]) and _observed(rows[index - 1]) and
            _month(rows[index]["month"]) == _month(rows[index - 1]["month"]) + 1 and
            # A single catalog version does not prove year-to-year definition
            # equivalence for this particular product. Wait for an audit.
            rows[index]["month"][:4] == rows[index - 1]["month"][:4])


def _direction(delta: int) -> str:
    return "增加" if delta > 0 else "减少" if delta < 0 else "持平"


def _card(part: Mapping[str, Any], suffix: str, fact: str, months: list[str],
          *, eligible: bool, **extra: Any) -> dict[str, Any]:
    scope = part["scope"]
    return {"id": f"{scope['flow']}.{suffix}", "fact": fact,
            "flow": scope["flow"], "product_code": scope["product_code"],
            "partner": scope["partner"], "metric": scope["metric"],
            "months": months, "eligible_for_ai": eligible, **extra}


def _one_direction(part: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    scope, rows = part.get("scope"), part.get("series")
    if (not isinstance(scope, Mapping) or scope.get("flow") not in {"import", "export"}
            or not isinstance(rows, list) or not rows):
        raise ValueError("关系卡缺少有效的贸易方向或逐月数据")
    cards: list[dict[str, Any]] = []
    flow = "进口" if scope["flow"] == "import" else "出口"
    latest_sign: str | None = None
    if _pair(rows, len(rows) - 1):
        prior, latest = rows[-2:]
        delta = latest["value_usd"] - prior["value_usd"]
        latest_sign = _direction(delta)
        cards.append(_card(part, "latest_change",
                           f"{flow}金额在{latest['month']}较{prior['month']}{latest_sign}{abs(delta):,}美元；这只比较相邻两个月。",
                           [prior["month"], latest["month"]], eligible=False,
                           direction=latest_sign, delta_usd=delta))
        if _pair(rows, len(rows) - 2):
            previous_delta = rows[-2]["value_usd"] - rows[-3]["value_usd"]
            previous_sign = _direction(previous_delta)
            if delta != 0 and previous_delta != 0 and (delta > 0) != (previous_delta > 0):
                # A year boundary can change commodity classification. Do not
                # infer a turn across that boundary without a separate audit.
                if len({row["month"][:4] for row in rows[-3:]}) == 1:
                    cards.append(_card(part, "recent_turn",
                                       f"{flow}金额先在{rows[-2]['month']}较上月{previous_sign}，"
                                       f"再在{latest['month']}较上月{latest_sign}；仅表示最近三个月的转向。",
                                       [row["month"] for row in rows[-3:]], eligible=True,
                                       direction=latest_sign, previous_direction=previous_sign))
            if delta != 0 and previous_delta != 0 and (delta > 0) == (previous_delta > 0):
                # Count changes, not months. Missing or unobserved rows stop the run.
                changes = 2
                cursor = len(rows) - 3
                while _pair(rows, cursor):
                    earlier = rows[cursor]["value_usd"] - rows[cursor - 1]["value_usd"]
                    if earlier == 0 or (earlier > 0) != (delta > 0):
                        break
                    changes += 1
                    cursor -= 1
                cards.append(_card(part, "recent_run",
                                   f"截至{latest['month']}，{flow}金额连续{changes}次逐月{latest_sign}；"
                                   "这不是整个查询区间的走势结论。",
                                   [row["month"] for row in rows[-changes - 1:]],
                                   eligible=True, direction=latest_sign,
                                   consecutive_changes=changes))
    observed = [row for row in rows if _observed(row)]
    if observed:
        high = max(row["value_usd"] for row in observed)
        low = min(row["value_usd"] for row in observed)
        highs = [row["month"] for row in observed if row["value_usd"] == high]
        lows = [row["month"] for row in observed if row["value_usd"] == low]
        cards.append(_card(part, "observed_extremes",
                           f"{flow}金额在已观察月份中最高为{high:,}美元（{'、'.join(highs)}），"
                           f"最低为{low:,}美元（{'、'.join(lows)}）；未观察月份不参加比较。",
                           [row["month"] for row in observed], eligible=False))
        cards[-1].update(high_usd=high, high_months=highs, low_usd=low, low_months=lows)
        # This is a deterministic page fact, not a model relation.  Keeping
        # it out of eligible_card_ids prevents a generic explanation call
        # from introducing an unrelated year comparison, while the follow-up
        # catalog exposes the same calculation for every observed month.
        latest_observed = observed[-1]
        latest_year_rows = [row for row in observed
                            if row["month"][:4] == latest_observed["month"][:4]]
        if len(latest_year_rows) >= 2:
            year_high = max(row["value_usd"] for row in latest_year_rows)
            year_peaks = [row for row in latest_year_rows if row["value_usd"] == year_high]
            year_peak_months = [row["month"] for row in year_peaks]
            year_gap = year_high - latest_observed["value_usd"]
            comparison = "与该峰值相同" if year_gap == 0 else f"低于该峰值{year_gap:,}美元"
            cards.append(_card(
                part, "same_year_peak_gap",
                f"{latest_observed['month'][:4]}年已观察月份中，最高为{'、'.join(year_peak_months)}的"
                f"{year_high:,}美元；{latest_observed['month']}为{latest_observed['value_usd']:,}美元，"
                f"{comparison}。",
                [latest_observed["month"], *year_peak_months], eligible=False,
                year=latest_observed["month"][:4], latest_month=latest_observed["month"],
                latest_usd=latest_observed["value_usd"], high_usd=year_high,
                high_months=year_peak_months, gap_usd=year_gap))
    summary = part.get("summary")
    if isinstance(summary, Mapping) and summary.get("complete_window") is True:
        total = summary.get("period_total_usd")
        if (type(total) is int and total >= 0 and len(rows) > 1 and
                len(observed) == len(rows) and total == sum(row["value_usd"] for row in rows)):
            cards.append(_card(part, "period_total",
                               f"{flow}金额在{rows[0]['month']}至{rows[-1]['month']}合计{total:,}美元。",
                               [row["month"] for row in rows], eligible=False))
            cards[-1]["total_usd"] = total
    return cards, latest_sign


def build_snapshot(report: Mapping[str, Any], digest: str) -> dict[str, Any]:
    if report_sha256(report) != digest:
        raise ValueError("贸易报告摘要不匹配")
    parts = ([report.get("import_report"), report.get("export_report")]
             if report.get("kind") == "trade-query-both-v1" else [report])
    cards: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    signs: dict[str, str] = {}
    for part in parts:
        if not isinstance(part, Mapping) or part.get("kind") != "trade-query-v1":
            raise ValueError("双方向报告缺少有效子报告")
        own, sign = _one_direction(part)
        cards.extend(own)
        card_ids = {item["id"] for item in own}
        prefix = part["scope"]["flow"]
        for suffix, reason in (("latest_change", "相邻两月未同时观察、月份不连续或跨年度口径尚未核验"),
                               ("recent_run", "最近不足两次同向连续变动，或期间有缺月及未核验跨年口径"),
                               ("recent_turn", "最近三个月不构成同年连续反向变动")):
            if f"{prefix}.{suffix}" not in card_ids:
                unavailable.append({"id": f"{prefix}.{suffix}", "reason": reason})
        if sign is not None:
            signs[part["scope"]["flow"]] = sign
    if report.get("kind") == "trade-query-both-v1" and set(signs) == {"import", "export"}:
        imports, exports = parts
        imonths = next(card["months"] for card in cards if card["id"] == "import.latest_change")
        emonths = next(card["months"] for card in cards if card["id"] == "export.latest_change")
        import_partner = imports["scope"].get("partner")
        export_partner = exports["scope"].get("partner")
        same_partner = ((import_partner == export_partner == "CHINA") or
                        (import_partner == "ALL_ORIGINS" and export_partner == "ALL_DESTINATIONS"))
        if (imonths == emonths and imports["scope"].get("product_code") ==
                exports["scope"].get("product_code") and same_partner):
            relation = "同向" if signs["import"] == signs["export"] else "不同向"
            cards.append({"id": "both.latest_relation", "fact":
                          f"在{imonths[-1]}，进口金额较上月{signs['import']}，"
                          f"出口金额较上月{signs['export']}；两方向{relation}。"
                          "进口和出口使用不同口径，不相减、不推断贸易差额。",
                          "flow": "both", "product_code": imports["scope"]["product_code"],
                          "partner": "CHINA" if import_partner == "CHINA" else "ALL",
                          "metric": "separate_import_export_values",
                          "months": imonths, "eligible_for_ai": True, "relation": relation,
                          "import_direction": signs["import"], "export_direction": signs["export"]})
    for card in cards:
        card["report_sha256"] = digest
        card["calculator_version"] = CALCULATOR
        card["status"] = "available"
    return {"schema_version": PROTOCOL, "calculator_version": CALCULATOR,
            "report_sha256": digest, "cards": cards, "unavailable": unavailable,
            "eligible_card_ids": [card["id"] for card in cards if card["eligible_for_ai"]]}


def messages(report: Mapping[str, Any], snapshot: Mapping[str, Any],
             snapshot_digest: str) -> list[dict[str, str]]:
    digest = report_sha256(report)
    if (snapshot.get("report_sha256") != digest or snapshot_sha256(snapshot) != snapshot_digest):
        raise ValueError("关系卡与报告摘要不匹配")
    eligible = snapshot.get("eligible_card_ids")
    if not isinstance(eligible, list) or not eligible:
        raise ValueError("目前没有额外的关系可解释；不调用模型")
    scope = report["scope"]
    payload = {"schema_version": PROTOCOL, "report_sha256": digest,
               "relation_snapshot_sha256": snapshot_digest, "question": report["question"],
               "scope": {key: scope.get(key) for key in
                         ("flow", "product_label", "product_code", "partner", "start_month", "end_month")},
               "relation_cards": snapshot["cards"], "eligible_card_ids": eligible,
               "output_shape": {"schema_version": PROTOCOL, "report_sha256": digest,
                                "relation_snapshot_sha256": snapshot_digest,
                                "interpretations": [{"observation_ids": ["relation card ID"], "text": "中文解释"}]}}
    system = ("你是美国商品贸易报告的编辑。程序已计算数字和关系，你只能解释给定关系卡，"
              "不要复述月度表或堆叠通用免责声明。只输出指定字段的严格JSON。"
              "每条解释引用一到两张卡，至少一张必须属于eligible_card_ids。"
              "不能添加数字、日期、税率、编码、网址、外部来源，不能说全期一直增长或下降，"
              "不能把进口和出口相减、猜原因、作政策因果推断、投资建议或确定性预测。"
              "如果用户问原因或政策，只能说明金额数据不足以判定原因。")
    result = [{"role": "system", "content": system},
              {"role": "user", "content": _encoded(payload).decode("utf-8")}]
    if len(_encoded(result)) > MAX_INPUT_BYTES:
        raise ValueError("模型输入超过通用报告预算，请缩小查询范围")
    return result


def parse(raw: str, report: Mapping[str, Any], snapshot: Mapping[str, Any],
          snapshot_digest: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_RAW_BYTES:
        raise ValueError("模型原答过大或类型无效")
    digest = report_sha256(report)
    if snapshot.get("report_sha256") != digest or snapshot_sha256(snapshot) != snapshot_digest:
        raise ValueError("关系卡与报告摘要不匹配")
    envelope = canonical_response(raw, stage=PROTOCOL)
    answer = envelope["parsed"]
    if not isinstance(answer, dict) or set(answer) != {
        "schema_version", "report_sha256", "relation_snapshot_sha256", "interpretations"
    }:
        raise ValueError("模型解释字段无效")
    if (answer["schema_version"] != PROTOCOL or answer["report_sha256"] != digest or
            answer["relation_snapshot_sha256"] != snapshot_digest):
        raise ValueError("模型解释与本次报告或关系卡不匹配")
    items = answer["interpretations"]
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        raise ValueError("模型解释条目数量无效")
    by_id = {card["id"]: card for card in snapshot["cards"]}
    eligible = set(snapshot["eligible_card_ids"])
    used: set[str] = set()
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"observation_ids", "text"}:
            raise ValueError("模型解释条目字段无效")
        keys, value = item["observation_ids"], item["text"]
        if (not isinstance(keys, list) or not 1 <= len(keys) <= 2 or
                any(not isinstance(key, str) or key not in by_id or key in used for key in keys) or
                len(set(keys)) != len(keys) or not eligible.intersection(keys)):
            raise ValueError("模型解释缺少有效关系卡引用")
        if not isinstance(value, str) or not 12 <= len(value.strip()) <= 160 or _NUMBER.search(value):
            raise ValueError("模型解释文字包含新数字、网址或长度无效")
        if any(term in value for term in ("政策导致", "关税导致", "一定会", "建议买", "贸易顺差", "贸易逆差")):
            raise ValueError("模型解释作出了未支持的推断")
        for clause in re.split(r"[。；;，,]", value):
            if (any(term in clause for term in ("整个期间", "整个查询期间", "全期", "本区间", "所选期间"))
                    and any(term in clause for term in ("一直增加", "一直减少", "一直上涨", "一直下降",
                                                        "持续增加", "持续减少", "呈增加", "呈减少", "呈上涨", "呈下降"))
                    and not any(term in clause for term in ("不能", "无法", "不代表", "不可", "不应", "未能"))):
                raise ValueError("不能把局部变化写成全期走势")
        if (any(term in value for term in ("份额上升", "份额下降", "份额增加", "份额减少",
                                             "价格上涨", "价格下降", "数量增长", "数量减少"))
                and not any(term in value for term in ("不能", "无法", "不代表", "不足以"))):
            raise ValueError("模型解释推断了未提供的份额、价格或数量变化")
        if any(term in str(report.get("question", "")) for term in _CAUSE) and not any(
                term in value for term in ("无法判断", "不能判断", "不足以判断", "无法确定", "不能确定")):
            raise ValueError("原因问题必须说明现有金额数据不足以判断")
        used.update(keys)
        cleaned.append({"observation_ids": list(keys), "text": value.strip()})
    if not used.intersection(eligible):
        raise ValueError("模型解释没有使用实质关系")
    return {"schema_version": PROTOCOL, "report_sha256": digest,
            "relation_snapshot_sha256": snapshot_digest,
            "raw_sha256": envelope["raw_sha256"], "interpretations": cleaned,
            "status": "needs_review"}


__all__ = ["PROTOCOL", "CALCULATOR", "snapshot_sha256", "build_snapshot", "messages", "parse"]
