"""Offline presentation adapter for frozen v2.1 results, with an unchanged audit ledger.

This adapter does not call a model, query data, infer user intent or assign accuracy.
Only consume trusted host execution records; rebuilding facts is not authentication.
"""
from copy import deepcopy
import hashlib
import json

from .evidence_v21 import report_v21


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def format_value(value):
    if value is None:
        return "未知，不能视为0"
    if type(value) is int:
        return f"{value:,}"
    if isinstance(value, (list, dict, bool)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def build_view(result):
    """Keep authoritative facts intact; derive explicit presentation-only annotations."""
    if result.get("version") != "2.1" or result.get("status") != "needs_review":
        return {"status":"unavailable", "presentation_version":"1.0",
                "response":"本次运行没有可核验的完整证据报告，请检查运行记录。",
                "task_success_verified":False}
    expected = report_v21(result["tool_results"])
    if canonical(expected.facts) != canonical(result["facts"]) or canonical(expected.sources) != canonical(result["sources"]):
        raise ValueError("事实或来源与执行记录不一致；停止展示")
    turns = (result.get("model_run") or {}).get("turns", [])
    complete = bool(turns and turns[-1].get("finish_reason") == "stop")
    ledger = deepcopy({"facts":result["facts"],"sources":result["sources"]})
    selected = set(result.get("model_selected_tools", []))
    sections = []

    def section(title, facts):
        if facts:
            sections.append({"title":title,"facts":facts})

    def display(fact, *, label=None, value=None):
        output = deepcopy(fact)
        if label is not None:
            output["label"] = label
        if value is not None:
            output["value"] = value
        return output

    seen = set()
    for tool in result["tool_results"]:
        if tool.get("status") != "ok":
            continue
        fingerprint = canonical(tool)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        name, data = tool["tool_name"], tool["data"]
        facts = report_v21([tool]).facts
        if name == "get_trade_series":
            requested = data["requested_months"]
            observed = [r for r in data["series"] if r["value_usd"] is not None]
            body = []
            for fact in facts:
                label = fact["label"]
                if label == "本次查询范围":
                    scope = {k:data.get(k) for k in ("policy_id","scope","hs6","origin")}
                    scope["months"] = requested
                    body.append(display(fact,label="请求范围（按列出的月份查询）",value=scope))
                elif " / " in label and label.endswith("进口额"):
                    body.append(fact)
                elif label == "本次查询完整窗口合计":
                    body.append(display(fact,label="所列请求月份合计"))
                elif label == "本次查询已观测月份合计" and data["missing_months"]:
                    item=display(fact,label="已取得数据的小计（不代表完整请求合计）")
                    if not observed:
                        item.update(value="无可计算观测",unit="")
                    body.append(item)
                elif label == "缺失月份（不得补零）" and data["missing_months"]:
                    body.append(fact)
                elif label == "不可查月份说明":
                    message=(f"{', '.join(data['unavailable_months'])} 超出本项目数据范围 "
                             "2016-01至2019-12；金额未知，不能补零。这不表示官方不存在该数据。")
                    if observed:
                        message += "本次已返回可查月份：" + ", ".join(r["month"] for r in observed) + "。"
                    else:
                        message += "本次查询没有取得任何可用月份金额。"
                    body.append(display(fact,value=message))
            origin={"China":"中国原产","other_origins":"其他原产地","all_origins":"全部原产地"}.get(data['origin'],data['origin'])
            section(f"美国进口额 · {origin}",body)
        elif name == "get_causal_readiness":
            if name in selected:
                section("匹配与因果分析边界",facts)
            else:
                section("当前解释限制",[f for f in facts if f["label"] == "当前能力边界"])
        else:
            section({"get_policy_event":"政策登记信息","get_descriptive_change":"登记同期比较",
                     "get_data_quality_status":"数据质量"}.get(name,name),facts)
    # Cross-tool explanation belongs to the main answer only when the model
    # requested matching evidence as well as policy information.
    if {"get_policy_event","get_causal_readiness"} <= selected:
        section("商品计数解释",[f for f in ledger["facts"] if f['label']=="三个计数为何不能混用"])
    trade_calls = [t for t in result["tool_results"] if t.get("status")=="ok" and t['tool_name']=='get_trade_series']
    if len(trade_calls)>1:
        section("相同范围查询去重汇总",[f for f in ledger['facts'] if f['label'] in
            ("同范围多次查询去重月份","上述已查询月份去重合计（须核对是否符合所问月份）")])
    used_ids = {sid for s in sections for f in s["facts"] for sid in f["source_ids"]}
    if not used_ids <= ledger["sources"].keys():
        raise ValueError("展示来源不完整")
    lines = ["证据报告（内容仍需核对）" if complete else "部分证据报告（模型未完整结束）", ""]
    for s in sections:
        lines += [f"### {s['title']}", ""]
        for f in s["facts"]:
            lines.append(f"- {f['label']}：{format_value(f['value'])} {f['unit']} [{', '.join(f['source_ids'])}]")
        lines.append("")
    if result.get("failed_tool_requests"):
        lines += ["部分工具请求失败，以上证据可能未覆盖全部所问内容。", ""]
    lines += ["<details>", "<summary>来源与版本核对</summary>", ""]
    for sid in sorted(used_ids):
        source=ledger['sources'][sid]
        lines.append(f"- [{sid}] " + "；".join(f"{k}: {source[k]}" for k in ('path','url','file_name','sha256') if source.get(k)))
    lines += ["", "</details>", "", "哈希用于核对文件版本，不独立证明事实真实。以上金额仅为描述性统计。"]
    return {"status":"needs_review", "presentation_version":"1.0", "generation_complete":complete,
            "response":"\n".join(lines), "sections":sections, "audit_ledger":ledger,
            "audit_ledger_sha256":hashlib.sha256(canonical(ledger).encode()).hexdigest(),
            "model_prose_published":False,"task_success_verified":False,
            "scope_verified_against_user_intent":False,
            "limitation":"Offline presentation only. Tool choices and raw model behavior are unchanged."}
