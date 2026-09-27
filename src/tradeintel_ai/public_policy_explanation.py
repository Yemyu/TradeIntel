"""Explicit policy-answer contract for the offline/public session path.

Keeps v1 trade interpretation validation, adding a separate, source-bound
policy section. It is not the default trade path, and structural acceptance
never certifies the policy claims.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .public_brief_explanation import messages as trade_messages, parse as trade_parse
from .response_contract import canonical_response

PROTOCOL = "public-policy-explanation-prototype-v2"
TOPICS = {"change", "applicability", "limits"}
NO_NUMERIC = re.compile(r"\d|[%％]|https?://|<[^>]*>|百分之")


def _input(question: str, report: Mapping[str, Any], policy_context: Mapping[str, Any],
           request_context: Mapping[str, Any] | None = None):
    base = trade_messages(question, report, policy_context=policy_context,
                          request_context=request_context)
    payload = json.loads(base[1]["content"])
    policy = payload.get("view", {}).get("policy")
    if not isinstance(policy, Mapping):
        raise ValueError("政策解释需要已验证的政策原文来源")
    rows = policy.get("sources", {}).get("rows", [])
    if not rows:
        raise ValueError("政策解释需要已验证的政策原文来源")
    binding = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    return payload, binding, {row[0]: row[1] for row in rows}


def messages(question: str, report: Mapping[str, Any], *,
             policy_context: Mapping[str, Any],
             request_context: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    payload, binding, _ = _input(question, report, policy_context, request_context)
    payload.update(protocol=PROTOCOL, schema_version=PROTOCOL, binding_sha256=binding)
    # No old answers, references or review decisions are added to the input.
    system = (
        "根据程序证据回答政策问题，只输出严格JSON，不输出Markdown。"
        "顶层必须为schema_version、binding_sha256、policy_explanations、interpretations、watchlist。"
        "schema_version和binding_sha256照抄输入。policy_explanations必须是JSON数组，恰好三项；"
        "topic逐字使用change、applicability、limits各一次，不得翻译；每项仅含示例字段。结构示例："
        '[{"topic":"change","source_ids":["<p-id>"],"text":"<text>"},'
        '{"topic":"applicability","source_ids":["<p-id>"],"text":"<text>"},'
        '{"topic":"limits","source_ids":["<p-id>"],"text":"<text>"}]。'
        "占位符须替换；source_ids从view.policy.sources.rows首列选择，至少一项，不重复。"
        "change解释公告具体调整什么，区别附加税与完整税则；没有旧税率证据不猜增幅或首次纳入。"
        "applicability解释商品、原产地与入境条件；limits说明存档政策不等于现行综合税则，条件和例外未知不等于不存在。"
        "不能把政策解释硬挂在贸易观察编号下。引用存在不意味着文字已核实，全部解释仍需审阅。"
        "interpretations最多六项，每项仅observation_id、kind、text，引用view.evidence.observations.rows中的o编号；"
        "kind仅meaning或hypothesis。沿metric_ids读取同商品、同月指标和来源。watchlist最多三项，每项仅watch_id、"
        "rationale，使用watchlist_catalog。text最多三百五十字，rationale最多二百字。"
        "所有政策说明、贸易解释和观察理由的正文合计最多两千字符。"
        "text和rationale正文不输出阿拉伯数字、百分号、百分之、日期、税号、税率、金额、网址或HTML；具体值由程序展示。"
        "美元指标称进口金额，不称贸易量；不得把份额等同依赖或替代能力，不作因果或价格定论。"
        "unknown/unverified表示尚未核实，不是已核验失败，不自行推断原因。"
        "解释至少一项具体贸易变化及其意义，政策与贸易变化分别解释；不得把先后发生等同因果。"
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]


def parse(raw: str, report: Mapping[str, Any], *, question: str,
          policy_context: Mapping[str, Any],
          request_context: Mapping[str, Any] | None = None,
          enforce_body_budget: bool = True) -> dict[str, Any]:
    _, binding, sources = _input(question, report, policy_context, request_context)
    envelope = canonical_response(raw, stage=PROTOCOL)
    answer = envelope["parsed"]
    fields = {"schema_version", "binding_sha256", "policy_explanations", "interpretations", "watchlist"}
    if not isinstance(answer, dict) or set(answer) != fields or answer["schema_version"] != PROTOCOL:
        raise ValueError("政策解释协议字段不匹配")
    if answer["binding_sha256"] != binding:
        raise ValueError("政策解释与当前问题、证据版本不匹配")
    items = answer["policy_explanations"]
    if not isinstance(items, list) or len(items) != 3:
        raise ValueError("必须解释政策变化、适用范围与局限")
    seen, clean = set(), []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"topic", "source_ids", "text"}:
            raise ValueError("政策解释项字段无效")
        topic, ids, text = item["topic"], item["source_ids"], item["text"]
        if not isinstance(topic, str) or topic not in TOPICS or topic in seen:
            raise ValueError("政策解释主题无效或重复")
        if (not isinstance(ids, list) or not 1 <= len(ids) <= len(sources)
                or any(not isinstance(i, str) or i not in sources for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("政策解释引用不存在、重复或跨类型来源")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 350 or NO_NUMERIC.search(text):
            raise ValueError("政策解释文字无效")
        seen.add(topic)
        clean.append({"topic": topic, "source_ids": [sources[i] for i in ids], "text": text.strip()})
    legacy = trade_parse(json.dumps({"schema_version": "public-brief-explanation-v1",
        "interpretations": answer["interpretations"], "watchlist": answer["watchlist"]}, ensure_ascii=False), report)
    body_chars = (sum(len(item["text"]) for item in clean)
                  + sum(len(item["text"]) for item in legacy["interpretations"])
                  + sum(len(item["rationale"]) for item in legacy["watchlist"]))
    if enforce_body_budget and body_chars > 2000:
        raise ValueError("政策与贸易解释正文合计超过2000字符")
    return {**legacy, "protocol": PROTOCOL, "schema_version": PROTOCOL,
            "raw_sha256": envelope["raw_sha256"], "binding_sha256": binding,
            "policy_explanations": clean, "status": "manual_review_required",
            "boundary": "政策引用和结构已检查；尚未证明陈述被原文支持，不可自动发布。"}
