"""Conservative request constraints, independent of model-proposed tool arguments."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from .trade_data_repository import TradeDataError
from .trade_query_flow import _direction, _explicit_period


class RequestConstraintError(TradeDataError):
    def __init__(self, message: str, kind: str):
        self.kind = kind
        super().__init__(message)


def _field(value=None, status="unspecified", basis="default", evidence=""):
    return {"value": value, "status": status, "basis": basis, "evidence": evidence}


def derive_constraints(question: str, previous_scope: dict | None = None,
                       today: date | None = None, clarification=None) -> dict[str, Any]:
    """Bind explicit supported grammar only; unresolved requests require clarification."""
    previous = previous_scope or {}
    # Negated choices are not affirmative directions or partners. Retain the
    # original text below, rather than changing the user's persisted question.
    affirmative = re.sub(r"(?:不是|并非|不要(?:查)?|不查|别查)\s*(?:进口|出口|中国|上个月|上月)",
                         " ", question, flags=re.I)
    affirmative = re.sub(r"\b(?:not|no)\s+(?:imports?|exports?|china|last month)\b",
                         " ", affirmative, flags=re.I)
    result = {"schema": "trade-request-constraints-v1", "question": question,
              "reporter": _field("US"), "flow": _field(), "partner": _field(),
              "period": _field(), "product_anchors": [], "issues": []}
    direction = _direction(affirmative)
    if direction != "ambiguous":
        result["flow"] = _field(direction, "known", "explicit", affirmative)
    elif previous.get("flow"):
        result["flow"] = _field(previous["flow"], "known", "inherited")

    all_partner = bool(re.search(r"全部|所有|全球|全世界|all\s+(?:destinations|origins)",
                                 affirmative, re.I))
    china = bool(re.search(
        r"(?:从|向|对|到|去往)\s*中国|中国(?:来源|目的地|呢|部分|方向|的份额)|"
        r"(?:to|from)\s+china|\bchina\s*(?:origins?|destinations?|share)|"
        r"(?:进口|出口)\s*中国|^\s*(?:中国|china)[？?。\s]*$", affirmative, re.I))
    if all_partner:
        result["partner"] = _field("all", "known", "explicit", affirmative)
    elif china:
        result["partner"] = _field("china", "known", "explicit", affirmative)
    elif previous.get("partner"):
        result["partner"] = _field("china" if previous["partner"] == "CHINA" else "all",
                                   "known", "inherited")
    if re.search(r"(?:除|排除).*?(?:中国|china)|(?:excluding|except)\s+china", question, re.I):
        result["issues"].append("当前全部伙伴统计包含中国，不能计算排除中国的金额。")
    elif re.search(r"(?:不要|不看|不是|not)\s*(?:中国|china)", question, re.I) and not all_partner:
        result["partner"] = _field(None, "ambiguous", "explicit", question)
        result["issues"].append("请说明是查看全部伙伴，还是要求排除中国；目前不能计算排除中国的金额。")

    # Role-bound patterns, not a blanket ban on foreign countries in context.
    for match in re.finditer(r"(?:从|向|对)([\u4e00-\u9fffA-Za-z ]{1,30}?)(?:进口|出口|采购)", affirmative):
        entity = match.group(1).strip()
        if entity in {"中国", "China", "china"}:
            result["partner"] = _field("china", "known", "explicit", match.group())
        elif entity not in {"美国", "US", "U.S."}:
            result["partner"] = _field(entity, "unsupported", "explicit", match.group())
            result["issues"].append(f"当前未接入伙伴“{entity}”的查询，不能改查全部伙伴。")
    country = r"日本|英国|欧盟|欧洲|巴西|加拿大|中国|Japan|UK|Brazil|Canada|China"
    reporter = re.search(rf"(?<!从)(?<!向)(?<!对)({country})(?:的)?(?:大豆|豆油|玉米|小麦|茶叶|汽车|棉花|soybeans?|cars?|wheat)?\s*(?:进口|出口|imports?|exports?)",
                         affirmative, re.I)
    if reporter and not re.search(r"美国|\bU\.?S\.?\b|United States", affirmative, re.I):
        result["reporter"] = _field(reporter.group(1), "unsupported", "explicit", reporter.group())
        result["issues"].append("当前只接入美国报告方数据，不能替代其他国家的统计。")
    if re.search(r"中国从美国进口|China\s+imports?\s+from\s+(?:the\s+)?US", affirmative, re.I):
        result["reporter"] = _field("China", "unsupported", "explicit", affirmative)
        result["issues"].append("中国进口统计不等于美国出口统计；如需美国出口视角，请明确提出。")

    date_text = re.sub(r"(?:不是|并非|不要(?:查)?|不查)\s*20\d{2}年\s*(?:0?[1-9]|1[0-2])月", " ", affirmative)
    parsed = _explicit_period(date_text)
    if isinstance(parsed, tuple):
        result["period"] = _field({"start": parsed[0], "end": parsed[1]}, "known", "explicit", affirmative)
    elif isinstance(parsed, str):
        result["period"] = _field(None, "ambiguous", "explicit", affirmative)
        result["issues"].append(parsed)
    if re.search(r"同比|去年同期|year.over.year|\byoy\b", affirmative, re.I):
        result["issues"].append("跨年商品口径可比性尚未核验，当前不能直接给出同比结论。")
    return result


def validate_query_constraints(constraints: dict, candidate: dict, flow: str,
                               partner: str, start: str, end: str) -> None:
    if constraints["issues"]:
        raise TradeDataError(constraints["issues"][0])
    requested = constraints["flow"]
    if requested["status"] == "known" and requested["value"] != "both" and flow != requested["value"]:
        raise RequestConstraintError("查询方向与用户要求不一致，请重新查询。", "flow")
    period = constraints["period"]
    if period["status"] == "known" and (start, end) != (period["value"]["start"], period["value"]["end"]):
        raise RequestConstraintError("查询月份与用户明确指定的月份不一致。", "period")
    # Additional partners are permitted, but they cannot replace the required
    # primary report; that requirement is checked at finish, below.


def validate_finished_scope(constraints: dict, reports: list[dict]) -> None:
    if constraints["issues"]:
        raise TradeDataError(constraints["issues"][0])
    partner = constraints["partner"]["value"]
    matching = [r for r in reports if partner is None or
                (r["scope"]["partner"] == "CHINA") == (partner == "china")]
    if not matching:
        raise RequestConstraintError("报告没有回答用户要求的伙伴范围。", "partner")
    if constraints["flow"]["value"] == "both":
        groups: dict[tuple, set] = {}
        for report in matching:
            s = report["scope"]
            key = (s["product_code"], s["start_month"], s["end_month"], s["partner"] == "CHINA")
            groups.setdefault(key, set()).update({"import", "export"} if s["flow"] == "both" else {s["flow"]})
        if not any(flows == {"import", "export"} for flows in groups.values()):
            raise RequestConstraintError("用户要求进出口，报告须分别涵盖同一商品和期间的两个方向。", "flow")
