"""Provider-neutral ``public-brief-explanation-v1`` contract.

The deterministic temporal report owns every number, date, source and
comparison permission.  The provider receives one versioned v2 business view
containing all observations and metrics.  This module only accepts plain
language keyed to those existing IDs; it never turns a model answer into
evidence by itself.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Mapping

from .analysis_request import validate_analysis_request
from .response_contract import canonical_response
from .temporal_evidence import validate_temporal_evidence
from .public_input_view import VIEW_SCHEMA, build_view


PROTOCOL = "public-brief-explanation-v1"
_WATCH_IDS = {"next_trade_release", "origin_mix", "policy_revision", "coverage_gap"}
_KINDS = {"meaning", "hypothesis"}
_OBSERVATION_KINDS = {"level", "comparison", "composition", "coverage"}
_NO_NUMERIC = re.compile(r"\d|[%％]|https?://|<[^>]*>|百分之")


def _watchlist_ids(report: Mapping[str, Any]) -> list[str]:
    """Return only watch items already emitted by the program report."""
    items = report.get("watchlist")
    if not isinstance(items, list):
        raise ValueError("报告 watchlist 必须是列表")
    result: list[str] = []
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {"watch_id", "rationale"}:
            raise ValueError("报告 watchlist 项字段无效")
        watch_id = item.get("watch_id")
        rationale = item.get("rationale")
        if (not isinstance(watch_id, str) or watch_id not in _WATCH_IDS
                or watch_id in result or not isinstance(rationale, str)
                or not 1 <= len(rationale.strip()) <= 200):
            raise ValueError("报告 watchlist 项无效")
        result.append(watch_id)
    return result


def _observation_catalog(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    observations = evidence.get("observations")
    if not isinstance(observations, list):
        raise ValueError("证据缺少 observations")
    catalog: list[dict[str, Any]] = []
    for item in observations:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise ValueError("观察目录含无效 ID")
        if item.get("kind") not in _OBSERVATION_KINDS:
            raise ValueError("观察目录含不受支持的类型")
        catalog.append({
            "observation_id": item["id"],
            "kind": item["kind"],
            "scope": deepcopy(item.get("scope") or {}),
            "comparability": item.get("comparability"),
            "fact_sentence": str(item.get("fact_sentence") or ""),
        })
    if not catalog:
        raise ValueError("没有可供解释的程序观察")
    return catalog


def _observation_aliases(evidence: Mapping[str, Any]) -> dict[str, str]:
    observations = evidence.get("observations")
    if not isinstance(observations, list):
        raise ValueError("证据缺少 observations")
    aliases: dict[str, str] = {}
    for index, item in enumerate(observations, 1):
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise ValueError("观察目录含无效 ID")
        aliases[f"o{index}"] = item["id"]
    return aliases


def _validate_request_context(context: Any, report: Mapping[str, Any]) -> dict[str, Any] | None:
    if context is None:
        return None
    if not isinstance(context, Mapping) or context.get("schema_version") != "public-request-context-v1":
        raise ValueError("request_context 格式无效")
    required = {"schema_version", "kind", "parent_request_digest", "parent_data_version",
                "parent_task_id", "parent_window", "selected_products", "summary"}
    if set(context) != required or context.get("kind") != "prior_program_report":
        raise ValueError("request_context 字段无效")
    if context.get("parent_data_version") != report.get("data_version"):
        raise ValueError("request_context 与报告版本不一致")
    if (not isinstance(context.get("selected_products"), list)
            or not context["selected_products"]
            or any(code not in (report.get("request") or {}).get("products", [])
                   for code in context["selected_products"])):
        raise ValueError("request_context 商品不在当前请求中")
    if not isinstance(context.get("summary"), list) or len(context["summary"]) > 8:
        raise ValueError("request_context 摘要无效")
    return deepcopy(dict(context))


def messages(question: str, report: Mapping[str, Any], *,
             policy_context: Mapping[str, Any] | None = None,
             request_context: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    """Build the exact provider input without making a network call."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("解释问题不能为空")
    if not isinstance(report, Mapping) or report.get("schema_version") != "public-report-v1":
        raise ValueError("解释输入必须是 public-report-v1")
    request = validate_analysis_request(report.get("request") or {})
    request_context = _validate_request_context(request_context, report)
    evidence = report.get("evidence")
    validate_temporal_evidence(evidence, request)
    observations = _observation_catalog(evidence)
    watch_ids = _watchlist_ids(report)
    packet = build_view(report, policy_context)
    template = {
        "schema_version": PROTOCOL,
        "interpretations": [{"observation_id": "o1",
                              "kind": "meaning", "text": "用通俗语言说明这条观察的含义"}],
        "watchlist": ([{"watch_id": watch_ids[0],
                         "rationale": "说明下一步应观察什么以及原因"}]
                       if watch_ids else []),
    }
    system = (
        "你只解释程序已经生成的观察，不重算或改写事实。只输出一个严格JSON对象，"
        "顶层键必须是 schema_version、interpretations、watchlist；不要Markdown围栏。"
        "interpretations最多六项，每项只能引用 view.evidence.observations.rows 中的 id（o1、o2…），"
        "kind只能是meaning或hypothesis；watchlist最多三项且只能使用程序给出的watch_id。"
        "view.evidence中包含全部观察、全部指标、来源ID/URL和政策条件，没有需要另猜的隐藏目录。"
        "观察行列依次为id、kind、scope、comparability、metric_ids、source_set；scope的l/o/s/c分别表示"
        "水平、来源构成、序列、跨期比较。metric_ids中的m1、m2…对应metrics.levels、comparisons、origins"
        "表中的ids位置；表头和semantics说明每个值的指标含义、单位、状态和分母。"
        "source_set通过source_sets连接到sources；source表中的压缩引用按prefixes拼回原始source_id或URL。"
        "如果存在request_context，它是服务端提供的上一份程序报告摘要和本次选卡范围；只能用于理解追问上下文，"
        "不能把摘要中的文字当成新的证据，也不能改变当前view中的数字。"
        "文字只能用中文通俗说明含义或待验证假设，不得输出阿拉伯数字、百分号、日期、税号、金额、税率、"
        "网址、HTML或新的来源。不要把统计变化说成政策因果、替代能力、税款、损失、投资建议或确定性预测。"
        "比较口径为unknown/unverified/incompatible时，必须保留不确定性，不得补成趋势；假设要明确写成可能的解释、"
        "尚待验证。美元指标称进口金额，不称贸易量。来源地沿metric_ids核对同商品同月origins，勿串商品。"
        "解释具体变化及意义。价格题须说明缺失资料及用途，用hypothesis解释条件性传导。日期税率由程序展示。"
        "输出格式示例：" + json.dumps(template, ensure_ascii=False)
    )
    payload = {
        "protocol": PROTOCOL,
        "question": question,
        "view_schema": VIEW_SCHEMA,
        "view_sha256": packet["sidecar"]["view_sha256"],
        "view": packet["view"],
        "watchlist_catalog": watch_ids,
    }
    if request_context is not None:
        payload["request_context"] = request_context
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False,
                                                      separators=(",", ":"))}]


def parse(raw: str, report: Mapping[str, Any]) -> dict[str, Any]:
    """Parse and structurally validate one model answer losslessly."""
    if not isinstance(report, Mapping) or report.get("schema_version") != "public-report-v1":
        raise ValueError("解释输入必须是 public-report-v1")
    request = validate_analysis_request(report.get("request") or {})
    evidence = report.get("evidence")
    validate_temporal_evidence(evidence, request)
    catalog = _observation_catalog(evidence)
    observation_ids = {item["observation_id"] for item in catalog}
    aliases = _observation_aliases(evidence)
    accepted_ids = observation_ids | set(aliases)
    watchlist_ids = set(_watchlist_ids(report))
    envelope = canonical_response(raw, stage=PROTOCOL)
    answer = envelope["parsed"]
    if not isinstance(answer, dict) or set(answer) != {"schema_version", "interpretations", "watchlist"}:
        raise ValueError("public-brief-explanation-v1 顶层字段无效")
    if answer["schema_version"] != PROTOCOL:
        raise ValueError("解释协议版本不一致")
    interpretations = answer["interpretations"]
    watchlist = answer["watchlist"]
    if not isinstance(interpretations, list) or len(interpretations) > 6:
        raise ValueError("interpretations 必须是0至6项列表")
    if not isinstance(watchlist, list) or len(watchlist) > 3:
        raise ValueError("watchlist 必须是0至3项列表")
    seen_pairs: set[tuple[str, str]] = set()
    clean_interpretations: list[dict[str, str]] = []
    for item in interpretations:
        if not isinstance(item, dict) or set(item) != {"observation_id", "kind", "text"}:
            raise ValueError("interpretation 字段无效")
        observation_id, kind, text = item["observation_id"], item["kind"], item["text"]
        if observation_id not in accepted_ids or kind not in _KINDS:
            raise ValueError("interpretation 引用了不存在的观察或类型")
        observation_id = aliases.get(observation_id, observation_id)
        if (observation_id, kind) in seen_pairs:
            raise ValueError("同一观察和解释类型不能重复")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 350:
            raise ValueError("interpretation text 必须是1至350字")
        if _NO_NUMERIC.search(text):
            raise ValueError("解释文字不能新增数字、百分号、网址或HTML")
        seen_pairs.add((observation_id, kind))
        clean_interpretations.append({"observation_id": observation_id,
                                      "kind": kind, "text": text.strip()})
    seen_watch: set[str] = set()
    clean_watchlist: list[dict[str, str]] = []
    for item in watchlist:
        if not isinstance(item, dict) or set(item) != {"watch_id", "rationale"}:
            raise ValueError("watchlist 字段无效")
        watch_id, rationale = item["watch_id"], item["rationale"]
        if watch_id not in watchlist_ids or watch_id in seen_watch:
            raise ValueError("watchlist 引用了不存在或重复的观察项")
        if not isinstance(rationale, str) or not 1 <= len(rationale.strip()) <= 200:
            raise ValueError("watchlist rationale 必须是1至200字")
        if _NO_NUMERIC.search(rationale):
            raise ValueError("观察事项不能新增数字、百分号、网址或HTML")
        seen_watch.add(watch_id)
        clean_watchlist.append({"watch_id": watch_id, "rationale": rationale.strip()})
    return {
        "protocol": PROTOCOL,
        "schema_version": PROTOCOL,
        "raw_sha256": envelope["raw_sha256"],
        "interpretations": clean_interpretations,
        "watchlist": clean_watchlist,
        "status": "manual_review_required" if clean_interpretations else "needs_revision",
        "boundary": "模型只能解释已绑定观察；数字、来源、日期和比较权限由程序报告保留，人工复核后才能合并。",
    }


__all__ = ["PROTOCOL", "messages", "parse"]
