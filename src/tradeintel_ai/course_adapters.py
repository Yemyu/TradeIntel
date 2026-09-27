"""把课程项目中值得复用的通用模式适配到 TradeIntel。

这里是 TradeIntel 自己的边界层，不直接导入 Downloads 中的课程代码。它只
接收课程模块可能产生的事件/工具参数，并将其转换成带政策、版本和证据
约束的本项目对象。这样可以先替换“接口”，再决定是否替换页面或编排器。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AdapterContractError(ValueError):
    """课程事件/工具请求无法映射到 TradeIntel 契约。"""


@dataclass(frozen=True)
class EvidenceCard:
    source_id: str
    policy_id: str
    data_version: str
    quote: str
    location: str


@dataclass(frozen=True)
class TradeQuery:
    policy_id: str
    data_version: str
    month: str
    hts8: tuple[str, ...]


def adapt_course_source(raw: dict[str, Any]) -> EvidenceCard:
    """把课程 source/chunk 卡片映射成带版本的证据卡片。"""
    required = ("source_id", "policy_id", "data_version", "quote", "location")
    if not isinstance(raw, dict) or any(
        not isinstance(raw.get(key), str) or not raw[key].strip() for key in required
    ):
        raise AdapterContractError("source card must carry source_id/policy_id/data_version/quote/location")
    return EvidenceCard(*(raw[key].strip() for key in required))


def adapt_course_db_tool(raw: dict[str, Any]) -> TradeQuery:
    """只接受固定贸易指标请求；拒绝模型生成的任意 SQL。"""
    if not isinstance(raw, dict) or set(raw) != {"policy_id", "data_version", "month", "hts8"}:
        raise AdapterContractError("trade tool requires the fixed query fields only")
    policy_id, data_version, month, hts8 = (raw[key] for key in ("policy_id", "data_version", "month", "hts8"))
    if not all(isinstance(value, str) and value.strip() for value in (policy_id, data_version, month)):
        raise AdapterContractError("trade query identity fields must be non-empty strings")
    if not isinstance(hts8, list) or not hts8 or any(
        not isinstance(code, str) or len(code) != 8 or not code.isdigit() for code in hts8
    ):
        raise AdapterContractError("trade query requires one or more HTS8 codes")
    return TradeQuery(policy_id.strip(), data_version.strip(), month.strip(), tuple(hts8))


def cache_scope(*, policy_id: str, data_version: str, month: str, question: str) -> tuple[str, str, str, str]:
    """课程语义缓存的安全适配键：不能跨政策、版本、月份复用答案。"""
    return policy_id, data_version, month, " ".join(question.lower().split())


def validate_research_state(state: dict[str, Any]) -> None:
    """研究状态必须有可追溯证据，不能用空 fallback 表示完成。"""
    if not isinstance(state.get("source_index"), list) or not state["source_index"]:
        raise AdapterContractError("research state cannot complete without source_index")
    source_ids = {item.get("source_id") for item in state["source_index"] if isinstance(item, dict)}
    if not source_ids or any(not source_id for source_id in source_ids):
        raise AdapterContractError("research source_index contains an invalid source")
    if state.get("parse_failed"):
        raise AdapterContractError("parse failure must remain needs_review, never completed")
