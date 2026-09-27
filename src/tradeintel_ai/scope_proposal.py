"""Server-owned proposal for the public multi-period session flow.

The proposal step turns a question plus an explicit policy/product card into
an ``analysis-request-v1`` request.  It reads the registered release and
product catalogue, but it does not query trade evidence or mutate a session.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping

from .analysis_request import default_window, request_digest, resolve_query_plan, validate_analysis_request
from .exposure_version_store import ExposureVersionStore
from .policy_cases import resolve_case


COMPARISONS = ["series", "mom", "yoy", "origins"]


def _registered_products(root: Path, case: Any) -> list[dict[str, Any]]:
    path = Path(root) / case.products
    if not path.is_file():
        raise ValueError("政策商品登记表不存在")
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("policy_id") != case.policy_id:
                continue
            code = str(row.get("canonical_hts8") or "").replace(".", "").strip()
            if len(code) != 8 or not code.isdigit():
                raise ValueError("政策商品登记表含无效 HTS8")
            rows.append({
                "hts8": code,
                "name": row.get("product_description_zh") or row.get("product_description") or "",
                "name_en": row.get("product_description") or "",
                "additional_rate_percent": int(row["additional_rate_percent"]),
                "effective_date": row.get("effective_date"),
            })
    if not rows or len({row["hts8"] for row in rows}) != len(rows):
        raise ValueError("政策商品登记表为空或 HTS8 重复")
    return rows


def propose_scope(root: Path, *, original_question: str, policy_id: str,
                  selected_products: list[str] | str = "all",
                  parent_request: Mapping[str, Any] | None = None,
                  request_override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create a read-only, server-resolved multi-period scope proposal."""
    if not isinstance(original_question, str) or not 1 <= len(original_question.strip()) <= 2000:
        raise ValueError("original_question 必须是1至2000字")
    case = resolve_case(policy_id)
    catalogue = _registered_products(root, case)
    by_code = {row["hts8"]: row for row in catalogue}
    if selected_products == "all" or selected_products is None:
        products = [row["hts8"] for row in catalogue]
        selection_reason = "使用政策卡片登记的全部商品"
    elif isinstance(selected_products, list):
        if not selected_products or any(not isinstance(code, str) for code in selected_products):
            raise ValueError("selected_products 必须是非空 HTS8 列表")
        products = list(dict.fromkeys(code.replace(".", "") for code in selected_products))
        selection_reason = "使用用户在政策卡片中明确选择的商品"
    else:
        raise ValueError("selected_products 只能是 all 或 HTS8 列表")
    if any(code not in by_code for code in products):
        raise ValueError("选择的商品不在该政策的登记范围内")
    if parent_request is not None:
        parent = validate_analysis_request(parent_request)
        if parent["policy_id"] != policy_id:
            raise ValueError("追问上下文的政策与当前卡片不一致")
        version = parent["data_version"]
        store = ExposureVersionStore(root, root / case.versions)
        snapshot = store.load_snapshot(version)
        if selected_products == "all" or selected_products is None:
            products = list(parent["products"])
            selection_reason = "沿用已确认请求的商品范围"
        if set(products) - set(parent["products"]):
            raise ValueError("追问商品必须来自已确认的政策卡片范围")
        parent_digest = request_digest(parent)
    else:
        store = ExposureVersionStore(root, root / case.versions)
        version = store.active_version()
        if not version:
            raise ValueError("没有已发布的数据版本；无法提出范围")
        snapshot = store.load_snapshot(version)
        parent_digest = None
    # The proposal may read only a complete published release.  This is a
    # cheap integrity check; confirmation repeats it immediately before any
    # evidence query.
    release = store.release_root(version)
    if _registered_products(release, case) != catalogue:
        raise ValueError("当前商品卡片与已发布版本不一致；请先同步登记范围")
    if store.version_record(version).get("status") not in {"active", "superseded"}:
        raise ValueError("提案只能使用已发布的数据版本")
    if parent_request is not None and parent.get("policy_binding") is not None:
        raise ValueError("公告绑定暂不支持此多期提案入口")
    if snapshot.get("policy_id") != policy_id:
        raise ValueError("发布版本与政策卡片不一致")
    if parent_request is not None:
        # A follow-up may narrow the product set, but it must not silently
        # move the already confirmed window or comparison definitions.
        if request_override is not None:
            candidate = validate_analysis_request(dict(request_override))
            if (candidate["policy_id"] != parent["policy_id"]
                    or candidate["data_version"] != parent["data_version"]
                    or set(candidate["products"]) != set(products)
                    or candidate["comparisons"] != parent["comparisons"]
                    or any(candidate.get(key) != parent.get(key) for key in
                           ("policy_binding", "policy_view", "policy_verified_at", "requested_as_of"))):
                raise ValueError("追问候选只能继承已确认政策、版本并缩小商品范围")
            window = dict(candidate["window"])
            comparisons = list(candidate["comparisons"])
            policy_view = candidate["policy_view"]
            policy_verified_at = candidate.get("policy_verified_at")
            requested_as_of = candidate.get("requested_as_of")
            original_question = candidate["original_question"]
        else:
            window = dict(parent["window"])
            comparisons = list(parent["comparisons"])
            policy_view = parent["policy_view"]
            policy_verified_at = parent.get("policy_verified_at")
            requested_as_of = parent.get("requested_as_of")
    else:
        window = default_window(snapshot, products=products)
        comparisons = COMPARISONS
        policy_view = "archived_event"
        policy_verified_at = None
        requested_as_of = None
    request = validate_analysis_request({
        "schema_version": "analysis-request-v1",
        "original_question": original_question,
        "policy_id": policy_id,
        "policy_binding": None,
        "products": products,
        "window": window,
        "comparisons": comparisons,
        "data_version": version,
        "policy_view": policy_view,
        "policy_verified_at": policy_verified_at,
        "requested_as_of": requested_as_of,
    })
    available: dict[str, dict[str, list[str]]] = {}
    for month, entry in (snapshot.get("months") or {}).items():
        metrics = entry.get("metrics") if isinstance(entry, Mapping) else None
        breakdown = metrics.get("product_breakdown") if isinstance(metrics, Mapping) else []
        available[month] = {"products": [str(row.get("hts8")) for row in breakdown or []
                                        if isinstance(row, Mapping) and row.get("hts8")]}
    cards = [by_code[code] for code in products]
    proposal = {
        "schema_version": "analysis-scope-proposal-v1",
        "status": "proposal_only",
        "confirmation_required": True,
        "query_executed": False,
        "policy_id": policy_id,
        "data_version": version,
        "policy_status": case.status,
        "policy_window": {"start": case.start, "end": case.end},
        "question": original_question,
        "selection": {"products": products, "reason": selection_reason},
        "product_cards": cards,
        "request": request,
        "request_digest": request_digest(request),
        "parent_request_digest": parent_digest,
        "query_plan_preview": resolve_query_plan(request, available=available),
        "message": "范围已由服务器根据登记政策和已发布数据版本提出；确认前不会查询贸易数据。",
    }
    return proposal


__all__ = ["propose_scope"]
