"""Explicit month selection and evidence-backed explanations; v2 stays frozen."""
from copy import deepcopy

from .agent import ToolCallingAgent
from .evidence_v2 import EvidenceRegistryV2, build_report
from .repository import EvidenceRepository
from .tools import DATA_START, DATA_END, ToolError, _month_key, get_trade_series


def trade_v21(origin="China", *, months=None, start=None, end=None,
              policy_id="us_301_list1_2018", scope="section301_list1", hs6=None,
              repository=None):
    repository = repository or EvidenceRepository()
    if months is not None:
        if start is not None or end is not None:
            raise ToolError("months 与 start/end 互斥；离散月份请仅传 months")
        if not isinstance(months, list) or not 1 <= len(months) <= 48:
            raise ToolError("months 必须包含 1 至 48 个月份")
        for month in months:
            _month_key(month)
        if len(set(months)) != len(months):
            raise ToolError("months 不能重复，以免重复求和")
        selected = sorted(months)
    else:
        if start is None or end is None:
            raise ToolError("请明确指定 months，或同时指定 start 与 end")
        a, b = _month_key(start), _month_key(end)
        first, last = a[0]*12+a[1]-1, b[0]*12+b[1]-1
        if not 0 <= last-first < 48:
            raise ToolError("连续窗口须为 1 至 48 个月")
        selected = [f"{i//12:04d}-{i%12+1:02d}" for i in range(first,last+1)]
    common = dict(origin=origin, policy_id=policy_id, scope=scope, hs6=hs6, repository=repository)
    available = [m for m in selected if DATA_START <= _month_key(m) <= DATA_END]
    # Validate policy/origin/product even when every requested month is outside coverage.
    probe = available[0] if available else "2016-01"
    result = deepcopy(get_trade_series(start=probe,end=probe,**common))
    data = result["data"]
    data.update(start=selected[0],end=selected[-1],requested_months=selected,months=len(selected),series=[])
    sources = [s for s in result["evidence"]["sources"] if not s.get("month")]
    unavailable = []
    for month in selected:
        if month in available:
            item = get_trade_series(start=month,end=month,**common)
            data["series"].extend(item["data"]["series"])
            sources.extend(item["evidence"]["sources"])
        else:
            unavailable.append(month)
            data["series"].append({"month":month,"value_usd":None,
                                  "observed_product_count":None})
    data["missing_months"] = [r["month"] for r in data["series"] if r["value_usd"] is None]
    data["unavailable_months"] = unavailable
    data["available_window"] = {"start":"2016-01","end":"2019-12"}
    data["observed_total_usd"] = sum(r["value_usd"] for r in data["series"] if r["value_usd"] is not None)
    data["total_usd"] = None if data["missing_months"] else data["observed_total_usd"]
    data["coverage_complete"] = not data["missing_months"]
    result["evidence"]["sources"] = list({str(s):s for s in sources}.values())
    result["tool_version"] = "2.1"
    return result


class EvidenceRegistryV21(EvidenceRegistryV2):
    def __init__(self, repository=None):
        super().__init__(repository)
        self._functions["get_trade_series"] = trade_v21

    def schemas(self):
        schemas = super().schemas()
        for s in schemas:
            if s["name"] == "get_trade_series":
                s["description"] += (
                    " Supply months for exact discrete months; never fill gaps between requested months."
                    " Alternatively supply start AND end for a continuous window."
                    " Do not combine months with start/end. Out-of-coverage months return null with explanation."
                    " Registered comparisons already include exact totals; do not fetch extra series for them.")
                s["parameters"]["properties"]["months"] = {
                    "type":"array","minItems":1,"maxItems":48,"uniqueItems":True,
                    "items":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}$"}}
        return schemas


def report_v21(results):
    report = build_report(results)
    for result in results:
        if result.get("status") != "ok":
            continue
        d, name = result["data"], result["tool_name"]
        sources = result["evidence"]["sources"]
        if name == "get_trade_series":
            selected = [s for s in sources if s.get("path", "").endswith(
                ("policy_case_monthly.csv", "causal_trade_panel_manifest.json"))]
            report.add("实际请求月份（含不可查部分）", d["requested_months"], selected)
            if d["unavailable_months"]:
                report.add("不可查月份说明",
                    f"{', '.join(d['unavailable_months'])} 超出本项目数据覆盖范围 2016-01 至 2019-12；"
                    "金额未知，不能补零，也不表示官方不存在该数据。已返回其余可查月份。", selected)
        elif name == "get_policy_event":
            selected = [s for s in sources if s.get("path", "").endswith("section301_list1_event.csv")]
            report.add("政策核对依据", f"登记生效日为 {d['effective_date']}，额外税率为 "
                       f"{d['additional_rate_percent']}%；与这些值不一致的便签内容需要更正。", selected)
    policy = next((r for r in results if r.get("status")=="ok" and r["tool_name"]=="get_policy_event"),None)
    readiness = next((r for r in results if r.get("status")=="ok" and r["tool_name"]=="get_causal_readiness"),None)
    if policy and readiness:
        sources = [s for r in (policy,readiness) for s in r["evidence"]["sources"]
                   if s.get("path", "").endswith(("section301_list1_products.csv","matching_balance_report.json"))]
        report.add("三个计数为何不能混用",
            "政策清单按 HTS8 编码计数；合格处理分母按跨年对齐并通过资格筛查的 HS6_2017 商品计数；"
            "至少两个对照的数量是该合格分母内满足对照数量要求的子集。"
            "编码粒度和筛选条件不同，不能直接相等或相减解释淘汰数量；找到对照不代表平衡检验通过。",sources)
    return report


class EvidenceAgentV21(ToolCallingAgent):
    def __init__(self, model, registry=None, **kwargs):
        super().__init__(model,registry or EvidenceRegistryV21(),**kwargs)

    def answer(self, question):
        previous = super().answer(question)
        if previous.get("status") == "error":
            return {**previous,"version":"2.1","task_success_verified":False}
        try:
            report = report_v21(previous["tool_results"])
        except (KeyError, TypeError, ValueError):
            return {"status":"error","version":"2.1",
                    "error":"证据字段或来源不完整，停止生成报告",
                    "task_success_verified":False}
        failed = [r for r in previous["model_tool_results"] if r.get("status") != "ok"]
        response = report.render()
        if failed:
            response += "\n部分工具请求失败，所问内容可能尚未覆盖；请检查调用记录。"
        return {"status":"needs_review","version":"2.1","response":response,
                "facts":report.facts,"sources":report.sources,
                "draft_for_audit_only":previous.get("original_model_response") or previous["response"],
                "model_prose_published":False,"task_success_verified":False,
                "final_answer_verified":False,"review_required":True,"causal_claim":False,
                "model_selected_tools":previous["model_selected_tools"],
                "host_selected_tools":previous["host_selected_tools"],
                "model_run":previous["model_run"],"tool_results":previous["tool_results"],
                "failed_tool_requests":failed}
