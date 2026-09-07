"""V2 evidence reports: model selects tools; host renders registered facts.

V1 is preserved for reproducibility. Free-form model prose stays in the audit
record and is never treated as verified user-facing content.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json

from .agent import ToolCallingAgent
from .repository import EvidenceRepository
from .tools import ToolRegistry, get_causal_readiness, get_descriptive_change


def readiness_v2(*, repository=None):
    repository = repository or EvidenceRepository()
    result = get_causal_readiness(repository=repository)
    coverage = repository.matching_reports()["v1"]["coverage"]
    result["data"]["matching"].update({
        "v1_treated_denominator": coverage["coverage_denominator"],
        "v1_treated_with_at_least_two_controls": coverage["treated_with_at_least_two_controls"],
        "v1_treated_unit": "HS6_2017 eligible treated product",
    })
    result["tool_version"] = "2.0"
    return result


def descriptive_v2(comparison_id="immediate_post_same_months", *, policy_id="us_301_list1_2018", repository=None):
    repository = repository or EvidenceRepository()
    result = get_descriptive_change(comparison_id, policy_id=policy_id, repository=repository)
    original = repository.statistical_baseline()["comparisons"][comparison_id]
    for origin in ("target", "other_origins", "all_origins"):
        for period in ("current", "reference"):
            name = f"{origin}_total_{period}_usd"
            result["data"][name] = original[name]
    result["tool_version"] = "2.0"
    return result


class EvidenceRegistryV2(ToolRegistry):
    def __init__(self, repository=None):
        super().__init__(repository)
        self._functions["get_causal_readiness"] = readiness_v2
        self._functions["get_descriptive_change"] = descriptive_v2

    def schemas(self):
        schemas = super().schemas()
        for item in schemas:
            if item["name"] == "get_causal_readiness":
                item["description"] += " Includes eligible treated denominator, count with at least two controls, and coverage rate."
            if item["name"] == "get_descriptive_change":
                item["description"] += " Includes exact current/reference totals in USD, registered windows and changes."
        return schemas


def percent(value):
    return None if value is None else format(Decimal(str(value)) * 100, ".4f")


class EvidenceReport:
    def __init__(self):
        self.sources = {}
        self.facts = []

    def add(self, label, value, sources, *, unit="", evidence_field=""):
        if not sources:
            raise ValueError("没有来源的事实不能展示")
        ids = []
        for source in sources:
            # These objects originate from executed repository tools, not model prose.
            identity = json.dumps(source, sort_keys=True, ensure_ascii=False)
            sid = "S" + hashlib.sha256(identity.encode()).hexdigest()[:12]
            self.sources[sid] = deepcopy(source)
            ids.append(sid)
        self.facts.append({"label": label, "value": deepcopy(value), "unit": unit,
                           "source_ids": ids, "evidence_field": evidence_field})

    def render(self):
        lines = ["已查询到的登记事实（问题是否完全回答仍需核对）：", ""]
        for fact in self.facts:
            value = fact["value"]
            if value is None:
                value = "未观测/未知，不能视为0"
            elif isinstance(value, (list, dict, bool)):
                value = json.dumps(value, ensure_ascii=False)
            elif type(value) is int:
                value = format(value, ",")
            lines.append(f"- {fact['label']}：{value} {fact['unit']} [{', '.join(fact['source_ids'])}]")
        lines += ["", "来源（标识与上述事实对应）："]
        for sid, source in self.sources.items():
            lines.append(f"- [{sid}] " + "；".join(f"{k}: {source[k]}" for k in ("path", "url", "file_name", "sha256") if source.get(k)))
        lines += ["", "哈希用于核对文件版本和完整性，不独立证明事实真实性。",
                  "以上贸易金额为美国进口、所列原产地和月份的登记范围；仅作描述性分析。",
                  "当前版本不发布模型自由撰写的解释；缺少的数据和未覆盖的问题仍需复核。"]
        return "\n".join(lines)


def build_report(results):
    report = EvidenceReport()
    seen = set()
    series_groups = {}
    for result in results:
        if result.get("status") != "ok":
            continue
        fingerprint = json.dumps(result, sort_keys=True, ensure_ascii=False)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        name, d = result["tool_name"], result["data"]
        sources = result["evidence"]["sources"]
        def from_file(suffix):
            return [s for s in sources if s.get("path", "").endswith(suffix)]
        def add(field, label, selected, unit=""):
            report.add(label, d.get(field), selected, unit=unit, evidence_field=f"{name}.data.{field}")
        if name == "get_policy_event":
            event = from_file("section301_list1_event.csv")
            for field, label in (("policy_id", "政策标识"), ("policy_name", "项目政策名称"),
                                 ("importer", "进口国"), ("target_origin", "目标原产地"),
                                 ("announcement_date", "宣布日期"), ("effective_date", "生效日期"),
                                 ("transition_month", "过渡月：不作完整政策后月")):
                add(field, label, event)
            add("additional_rate_percent", "额外税率", event, "%")
            add("policy_hts8_count", "政策清单商品数量", from_file("section301_list1_products.csv"), "HTS8编码")
        elif name == "get_trade_series":
            data_sources = [s for s in sources if s.get("path", "").endswith(("policy_case_monthly.csv", "causal_trade_hs6_monthly.csv"))]
            group_key = tuple(d.get(k) for k in ("policy_id", "scope", "hs6", "origin"))
            group = series_groups.setdefault(group_key, {"months": {}, "sources": []})
            group["sources"].extend(data_sources)
            report.add("本次查询范围", {k:d.get(k) for k in ("policy_id", "scope", "hs6", "origin", "start", "end")}, data_sources)
            for item in d["series"]:
                if item["month"] in group["months"] and group["months"][item["month"]] != item["value_usd"]:
                    raise ValueError("同一范围同月的工具值冲突")
                group["months"][item["month"]] = item["value_usd"]
                relevant = data_sources + [s for s in sources if s.get("month") == item["month"]]
                report.add(f"{item['month']} / {d['origin']} 进口额", item["value_usd"], relevant, unit="美元",
                           evidence_field=f"get_trade_series.data.series[{item['month']}].value_usd")
            for field, label in (("total_usd", "本次查询完整窗口合计"), ("observed_total_usd", "本次查询已观测月份合计")):
                add(field, label, data_sources, "美元")
            add("missing_months", "缺失月份（不得补零）", data_sources)
        elif name == "get_descriptive_change":
            selected = from_file("statistical_baseline_summary.json")
            for field, label in (("comparison_id", "已登记比较"), ("reference_months", "基期月份"),
                                 ("current_months", "当期月份"), ("coverage_comparability_status", "覆盖可比性筛查")):
                add(field, label, selected)
            for origin, label in (("target", "中国原产"), ("other_origins", "其他原产地"), ("all_origins", "全部原产地")):
                for period, when in (("reference", "基期"), ("current", "当期")):
                    add(f"{origin}_total_{period}_usd", f"{label}{when}进口额", selected, "美元")
                report.add(f"{label}描述性变化", percent(d[f"{origin}_change_pct"]), selected, unit="%",
                           evidence_field=f"get_descriptive_change.data.{origin}_change_pct ×100")
            add("target_share_change_percentage_points", "中国份额变化", selected, "个百分点")
            report.add("解释限制", "这些变化不是因果效果；同期宏观变化、提前进口和贸易转移均可能影响比较", selected)
        elif name == "get_data_quality_status":
            selected = from_file("data_quality_report.json")
            add("overall_status", "数据质量状态（需复核不等于无条件通过）", selected)
            for field, label in (("trade_rows", "贸易记录数"), ("policy_product_rows", "政策商品数"),
                                 ("month_count", "覆盖月数"), ("origin_count", "原产国数量"),
                                 ("failed_rule_count", "失败规则数"), ("review_rule_count", "复核规则数"),
                                 ("policy_codes_without_trade", "未观察到贸易的政策商品编码"),
                                 ("origin_codes_with_name_changes", "名称发生变化的稳定原产国代码")):
                report.add(label, d["summary"].get(field), selected, evidence_field=f"get_data_quality_status.data.summary.{field}")
            report.add("通过规则数", sum(r["status"] == "pass" for r in d["rules"]), selected)
            report.add("贸易总额", d["summary"]["trade_value_usd"], selected, unit="美元")
            report.add("复核要求", "历史名称按稳定代码聚合；未观察商品不能静默补零。数据质量通过不授权因果结论。", selected)
        elif name == "get_causal_readiness":
            v1 = from_file("matching_balance_report.json")
            m = d["matching"]
            for field, label, unit in (("v1_treated_denominator", "合格处理商品分母", "HS6_2017商品"),
                ("v1_treated_with_at_least_two_controls", "至少有两个对照的处理商品数", "HS6_2017商品"),
                ("v1_failed_balance_features", "v1未通过平衡的特征", "")):
                report.add(label, m[field], v1, unit=unit, evidence_field=f"get_causal_readiness.data.matching.{field}")
            report.add("v1覆盖率", percent(m["v1_coverage_rate"]), v1, unit="%")
            for version in ("v2", "v3"):
                selected = from_file(f"matching_balance_report_{version}.json")
                report.add(f"{version}匹配状态", m[f"{version}_status"], selected)
                report.add(f"{version}求解状态码", m[f"{version}_solver_status_code"], selected)
            v3 = from_file("matching_balance_report_v3.json")
            report.add("v3已观测选中处理商品数", m["v3_selected_treated"], v3)
            report.add("v3计数解释", "无可行解时原报告的0是占位；未测量无约束最大匹配数量。", v3)
            add("status", "当前因果状态", v3)
            report.add("当前能力边界", "匹配阶段未通过；前趋势检验与事件研究未运行，不能报告关税因果效果。", v3)
    for key, group in series_groups.items():
        months = group["months"]
        sources = list({json.dumps(s, sort_keys=True): s for s in group["sources"]}.values())
        report.add("同范围多次查询去重月份", {"policy_id":key[0], "scope":key[1], "hs6":key[2], "origin":key[3],
                   "months":sorted(months)}, sources)
        total = None if any(v is None for v in months.values()) else sum(months.values())
        report.add("上述已查询月份去重合计（须核对是否符合所问月份）", total, sources, unit="美元",
                   evidence_field="sum(unique month values within identical policy/scope/hs6/origin)")
    return report


class EvidenceAgentV2(ToolCallingAgent):
    def __init__(self, model, registry=None, **kwargs):
        super().__init__(model, registry or EvidenceRegistryV2(), **kwargs)

    def answer(self, question):
        previous = super().answer(question)
        if previous.get("status") == "error":
            return {**previous, "version": "2.0", "task_success_verified": False}
        try:
            report = build_report(previous["tool_results"])
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "version": "2.0", "error": "证据字段或来源不完整，停止生成报告",
                    "task_success_verified": False}
        draft = previous.get("original_model_response") or previous.get("response", "")
        return {"status": "needs_review", "version": "2.0", "answer_kind": "host_rendered_evidence_report",
                "response": report.render(), "facts": report.facts, "sources": report.sources,
                "draft_for_audit_only": draft, "model_prose_published": False,
                "task_success_verified": False, "final_answer_verified": False, "review_required": True,
                "causal_claim": False, "model_selected_tools": previous["model_selected_tools"],
                "host_selected_tools": previous["host_selected_tools"], "model_run": previous.get("model_run"),
                "tool_results": previous["tool_results"], "legacy_guard_triggered": previous["safety_guard_triggered"]}
