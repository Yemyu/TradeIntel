"""Fail-closed routing for the currently published product case.

This is deliberately a narrow bridge until trade-query-v1 is available.  It
must never silently turn an unrelated question into the tungsten/solar case.
"""
from __future__ import annotations

import re


POLICY_ID = "us_301_review2025_tungsten_solar"
TUNGSTEN = ("81019400", "81019910", "81019980")
SOLAR = ("28046100", "38180000")
REGISTERED = set(TUNGSTEN + SOLAR)
UNSUPPORTED = re.compile(
    r"大豆|豆粕|玉米|小麦|牛肉|钢铁|汽车|原油|石油|铜|铝|棉花|锂电池|芯片|soybean|soybeans|corn|wheat|beef|copper|aluminum|cotton|\bsteel\b|\bcar\b",
    re.IGNORECASE,
)


def route_published_case(question: str) -> dict[str, object]:
    """Return an explicit product scope, or a truthful unsupported result."""
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ValueError("请先输入一个问题（不超过2000字）")
    q = question.strip()
    if UNSUPPORTED.search(q):
        return {"status": "not_available", "message": "这个商品尚未接入网页查询。已有原始贸易资料正在接入通用查询；这里不会改用钨或光伏的数据回答。"}
    if re.search(r"出口|export", q, re.IGNORECASE):
        return {"status": "not_available", "message": "当前网页使用的是美国进口数据，尚不能回答出口问题。请明确询问美国进口，或等待出口数据接入。"}
    if re.search(r"(?:20\d{2}(?:年|[-/]\d{1,2})?|去年|前年|同比|环比)", q):
        return {"status": "not_available", "message": "当前网页固定展示已发布的 2026-02 至 2026-07 案例，不能按问题指定年份或比较区间。通用时间查询仍在接入。"}
    codes = set(re.findall(r"(?<!\d)\d{8}(?!\d)", q))
    if codes - REGISTERED:
        return {"status": "not_available", "message": "问题中有尚未开放的商品编码，这里不会替换成其他商品。"}
    if "钨" in q or re.search(r"tungsten", q, re.IGNORECASE):
        codes.update(TUNGSTEN)
    if re.search(r"光伏|太阳能|多晶硅|硅片|晶圆|solar|photovoltaic|wafer|polysilicon", q, re.IGNORECASE):
        codes.update(SOLAR)
    if not codes and re.search(r"(?:301|Section\s*301).*(?:关税|政策|tariff|policy)", q, re.IGNORECASE):
        codes.update(REGISTERED)
    if not codes:
        return {"status": "needs_scope", "message": "请指出具体商品。当前网页已开放钨与光伏材料的美国进口案例；其他商品的通用查询仍在接入。"}
    return {"status": "supported_case", "policy_id": POLICY_ID,
            "selected_products": [code for code in TUNGSTEN + SOLAR if code in codes],
            "message": "已按问题识别已登记商品，请核对范围。"}
