"""Read-only, bilingual report projection from saved facts; no model prose."""
from copy import deepcopy
import re


def build_reader_view(question: str, reports: list[dict], policy_evidence: dict | None = None) -> dict:
    facts = []
    for report in reports:
        parts = ([report["import_report"], report["export_report"]]
                 if report["scope"]["flow"] == "both" else [report])
        for part in parts:
            scope, summary = part["scope"], part["summary"]
            export = scope["flow"] == "export"
            china = scope["partner"] == "CHINA"
            metric = "出口 FAS 总额" if export else "进口消费额"
            partner = ("中国目的地" if export else "中国来源地") if china else ("全部目的地" if export else "全部来源地")
            metric_en = "total exports (FAS)" if export else "imports for consumption"
            partner_en = ("to China" if export else "from China") if china else ("to all destinations" if export else "from all origins")
            value = summary.get("latest_value_usd")
            month = summary["latest_month"]
            if value is not None and type(value) is not int:
                raise ValueError("invalid saved report amount")
            zh = f"{month}（{partner}）{metric}为 {value:,} 美元。" if value is not None else f"{month}（{partner}）{metric}没有可用金额。"
            en = f"In {month}, {metric_en} {partner_en} were {value:,} USD." if value is not None else f"No published value is available for {month} {metric_en} {partner_en}."
            change = summary.get("month_change_usd")
            if type(change) is int:
                zh += f"较前月{'增加' if change >= 0 else '减少'} {abs(change):,} 美元。"
                en += f" {'Increased' if change >= 0 else 'Decreased'} by {abs(change):,} USD from the previous month."
            facts.append({"report_id": report["report_id"], "scope": deepcopy(scope),
                          "text": zh, "text_en": en})
    policy_question = bool(re.search(r"政策|关税|豁免|税率|policy|tariff|exemption", question, re.I))
    causal_question = bool(re.search(r"原因|为什么|奏效|效果|导致|why|cause|effect", question, re.I))
    unanswered = []
    if causal_question:
        unanswered.append({"text": "金额变化不能单独解释原因或证明政策效果；还需数量与单位、价格及政策适用范围等证据。",
                           "text_en": "Trade values alone cannot explain causes or establish policy effects. Quantity, units, prices and policy applicability need separate evidence."})
    return {"schema": "trade-reader-view-v1", "question": question, "facts": facts,
            "policy": (deepcopy(policy_evidence) if policy_evidence else
                       {"status": "not_recorded", "evidence_bundles": []}) if policy_question else None,
            "unanswered": unanswered,
            "method": {"text": "金额和图表来自本次查询的已发布数据；统计范围和截至月份见各图表。",
                       "text_en": "Values and charts use published data queried for this turn. Each chart identifies its statistical scope and cutoff month."}}
