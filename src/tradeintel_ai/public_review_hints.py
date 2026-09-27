"""Advisory prompts for human review, never a semantic acceptance gate."""
from __future__ import annotations


def review_hints(answer: dict, *, question: str) -> list[dict[str, str]]:
    """Accept a production-parsed answer and flag places needing inspection.

    These lexical checks neither prove correctness nor automatically reject
    explanations. In particular, country names require source-row inspection.
    """
    hints = []
    items = answer.get("interpretations", [])
    for index, item in enumerate(items):
        text = item["text"]
        if "贸易量" in text or "进口量" in text:
            hints.append({"code": "amount_quantity_ambiguity", "location": f"interpretations[{index}]",
                          "reason": "核对指标单位；若为USD金额，应说明进口金额。若此处是否定数量推断，可保留。"})
        if ":origins" in item["observation_id"]:
            hints.append({"code": "origin_rows_manual_check", "location": f"interpretations[{index}]",
                          "reason": "逐一核对同商品同月来源地及排名；存在此提示不代表来源写错。"})
    for index, item in enumerate(answer.get("watchlist", [])):
        if "贸易量" in item["rationale"] or "进口量" in item["rationale"]:
            hints.append({"code": "amount_quantity_ambiguity", "location": f"watchlist[{index}]",
                          "reason": "确认后续观察说的是金额还是实物数量。"})
    if any(word in question for word in ("涨价", "价格", "降价")):
        if not any(item["kind"] == "hypothesis" for item in items):
            hints.append({"code": "price_mechanism_review", "location": "interpretations",
                          "reason": "核对是否解释了待验证传导机制、缺少的资料及用途；不能仅拒绝预测。"})
    return hints
