"""Small local web application for the bounded TradeShock AI demonstration.

The page deliberately exposes a narrow, registered case rather than pretending
to be a general trade-policy portal.  Deterministic exposure queries are
available with GET requests.  The model-backed demo is a separate POST route
and is only executed after an explicit button click in the browser.

This module uses the standard library only.  API credentials stay in the
project-local configuration and are never included in HTTP responses or
request logs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlparse

from .local_provider_config import load_config, load_product_config
from .model_adapter import ModelAdapterError
from .policy_exposure_tools import (
    EXPOSURE_END,
    EXPOSURE_START,
    HTS8_PATTERN,
    POLICY_EXPOSURE_ID,
    get_policy_exposure_series,
)
from .policy_exposure_workflow import run_exposure_demo
from .repository import EvidenceRepository, RepositoryError, default_paths
from .research_models import ResearchPlannerModel
from .tools import ToolError
from .course_adapters import AdapterContractError, adapt_course_db_tool
from .exposure_version_store import ExposureVersionStore, VersionStoreError, pin_repository


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8765
DEFAULT_OUTPUT_ROOT_NAME = "tmp/unified-research"
RUN_ID_PATTERN = re.compile(r"^exposure-[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")
CASES = {
    "may-tungsten": {
        "label": "2026 年 5 月 · 单税号",
        "description": "查询 81019910 的当月金额、中国份额和后续调查方向。",
    },
    "june-tungsten": {
        "label": "2026 年 6 月 · 单税号",
        "description": "保留的格式失败案例；可用来观察失败如何被保留。",
    },
    "july-scope": {
        "label": "2026 年 7 月 · 五税号整体",
        "description": "查询登记政策五个 HTS8 的整体金额、中国金额和份额。",
    },
}

POLICY_SOURCE_CARDS = (
    {
        "label": "USTR 公告（2024-12-11）",
        "kind": "政策公告",
        "url": "https://ustr.gov/about-us/policy-offices/press-office/press-releases/2024/december/ustr-increases-tariffs-under-section-301-tungsten-products-wafers-and-polysilicon-concluding",
        "description": "说明四年审查后的关税调整背景。",
    },
    {
        "label": "Federal Register（2024-12-16）",
        "kind": "法律出版",
        "url": "https://www.federalregister.gov/documents/2024/12/16/2024-29462/notice-of-modification-chinas-acts-policies-and-practices-related-to-technology-transfer",
        "description": "登记政策范围、税率与正式出版日期。",
    },
    {
        "label": "CBP 执行指引（2024-12-31）",
        "kind": "执行指引",
        "url": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1",
        "description": "确认五个税号及 2025-01-01 生效安排。",
    },
    {
        "label": "USITC 2026-07 编码变更表",
        "kind": "编码连续性",
        "url": "https://www.usitc.gov/tariff_affairs/documents/list_of_committee_changes_for_july_1_2026-final.pdf",
        "description": "说明 3818000095 拆分为后续统计编码，避免把拆码误当增长。",
    },
)


class WebRequestError(ValueError):
    """A safe validation error returned as HTTP 400."""


SESSION_POST_PATHS = ("/api/session/create", "/api/session/message", "/api/session/proposal",
                      "/api/session/confirm-proposal", "/api/session/request",
                      "/api/session/followup", "/api/session/confirm-request",
                      "/api/session/task/start", "/api/session/task/evidence",
                      "/api/session/task/generate", "/api/session/task/transition",
                      "/api/session/task/explanation/prepare",
                      "/api/session/task/explanation/call",
                      "/api/session/task/explanation/submit",
                      "/api/session/task/explanation/review",
                      "/api/update/check", "/api/announcements/import",
                      "/api/announcements/candidates",
                      "/api/announcements/template", "/api/announcements/submit",
                      "/api/announcements/enable", "/api/announcements/coverage/check",
                      "/api/announcements/statistics/prepare",
                      "/api/announcements/statistics/report",
                      "/api/announcements/linkage/confirm",
                      "/api/announcements/linkage/prepare",
                      "/api/announcements/linkage/report",
                      "/api/model/config", "/api/model/test", "/api/product/scope",
                      "/api/trade/query", "/api/trade/prepare", "/api/trade/report",
                      "/api/trade/explanation/call", "/api/trade/explanation/review")


def _handle_announcement_flow(root: Path, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """K3: candidate template -> human-confirmed fields -> enable -> rebind."""
    from .announcement_flow import (candidate_template, confirm_and_enable,
                                    load_announcement_store, submit_candidates)
    policy_id = str(payload.get("policy_id") or "").strip()
    doc_version = str(payload.get("doc_version") or "").strip()
    if not policy_id:
        raise WebRequestError("policy_id is required")
    if path in ("/api/announcements/template", "/api/announcements/candidates") \
            and not isinstance(payload.get("fields"), list):
        if not doc_version:
            raise WebRequestError("doc_version is required")
        store = load_announcement_store(root, policy_id)
        return {"status": "template", **candidate_template(store, doc_version)}
    if path in ("/api/announcements/submit", "/api/announcements/candidates"):
        fields = payload.get("fields")
        if not isinstance(fields, list) or not fields:
            raise WebRequestError("fields is required")
        return submit_candidates(root, policy_id, doc_version, fields)
    if path == "/api/announcements/enable":
        fields = payload.get("fields")
        if not isinstance(fields, list) or not fields:
            raise WebRequestError("fields is required")
        if not doc_version:
            raise WebRequestError("doc_version is required")
        operator = str(payload.get("operator") or "local-user")
        return confirm_and_enable(root, policy_id, doc_version, fields,
                                  confirmed_by=operator,
                                  expected_candidate_digest=(
                                      str(payload.get("candidate_digest"))
                                      if payload.get("candidate_digest") is not None else None))
    raise WebRequestError("未知公告接口")


def _handle_announcement_coverage(root: Path, policy_id: str,
                                  doc_version: str) -> dict[str, Any]:
    from .announcement_flow import coverage_report
    if not policy_id or not doc_version:
        raise WebRequestError("policy_id 与 doc_version 为必填")
    return coverage_report(root, policy_id, doc_version)


def _handle_announcement_coverage_check(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    from .announcement_flow import check_trade_coverage
    policy_id = str(payload.get("policy_id") or "").strip()
    doc_version = str(payload.get("doc_version") or "").strip()
    month = str(payload.get("month") or "").strip()
    if not policy_id or not doc_version or not month:
        raise WebRequestError("policy_id、doc_version 与 month 为必填")
    # source_case_id is a routing request only; amounts and exact status come
    # from the server-side registered case and read-only query.
    source_case_id = str(payload.get("source_case_id") or
                         "us_301_review2025_tungsten_solar")
    requested_codes = payload.get("requested_codes")
    if requested_codes is not None and not isinstance(requested_codes, list):
        raise WebRequestError("requested_codes 必须是数组")
    return check_trade_coverage(root, policy_id, doc_version, month=month,
                                source_case_id=source_case_id,
                                requested_codes=requested_codes)


def _session_state(root: Path, session_id: str) -> dict[str, Any]:
    from .session_store import load_session
    session = load_session(root, session_id)
    public = {key: value for key, value in session.items() if key != "_loaded_revision"}
    # Catalogs contain official source text and can be large.  The server
    # keeps them in the task snapshot for validation, but the browser only
    # receives the report/evidence summary and explanation status.
    for task in public.get("tasks", {}).values():
        response = task.get("response") if isinstance(task, dict) else None
        if isinstance(response, dict):
            response.pop("catalog", None)
        explanation = task.get("explanation") if isinstance(task, dict) else None
        if isinstance(explanation, dict):
            explanation.pop("raw_text", None)
            explanation.pop("messages", None)
            explanation.pop("host_bindings", None)
        history = task.get("explanation_history") if isinstance(task, dict) else None
        if isinstance(history, list):
            for item in history:
                if isinstance(item, dict):
                    item.pop("raw_text", None)
                    item.pop("messages", None)
                    item.pop("host_bindings", None)
    return public


def _prior_program_context(session: Mapping[str, Any], parent_request: Mapping[str, Any],
                           selected_products: list[str]) -> dict[str, Any]:
    """Build a short server-owned Q1 context for a confirmed product follow-up."""
    from .session_store import request_digest
    parent_digest = request_digest(dict(parent_request))
    task = next((item for item in (session.get("tasks") or {}).values()
                 if isinstance(item, Mapping)
                 and item.get("request_digest") == parent_digest
                 and (item.get("response") or {}).get("kind") == "temporal-report-v1"), None)
    if task is None:
        raise WebRequestError("请先完成上一份程序报告，再进行商品追问")
    response = task.get("response") or {}
    report = response.get("report") or {}
    evidence = report.get("evidence") or {}
    anchor = ((parent_request.get("window") or {}).get("anchor_month"))
    observations = evidence.get("observations") or []
    selected: list[dict[str, str]] = []
    # Prefer current-month levels and comparisons so Q2 receives a useful
    # summary without copying the whole Q1 report into the model input.
    ranked = sorted(observations, key=lambda item: (
        0 if isinstance(item, Mapping) and item.get("scope", {}).get("period") == anchor else 1,
        0 if isinstance(item, Mapping) and item.get("kind") == "comparison" else 1,
        str(item.get("id", "")) if isinstance(item, Mapping) else ""))
    for item in ranked:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            continue
        sentence = str(item.get("fact_sentence") or "").strip()
        if not sentence:
            continue
        selected.append({"observation_id": item["id"], "kind": str(item.get("kind") or ""),
                         "period": str((item.get("scope") or {}).get("period") or ""),
                         "fact_sentence": sentence[:220]})
        if len(selected) >= 8:
            break
    if not selected:
        raise WebRequestError("上一份程序报告没有可供追问的观察摘要")
    return {
        "schema_version": "public-request-context-v1",
        "kind": "prior_program_report",
        "parent_request_digest": parent_digest,
        "parent_data_version": parent_request.get("data_version"),
        "parent_task_id": str(task.get("task_id")),
        "parent_window": dict(parent_request.get("window") or {}),
        "selected_products": list(selected_products),
        "summary": selected,
    }


def _announcement_store_path(root: Path, policy_id: str) -> Path:
    """Compatibility wrapper for callers that imported the old web helper."""
    from .announcement_store import announcement_store_path, AnnouncementStoreError
    try:
        return announcement_store_path(root, policy_id)
    except AnnouncementStoreError as exc:
        raise WebRequestError(str(exc)) from exc


def _announcement_lock(root: Path, policy_id: str):
    """Compatibility wrapper; the shared lock now belongs to the workflow layer."""
    from .announcement_store import announcement_lock
    return announcement_lock(root, policy_id)


def _handle_announcement_import(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Register a NEW announcement as a DISABLED candidate document (J4).

    This is the first step of the separate new-announcement path: the parsed
    text is stored as an unsearchable candidate document; field extraction,
    candidate confirmation, trade coverage and the report rebind stay pending
    until the human confirmation flow (policy_candidates) completes.
    """
    from .policy_documents import build_document, validate_document_store
    policy_id = str(payload.get("policy_id") or "").strip()
    source_id = str(payload.get("source_id") or "").strip()
    text = payload.get("text")
    if not source_id:
        raise WebRequestError("policy_id 与 source_id 为必填")
    if not isinstance(text, str) or len(text.strip()) < 20:
        raise WebRequestError("公告正文过短或缺失；导入的是完整原文而不是标题")
    # K1a: strict allowlist + containment check BEFORE any path is built.
    from .announcement_store import save_announcement_store
    store_path = _announcement_store_path(root, policy_id)
    doc = build_document(
        {"policy_id": policy_id, "data_version": "announcement-candidate",
         "sources": [{"id": source_id, "url": payload.get("url"),
                      "text": text, "document_sha256": payload.get("sha256")}]},
        doc_id=source_id, status="disabled")
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with _announcement_lock(root, policy_id):
        if store_path.is_file():
            store = json.loads(store_path.read_text(encoding="utf-8"))
            existing = {d["doc_version"]: d for d in store["documents"]}
            if doc["doc_version"] in existing:
                # Idempotent import: the identical document is already registered.
                return {"status": "registered_candidate", "doc_version": doc["doc_version"],
                        "policy_id": policy_id, "doc_status": existing[doc["doc_version"]]["status"],
                        "idempotent": True,
                        "source_provenance": (store.get("announcement_imports") or {}).get(
                            doc["doc_version"], {}).get("source_provenance", "unknown"),
                        "next_steps": "逐字段候选确认（policy_candidates）→启用→数据覆盖→报告重绑定；本端点不启用文档。",
                        "boundary": "导入登记≠采纳；候选公告不进入检索与报告，直到人工确认完成。"}
            store["documents"].append(doc)
            validate_document_store(store)
        else:
            store = {"schema_version": "policy-document-store-v1", "policy_id": policy_id,
                     "data_version": None, "documents": [doc], "limitations": [
                         "导入公告保持disabled候选态；未经字段确认与覆盖核对不得启用或检索。"]}
            validate_document_store(store)
        store.setdefault("announcement_imports", {})[doc["doc_version"]] = {
            "source_provenance": "user_supplied_unverified",
            "source_url_verification": "not_checked",
        }
        save_announcement_store(root, policy_id, store)
    return {"status": "registered_candidate", "doc_version": doc["doc_version"],
            "policy_id": policy_id, "doc_status": doc["status"],
            "source_provenance": "user_supplied_unverified",
            "next_steps": "逐字段候选确认（policy_candidates）→启用→数据覆盖→报告重绑定；本端点不启用文档。",
            "boundary": "导入登记≠采纳；候选公告不进入检索与报告，直到人工确认完成。"}


def _program_draft_gate(task: Mapping[str, Any]) -> str | None:
    """Return None when the task may export its A3 program draft, else the reason.

    Review J-acceptance item 2: the confirmation record is compared against
    the CURRENT response on ALL bound fields -- report hash, data_version,
    catalog digest and response kind -- so changing only the metadata also
    invalidates the confirmation.  AI-generated content never passes this
    gate and must go through the item-by-item review service.
    """
    response = task.get("response") or {}
    markdown = response.get("final_markdown") or response.get("a3_markdown")
    if response.get("kind") != "program-report-a3":
        return "AI生成内容不接受客户端状态跳转导出；必须走逐项审阅服务"
    confirmations = [c for c in task.get("confirmations", [])
                     if c.get("confirmation_type") == "program_draft_confirmation"]
    latest = confirmations[-1] if confirmations else None
    if not latest:
        return "程序稿确认缺失或报告已变化；请重新审阅确认"
    if latest.get("report_sha256") != hashlib.sha256((markdown or "").encode("utf-8")).hexdigest():
        return "程序稿确认缺失或报告已变化；请重新审阅确认"
    if latest.get("data_version") != response.get("data_version"):
        return "程序稿确认缺失或报告已变化；请重新审阅确认"
    if latest.get("catalog_sha256") != response.get("catalog_sha256"):
        return "程序稿确认缺失或报告已变化；请重新审阅确认"
    if latest.get("response_kind") != response.get("kind"):
        return "程序稿确认缺失或报告已变化；请重新审阅确认"
    explanation = task.get("explanation") or {}
    if explanation.get("raw_sha256") and explanation.get("status") != "failed":
        review = explanation.get("review") or {}
        if not review.get("eligible_for_export"):
            return "AI解释尚未逐项审阅通过；不能导出AI报告"
        if not response.get("final_markdown"):
            return "AI解释已审阅但最终报告未生成；请重新审阅"
        if response.get("final_markdown_sha256") != hashlib.sha256(
                response["final_markdown"].encode("utf-8")).hexdigest():
            return "最终报告内容已变化；请重新审阅"
    return None


def _temporal_report_core_gate(task: Mapping[str, Any]) -> str | None:
    """Validate the deterministic multi-period report before confirmation."""
    response = task.get("response") or {}
    if response.get("kind") != "temporal-report-v1":
        return "响应类型不是多期确定性报告"
    report = response.get("report")
    markdown = response.get("markdown")
    if not isinstance(report, Mapping) or not isinstance(markdown, str) or not markdown:
        return "多期程序报告内容缺失；请重新生成"
    try:
        from .public_report import render_public_report
        rendered = render_public_report(report)
    except (TypeError, ValueError, KeyError) as exc:
        return f"多期程序报告校验失败；请重新生成（{exc}）"
    if rendered != markdown:
        return "多期程序报告正文已变化；请重新审阅确认"
    if report.get("report_sha256") != response.get("report_sha256"):
        return "多期程序报告摘要已变化；请重新审阅确认"
    from .session_store import request_digest as _request_digest
    try:
        calculated_request_digest = _request_digest(report.get("request") or {})
    except (TypeError, ValueError):
        return "多期程序报告请求绑定无效；请重新生成"
    if report.get("request_digest") != calculated_request_digest:
        # The digest is derived from the canonical request, not from a
        # user-supplied field inside that request.
        return "多期程序报告请求绑定已变化；请重新审阅确认"
    if response.get("request") != report.get("request"):
        return "多期程序报告顶层请求与报告内容不一致；请重新审阅确认"
    report_evidence = report.get("evidence")
    if response.get("evidence") != report_evidence:
        return "多期程序报告顶层证据与报告内容不一致；请重新审阅确认"
    if response.get("data_version") != report.get("data_version") \
            or response.get("data_version") != (report_evidence or {}).get("data_version"):
        return "多期程序报告数据版本绑定已变化；请重新审阅确认"
    if response.get("query_plan") != (report_evidence or {}).get("query_plan"):
        return "多期程序报告查询计划已变化；请重新审阅确认"
    evidence_bytes = json.dumps(report_evidence, ensure_ascii=False,
                                sort_keys=True, separators=(",", ":")).encode("utf-8")
    if response.get("evidence_sha256") != hashlib.sha256(evidence_bytes).hexdigest():
        return "多期程序报告证据摘要已变化；请重新审阅确认"
    return None


def _temporal_draft_gate(task: Mapping[str, Any]) -> str | None:
    """Validate the deterministic multi-period report confirmation.

    ``temporal-report-v1`` is a program-generated report, not an AI answer.
    It therefore has its own confirmation record and does not pass through the
    A3/catalog gate.  The report object, rendered Markdown, evidence digest,
    request digest and bound data version are all checked so a later mutation
    cannot turn a reviewed draft into a different export.
    """
    core_refusal = _temporal_report_core_gate(task)
    if core_refusal:
        return core_refusal
    response = task.get("response") or {}
    report = response["report"]
    markdown = response["markdown"]
    explanation = task.get("explanation") or {}
    export_markdown = markdown
    if explanation.get("raw_sha256"):
        review = explanation.get("review") or {}
        if not review.get("eligible_for_export"):
            return "多期报告的AI解释尚未逐项审阅通过；当前只能导出程序稿"
        if response.get("final_kind") != "temporal-report-v1-with-reviewed-explanation":
            return "AI解释已审阅但合并报告缺失；请重新审阅生成"
        export_markdown = response.get("final_markdown")
        if not isinstance(export_markdown, str) or not export_markdown:
            return "AI解释已审阅但最终报告缺失；请重新审阅生成"
        if response.get("final_markdown_sha256") != hashlib.sha256(
                export_markdown.encode("utf-8")).hexdigest():
            return "最终报告内容已变化；请重新审阅"
        if response.get("final_report_sha256") != review.get("final_report_sha256"):
            return "最终报告摘要与审阅记录不一致；请重新审阅"
        final_report = response.get("final_report")
        try:
            from .public_report import render_public_report
            if (not isinstance(final_report, Mapping)
                    or render_public_report(final_report) != export_markdown
                    or final_report.get("report_sha256") != response.get("final_report_sha256")
                    or final_report.get("request") != report.get("request")
                    or final_report.get("evidence") != report.get("evidence")):
                return "最终报告与确定性证据不一致；请重新审阅"
        except (TypeError, ValueError, KeyError):
            return "最终报告校验失败；请重新审阅"
    confirmations = [c for c in task.get("confirmations", [])
                     if c.get("confirmation_type") == "temporal_draft_confirmation"]
    latest = confirmations[-1] if confirmations else None
    if not latest:
        return "多期程序稿确认缺失；请先审阅确认"
    markdown_sha = hashlib.sha256(export_markdown.encode("utf-8")).hexdigest()
    expected = {
        "report_sha256": response.get("report_sha256"),
        "markdown_sha256": markdown_sha,
        "evidence_sha256": response.get("evidence_sha256"),
        "final_report_sha256": response.get("final_report_sha256"),
        "request_digest": (response.get("evidence") or {}).get("request_digest")
            or report.get("request_digest"),
        "data_version": response.get("data_version"),
        "response_kind": response.get("kind"),
    }
    for key, value in expected.items():
        if latest.get(key) != value:
            return "多期程序稿确认缺失或报告已变化；请重新审阅确认"
    # Package 3 owns AI explanation review.  A raw/unreviewed explanation
    # must never be smuggled into the program-only export path.
    return None


def _draft_gate(task: Mapping[str, Any]) -> str | None:
    """Dispatch the export gate by response kind without mixing protocols."""
    kind = (task.get("response") or {}).get("kind")
    if kind == "temporal-report-v1":
        return _temporal_draft_gate(task)
    return _program_draft_gate(task)


def _handle_session_post(root: Path, path: str, payload: Mapping[str, Any],
                         repository: EvidenceRepository) -> dict[str, Any]:
    """Offline session-flow endpoints (F9/J2/J4): no model is ever called here."""
    from .session_store import (confirm_request, create_session, load_session,
                                record_task_confirmation, request_digest,
                                save_task_explanation,
                                resolve_followup, set_request,
                                start_task, TaskStateConflict, transition_task,
                                save_scope_proposal, load_scope_proposal)
    if path == "/api/session/create":
        return {"status": "created",
                "session": _session_state(root, create_session(root)["session_id"])}
    if path == "/api/session/proposal":
        from .scope_proposal import propose_scope
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise WebRequestError("session_id is required")
        session = load_session(root, session_id)
        policy_id = str(payload.get("policy_id") or "us_301_review2025_tungsten_solar")
        selected = payload.get("selected_products", payload.get("products", "all"))
        proposal = propose_scope(root,
                                 original_question=str(payload.get("original_question") or ""),
                                 policy_id=policy_id,
                                 selected_products=selected,
                                 # A follow-up scope is derived from the
                                 # server-owned confirmed request.  Never
                                 # accept a complete parent request from the
                                 # browser, even if it happens to validate.
                                 parent_request=session.get("current_request"))
        saved = save_scope_proposal(root, session, proposal)
        return saved
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise WebRequestError("session_id is required")
    session = load_session(root, session_id)
    if path == "/api/session/confirm-proposal":
        proposal_id = payload.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id:
            raise WebRequestError("proposal_id is required")
        try:
            proposal = load_scope_proposal(root, session, proposal_id)
        except ValueError as exc:
            raise WebRequestError(str(exc)) from exc
        request = proposal.get("request")
        if not isinstance(request, dict) or request.get("schema_version") != "analysis-request-v1":
            raise WebRequestError("保存的范围提案无效；请重新提出范围")
        # Re-check the immutable release at confirmation time.  The client
        # supplies only the proposal id; it cannot replace products, months,
        # policy or data_version between proposal and confirmation.
        from .analysis_request import validate_analysis_request
        from .policy_cases import resolve_case
        from .exposure_version_store import ExposureVersionStore
        try:
            canonical = validate_analysis_request(request)
            case = resolve_case(canonical["policy_id"])
            store = ExposureVersionStore(root, root / case.versions)
            snapshot = store.load_snapshot(canonical["data_version"])
            record = store.version_record(canonical["data_version"])
            if snapshot.get("policy_id") != canonical["policy_id"]:
                raise ValueError("保存提案的政策与发布快照不一致")
            if record.get("status") not in {"active", "superseded"}:
                raise ValueError("保存提案绑定的数据版本已不再发布")
            store.release_root(canonical["data_version"])
        except (ValueError, VersionStoreError) as exc:
            raise WebRequestError(str(exc)) from exc
        if request_digest(canonical) != proposal.get("request_digest"):
            raise WebRequestError("范围提案摘要已变化；请重新提出范围")
        set_request(root, session, canonical, data_version=canonical["data_version"],
                    request_context=proposal.get("request_context"))
        return {"status": "confirmed", "proposal_id": proposal_id,
                "bound_version": canonical["data_version"],
                "session": _session_state(root, session_id)}
    if path == "/api/session/message":
        role = payload.get("role") or "user"
        from .session_store import append_message
        append_message(root, session, role, str(payload.get("content") or ""))
        return {"status": "appended", "session": _session_state(root, session_id)}
    if path in ("/api/session/request", "/api/session/confirm-request"):
        if path == "/api/session/request":
            request = payload.get("request") or {}
        else:
            request = payload.get("candidate_request") or {}
        policy_id = str(request.get("policy_id") or "")
        from tradeintel_ai.policy_cases import resolve_case
        from tradeintel_ai.exposure_version_store import ExposureVersionStore
        if request.get("schema_version") == "analysis-request-v1":
            # New multi-period requests carry a complete, server-resolved
            # data_version.  They do not enter the legacy announcement
            # binding resolver, whose month-only contract is intentionally
            # unchanged.
            from .analysis_request import validate_analysis_request
            try:
                canonical = validate_analysis_request(request)
                if canonical.get("policy_binding") is not None:
                    raise ValueError("analysis-request-v1 的政策绑定必须由服务器公告流程解析，不能由客户端直接注入")
                case = resolve_case(policy_id)
                store = ExposureVersionStore(root, root / case.versions)
                snapshot = store.load_snapshot(canonical["data_version"])
                if snapshot.get("policy_id") != canonical["policy_id"]:
                    raise ValueError("请求政策与发布快照政策不一致")
                record = store.version_record(canonical["data_version"])
                if record.get("status") not in {"active", "superseded"}:
                    raise ValueError("只能绑定已发布的 active/superseded 数据版本")
                store.release_root(canonical["data_version"])
            except (ValueError, VersionStoreError) as exc:
                raise WebRequestError(str(exc)) from exc
            expected = payload.get("data_version")
            if expected is not None and str(expected) != canonical["data_version"]:
                raise WebRequestError("客户端数据版本期望与请求快照不一致；请重新确认范围")
            set_request(root, session, canonical,
                        policy_version=(canonical.get("policy_binding") or {}).get("doc_version"),
                        data_version=canonical["data_version"],
                        policy_binding=canonical.get("policy_binding"))
            return {"status": "confirmed", "bound_version": canonical["data_version"],
                    "policy_binding": canonical.get("policy_binding"),
                    "session": _session_state(root, session_id)}
        requested_binding = payload.get("policy_binding")
        if requested_binding is not None:
            if not isinstance(requested_binding, dict):
                raise WebRequestError("policy_binding 必须是对象")
            from .announcement_flow import resolve_policy_binding
            try:
                requested_codes = requested_binding.get("requested_codes")
                if requested_codes is None and isinstance(request.get("products"), list):
                    requested_codes = request.get("products")
                binding = resolve_policy_binding(
                    root, policy_id, str(requested_binding.get("doc_version") or ""),
                    requested_binding.get("candidate_digest"),
                    month=str(request.get("month") or ""),
                    requested_codes=requested_codes)
            except ValueError as exc:
                raise WebRequestError(str(exc)) from exc
            # The resolver returns audit metadata (confirmation/status) as
            # well as the binding.  Persist only the narrow binding contract
            # in a session; otherwise an untrusted metadata field could be
            # mistaken for part of the request identity.
            session_binding = {
                key: binding[key] for key in
                ("policy_id", "doc_version", "candidate_digest")
                if key in binding
            }
            if binding.get("data_version") is not None:
                session_binding["data_version"] = binding["data_version"]
            for key in ("coverage_month", "coverage_status", "trade_coverage_digest",
                        "requested_codes", "coverage_scope"):
                if binding.get(key) is not None:
                    session_binding[key] = binding[key]
            set_request(root, session, request,
                        policy_version=binding["doc_version"],
                        data_version=binding.get("data_version"),
                        policy_binding=session_binding)
            return {"status": "confirmed", "bound_version": binding["doc_version"],
                    "policy_binding": session_binding,
                    "session": _session_state(root, session_id)}
        try:
            case = resolve_case(policy_id)
        except ValueError as exc:
            raise WebRequestError("未知政策；请先提交已启用公告的 policy_binding") from exc
        store = ExposureVersionStore(root, root / case.versions)
        active = store.active_version()
        if not active:
            raise WebRequestError("没有已登记的活动数据版本；无法确认范围")
        # Client-supplied versions are EXPECTATIONS only: the server binds the
        # registered active version and refuses a mismatched expectation (J2).
        for client_key, bound in (("data_version", active), ("policy_version", active)):
            expected = payload.get(client_key)
            if expected is not None and str(expected) != bound:
                raise WebRequestError(
                    f"客户端{client_key}期望与服务器登记版本不一致；请刷新后重新确认")
        set_request(root, session, request, policy_version=active, data_version=active)
        return {"status": "confirmed", "bound_version": active,
                "session": _session_state(root, session_id)}
    if path == "/api/session/followup":
        published_last_month = None
        current = session.get("current_request") or {}
        if current.get("schema_version") == "analysis-request-v1":
            # “最新可用” is resolved from the server-pinned release snapshot,
            # never from a client-supplied month.  A missing snapshot produces
            # a clarification rather than silently retaining the old window.
            try:
                from .policy_cases import resolve_case
                from .exposure_version_store import ExposureVersionStore
                case = resolve_case(str(current.get("policy_id") or ""))
                store = ExposureVersionStore(root, root / case.versions)
                version = session.get("data_version") or current.get("data_version")
                snapshot = store.load_snapshot(str(version)) if version else None
                published_last_month = str((snapshot or {}).get("end") or "") or None
            except (ValueError, VersionStoreError):
                published_last_month = None
        else:
            # Legacy single-month requests retain their registered case bound.
            try:
                from .policy_cases import resolve_case
                published_last_month = resolve_case(str(current.get("policy_id") or "")).end
            except ValueError:
                published_last_month = None
        outcome = resolve_followup(session, str(payload.get("text") or ""),
                                   published_last_month=published_last_month)
        selected_products = payload.get("selected_products")
        if (current.get("schema_version") == "analysis-request-v1"
                and selected_products is not None):
            if (not isinstance(selected_products, list) or not selected_products
                    or any(not isinstance(code, str) or not re.fullmatch(r"\d{8}", code)
                           for code in selected_products)):
                raise WebRequestError("selected_products 必须是非空 HTS8 列表")
            selected_products = list(dict.fromkeys(selected_products))
            if set(selected_products) - set(current.get("products") or []):
                raise WebRequestError("所选商品必须来自当前已确认范围")
            explicit_codes = set(re.findall(r"(?<!\d)(\d{8})(?!\d)", str(payload.get("text") or "")))
            if explicit_codes and explicit_codes != set(selected_products):
                outcome["needs_clarification"].append("追问税号与所选商品卡片不一致，请确认商品范围。")
            if not outcome.get("needs_clarification"):
                # Keep parsed time changes and the actual question. Card selection
                # refines the parser result; it must never replace or clear it.
                candidate = dict(outcome["candidate_request"])
                candidate["products"] = selected_products
                candidate["original_question"] = (str(current.get("original_question") or "")
                                                   + "\n追问：" + str(payload.get("text") or "")
                                                   + "\n追问选卡：" + ",".join(selected_products))
                from .analysis_request import validate_analysis_request
                validate_analysis_request(candidate)
                outcome = {"changed": True,
                           "changes": outcome["changes"] + ["products -> " + ",".join(selected_products) + "（页面商品卡片）"],
                           "needs_clarification": [],
                           "candidate_request": candidate,
                           "scope_reconfirm_required": True,
                           "multi_request": None,
                           "confirmation_required": True}
        # For the v1 flow, a changed follow-up becomes the same kind of
        # server-owned scope proposal as the first question.  The browser
        # receives an id, not an editable candidate request.
        if (current.get("schema_version") == "analysis-request-v1"
                and outcome.get("changed") and not outcome.get("needs_clarification")):
            from .scope_proposal import propose_scope
            candidate = outcome.get("candidate_request") or {}
            proposal = propose_scope(
                root,
                original_question=str(candidate.get("original_question") or
                                     current.get("original_question") or ""),
                policy_id=str(current.get("policy_id") or ""),
                selected_products=list(candidate.get("products") or current.get("products") or []),
                parent_request=current,
                request_override=candidate,
            )
            proposal["request_context"] = _prior_program_context(
                session, current, list(candidate.get("products") or current.get("products") or []))
            saved = save_scope_proposal(root, session, proposal)
            outcome = {key: value for key, value in outcome.items()
                       if key != "candidate_request"}
            outcome["proposal"] = saved
        return {"status": "candidate", **outcome}
    if path == "/api/session/task/start":
        outcome = start_task(root, session,
                             model=str(payload.get("model") or "deterministic-evidence-query-v1"),
                             prompt_digest=str(payload.get("prompt_digest") or ""),
                             request=payload.get("request"))
        if outcome["action"] in ("blocked_unknown_outcome",):
            return {"status": outcome["action"], "reason": outcome["reason"],
                    "task_id": outcome["task_id"], "session": _session_state(root, session_id)}
        return {"status": outcome["action"], "reason": outcome.get("reason"),
                "task_id": outcome["task_id"], "session": _session_state(root, session_id)}
    task_id = payload.get("task_id")
    task = next((item for item in session["tasks"].values() if item.get("task_id") == task_id),
                None) if task_id else None
    if task is None:
        raise WebRequestError("task_id is required and must exist")
    if path == "/api/session/task/evidence":
        # K1c: both orders are legal -- "start then confirm" (task in
        # awaiting_confirmation) and "confirm then start" (task in received).
        # In every case the SERVER re-verifies the confirmation digest and
        # the bound version; an unconfirmed or stale task never queries.
        if task["state"] not in ("received", "awaiting_confirmation"):
            raise WebRequestError("任务不在等待确认状态；确认前不执行任何查询")
        request = task.get("request_snapshot") or {}
        if request_digest(request) != task.get("request_digest"):
            raise WebRequestError("任务请求快照与请求摘要不一致；请重新开始任务")
        if session.get("request_digest") != task.get("request_digest"):
            raise WebRequestError("任务请求与会话确认请求不一致；请先确认范围")
        if (session.get("data_version") or None) != (task.get("data_version") or None):
            if task.get("data_version"):
                raise WebRequestError("确认范围后数据版本已变化；请重新确认范围")
        if session.get("policy_binding") != task.get("policy_binding"):
            raise WebRequestError("公告绑定版本已变化；请重新确认范围")
        if (session.get("policy_binding") is not None
                and request.get("schema_version") != "analysis-request-v1"):
            from .announcement_flow import load_announcement_store
            from .announcement_report import build_announcement_session_brief
            binding = session["policy_binding"]
            store = load_announcement_store(root, binding["policy_id"])
            candidate_record = ((store.get("announcement_candidates") or {})
                                .get(binding["doc_version"]) or {})
            from .announcement_flow import load_trade_coverage
            coverage = load_trade_coverage(
                store, binding["doc_version"], binding.get("trade_coverage_digest"))
            candidate = candidate_record.get("candidate")
            if not isinstance(candidate, dict) or not isinstance(coverage, dict):
                raise WebRequestError("公告尚未完成贸易覆盖；请先执行覆盖核对")
            try:
                brief = build_announcement_session_brief(
                    root, request, binding, store=store,
                    candidate=candidate, coverage=coverage)
            except (ValueError, VersionStoreError) as exc:
                raise WebRequestError(str(exc)) from exc
        else:
            if request.get("schema_version") == "analysis-request-v1":
                from .session_brief import build_temporal_session_brief
                brief = build_temporal_session_brief(
                    root, request, data_version=session.get("data_version"))
            else:
                from .session_brief import build_session_brief
                brief = build_session_brief(root, request, data_version=session.get("data_version"))
        if task.get("request_snapshot", {}).get("schema_version") == "analysis-request-v1":
            evidence_payload = {"kind": brief["kind"],
                                "request_digest": brief["evidence"]["request_digest"],
                                "query_plan": brief["query_plan"],
                                "data_version": brief["data_version"],
                                "evidence": brief["evidence"],
                                "report": brief["report"],
                                "report_sha256": brief["report_sha256"],
                                "evidence_sha256": brief["evidence_sha256"]}
        else:
            evidence_payload = {"rows": brief["evidence_rows"],
                                "month": brief["month"],
                                "data_version": brief["data_version"],
                                "catalog_sha256": brief["catalog_sha256"]}
        task = transition_task(root, session, task_id, "evidence_ready",
                               reason="用户已确认范围；按绑定版本执行确定性查询",
                               evidence=evidence_payload)
        return {"status": "evidence_ready", "evidence": task.get("evidence"),
                "bound_version": brief["data_version"],
                "session": _session_state(root, session_id)}
    if path == "/api/session/task/generate":
        if task["state"] != "evidence_ready":
            raise WebRequestError("任务还没有就绪的证据；先生成证据")
        evidence = task.get("evidence") or {}
        bound = evidence.get("data_version") or session.get("data_version")
        transition_task(root, session, task_id, "generation_started",
                        reason="生成前先持久化started状态")
        try:
            if (task.get("policy_binding")
                    and (task.get("request_snapshot") or {}).get("schema_version")
                    != "analysis-request-v1"):
                from .announcement_flow import load_announcement_store
                from .announcement_report import build_announcement_session_brief
                binding = task["policy_binding"]
                store = load_announcement_store(root, binding["policy_id"])
                candidate_record = ((store.get("announcement_candidates") or {})
                                    .get(binding["doc_version"]) or {})
                from .announcement_flow import load_trade_coverage
                coverage = load_trade_coverage(
                    store, binding["doc_version"], binding.get("trade_coverage_digest"))
                candidate = candidate_record.get("candidate")
                if not isinstance(candidate, dict) or not isinstance(coverage, dict):
                    raise WebRequestError("公告覆盖记录缺失；不能生成报告")
                brief = build_announcement_session_brief(
                    root, task.get("request_snapshot") or {}, binding,
                    store=store, candidate=candidate, coverage=coverage)
            else:
                request_snapshot = task.get("request_snapshot") or {}
                if request_snapshot.get("schema_version") == "analysis-request-v1":
                    from .session_brief import build_temporal_session_brief
                    brief = build_temporal_session_brief(root, request_snapshot,
                                                         data_version=bound)
                else:
                    from .session_brief import build_session_brief
                    brief = build_session_brief(root, request_snapshot,
                                                data_version=bound)
        except (ValueError, VersionStoreError, RepositoryError, OSError) as exc:
            # A deterministic build failure is a terminal, persisted outcome.
            # Reload the session so an old in-memory copy cannot overwrite the
            # generation_started state or hide the failure after a refresh.
            try:
                failed_session = load_session(root, session_id)
                transition_task(root, failed_session, task_id, "failed",
                                reason="确定性报告生成失败；已保留失败记录",
                                error=str(exc)[:500])
            except (TaskStateConflict, ValueError, OSError):
                pass
            raise WebRequestError(str(exc)) from exc
        if task.get("request_snapshot", {}).get("schema_version") == "analysis-request-v1":
            if (brief["evidence_sha256"] != evidence.get("evidence_sha256")
                    or brief["report_sha256"] != evidence.get("report_sha256")
                    or brief["evidence"]["request_digest"] != evidence.get("request_digest")):
                transition_task(root, session, task_id, "failed",
                                reason="生成的多期证据与已查看版本不一致；需要重新确认范围",
                                error="temporal evidence mismatch")
                raise WebRequestError("生成的多期报告与已查看的证据版本不一致；请重新确认范围")
            response = {"kind": brief["kind"], "data_version": brief["data_version"],
                        "request": brief["request"], "query_plan": brief["query_plan"],
                        "policy_context": brief["policy_context"],
                        "evidence": brief["evidence"],
                        "evidence_sha256": brief["evidence_sha256"],
                        "report": brief["report"], "report_sha256": brief["report_sha256"],
                        "markdown": brief["markdown"], "boundary": brief["boundary"]}
        else:
            if brief["catalog_sha256"] != evidence.get("catalog_sha256"):
                transition_task(root, session, task_id, "failed",
                                reason="生成的目录与已查看证据不一致；需要重新确认范围",
                                error="catalog mismatch between evidence and report")
                raise WebRequestError("生成的报告与用户已查看的证据版本不一致；请重新确认范围")
            response = {"kind": brief["kind"],
                        "data_version": brief["data_version"],
                        "catalog_sha256": brief["catalog_sha256"],
                        "catalog": brief["catalog"],
                        "question": ((task.get("request_snapshot") or {}).get("original_question")
                                      or brief.get("question")),
                        "a3_markdown": brief["a3_markdown"],
                        "boundary": brief["boundary"]}
        task = transition_task(root, session, task_id, "response_saved",
                               response=response,
                               reason="确定性程序报告生成完成（无模型）")
        task = transition_task(root, session, task_id, "needs_review",
                               reason="程序报告仍需人工审阅")
        return {"status": "needs_review", "task_id": task_id,
                "data_version": brief["data_version"],
                "response_boundary": brief["boundary"],
                "session": _session_state(root, session_id)}
    if path.startswith("/api/session/task/explanation/"):
        # Attach the provider-neutral explanation contract to the persisted
        # A3 or temporal response.  The same parser is used by a future API adapter and
        # by the user's Luna chat simulation; this route itself never calls a
        # provider or creates a network client.
        temporal_explanation = (task.get("response") or {}).get("kind") == "temporal-report-v1"
        if not temporal_explanation and (task.get("response") or {}).get("kind") != "program-report-a3":
            raise WebRequestError("当前响应类型不支持解释协议")
        from .session_explanation import (load_public_snapshot, load_snapshot,
                                          prepare, prepare_public, render_public_reviewed,
                                          render_reviewed, review_public_result,
                                          review_result, submit, submit_public)
        if task.get("state") not in ("response_saved", "needs_review"):
            raise WebRequestError("请先生成并保存确定性程序报告")
        if path.endswith("/prepare"):
            existing = task.get("explanation") or {}
            if existing.get("raw_sha256") or existing.get("review"):
                raise WebRequestError("本任务已经有解释回答或审阅记录；请创建新的任务后再生成")
            mode = str(payload.get("mode") or "trade")
            if mode not in {"trade", "policy"}:
                raise WebRequestError("解释模式只能是trade或policy")
            result = prepare_public(root, session_id, task_id, task, mode=mode) if temporal_explanation \
                else prepare(root, session_id, task_id, task)
            save_task_explanation(root, session, task_id, result)
            # The legacy A3 contract exposes a fact-catalog digest and host
            # bindings; the public multi-period contract intentionally exposes
            # evidence/report digests instead.  Do not index the A3-only keys
            # for a temporal task: doing so made the newly connected public
            # explanation route fail before it could return its request.
            prepared = {"status": result["status"], "task_id": task_id,
                        "protocol": result["protocol"],
                        "mode": result.get("mode", "trade"),
                        "snapshot_sha256": result["snapshot_sha256"],
                        "messages": result["messages"],
                        "session": _session_state(root, session_id)}
            if temporal_explanation:
                prepared.update({"report_sha256": result["report_sha256"],
                                 "evidence_sha256": result["evidence_sha256"],
                                 "request_digest": result["request_digest"],
                                 "data_version": result["data_version"]})
            else:
                prepared.update({"catalog_sha256": result["catalog_sha256"],
                                 "host_bindings": result["host_bindings"]})
            return prepared
        current = task.get("explanation")
        if not isinstance(current, dict):
            raise WebRequestError("请先准备解释输入")
        if path.endswith("/call"):
            if set(payload) != {"session_id", "task_id"}:
                raise WebRequestError("模型调用只接受会话和任务编号")
            if current.get("status") != "ready_for_provider" or current.get("raw_sha256"):
                raise WebRequestError("本任务的模型调用已开始或已有回答；不会重复收费")
            from .model_adapter import OpenAICompatibleModel
            from .local_provider_config import product_request_params
            config = load_product_config()
            if not config.api_key:
                raise WebRequestError("本机尚未配置模型密钥")
            # This persisted revision is the one-call claim. A second browser
            # request with a stale revision loses under the session lock.
            claim = {**current, "status": "provider_call_started",
                     "channel": "api", "model": config.model}
            try:
                save_task_explanation(root, session, task_id, claim)
            except TaskStateConflict as exc:
                raise WebRequestError(str(exc)) from exc
            claimed_task = next(item for item in session["tasks"].values()
                                if item.get("task_id") == task_id)
            claimed = dict(claimed_task.get("explanation") or claim)
            try:
                answer = OpenAICompatibleModel(config, system_prompt="",
                                               request_params=product_request_params()).complete(
                    messages=claimed["messages"], tools=[])
            except ModelAdapterError as exc:
                http_status = exc.details.get("http_status")
                if http_status is None:
                    match = re.search(r"HTTP (\d{3})", str(exc))
                    http_status = int(match.group(1)) if match else None
                rejected = isinstance(http_status, int) and 400 <= http_status < 500
                save_task_explanation(root, session, task_id,
                                      {**claimed, "status": "failed" if rejected else "unknown_outcome",
                                       "error": str(exc)[:300],
                                       "error_details": {key: value for key, value in exc.details.items()
                                                         if key in {"http_status", "code", "param"}}})
                if http_status in {400, 422}:
                    message = "模型请求参数被拒绝；请核对模型 ID 和推理设置。本次未得到回答。"
                elif http_status in {401, 403}:
                    message = "模型凭证或权限未通过验证；请在工作台更新配置后提出新问题"
                elif http_status == 404:
                    message = "模型 ID 或接口不存在；请在模型设置中核对。"
                elif http_status == 429:
                    message = "模型服务限流或额度受限；请核对服务商记录。"
                else:
                    message = f"模型请求结果未知：{exc}。本任务不会自动重试"
                raise WebRequestError(message) from exc
            raw = answer.text
            if not isinstance(raw, str) or not raw.strip():
                save_task_explanation(root, session, task_id,
                                      {**claimed, "status": "failed", "error": "模型没有返回正文"})
                raise WebRequestError("模型没有返回正文；请查看已保存的任务状态")
            raw_saved = {**claimed, "status": "raw_saved", "raw_text": raw,
                         "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                         "usage": answer.metadata.get("usage", {})}
            save_task_explanation(root, session, task_id, raw_saved)
            raw_saved = dict(next(item for item in session["tasks"].values()
                                  if item.get("task_id") == task_id)["explanation"])
            try:
                result = (submit_public(root, session_id, task_id, raw_saved, raw,
                                        channel="api", model=config.model)
                          if temporal_explanation else
                          submit(root, session_id, task_id, raw_saved, raw,
                                 channel="api", model=config.model))
            except ValueError as exc:
                save_task_explanation(root, session, task_id,
                                      {**raw_saved, "status": "failed", "error": str(exc)[:500]})
                return {"status": "failed", "message": str(exc)[:500],
                        "task_id": task_id, "session": _session_state(root, session_id)}
            save_task_explanation(root, session, task_id, result)
            return {"status": result["status"], "task_id": task_id,
                    "model": config.model, "session": _session_state(root, session_id)}
        if path.endswith("/submit"):
            if current.get("raw_sha256"):
                # One task/run accepts one provider answer.  A second answer
                # must use an explicit new task so the first raw response and
                # its failure/review history cannot be silently replaced.
                raise WebRequestError("本任务已有原始解释回答；请创建新任务后再重试")
            raw = payload.get("raw_text")
            if not isinstance(raw, str):
                answer = payload.get("answer")
                if not isinstance(answer, dict):
                    raise WebRequestError("raw_text 或 answer 必须存在")
                raw = json.dumps(answer, ensure_ascii=False, separators=(",", ":"))
            channel = str(payload.get("channel") or "chat_simulation")
            if channel == "api":
                raise WebRequestError("API来源只能由服务端provider适配器写入，客户端不能自报")
            if channel not in {"chat_simulation", "stub"}:
                raise WebRequestError("开发解释来源只能是chat_simulation或stub")
            model = str(payload.get("model") or "Luna最高")[:120]
            # Preserve the exact provider text before parsing.  A malformed
            # answer must remain auditable and must never be mistaken for a
            # second chance to call the provider.
            raw_saved = {**current, "status": "raw_saved", "channel": channel,
                         "model": model,
                         "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                         "raw_text": raw, "parsed": None, "validation": None,
                         "flags": [], "review": None}
            saved_task = save_task_explanation(root, session, task_id, raw_saved)
            raw_saved = dict(saved_task.get("explanation") or raw_saved)
            try:
                result = (submit_public(root, session_id, task_id, raw_saved, raw,
                                        channel=channel, model=model)
                          if temporal_explanation else
                          submit(root, session_id, task_id, raw_saved, raw,
                                 channel=channel, model=model))
            except ValueError as exc:
                failed = {**raw_saved, "status": "failed",
                          "error": str(exc)[:500]}
                save_task_explanation(root, session, task_id, failed)
                raise WebRequestError(str(exc)) from exc
            save_task_explanation(root, session, task_id, result)
            return {"status": result["status"], "task_id": task_id,
                    "raw_sha256": result["raw_sha256"], "flags": result.get("flags", []),
                    "session": _session_state(root, session_id)}
        if path.endswith("/review"):
            try:
                reviewer = str(payload.get("reviewer") or "local-user")
                if temporal_explanation:
                    review = review_public_result(current, payload, reviewer=reviewer)
                    if review.get("eligible_for_export"):
                        snapshot = load_public_snapshot(root, session_id, task_id, current)
                        rendered = render_public_reviewed(current, snapshot, review)
                        review.update({"rendered_markdown": rendered["markdown"],
                                       "final_report": rendered["report"],
                                       "final_report_sha256": rendered["report_sha256"]})
                else:
                    review = review_result(current, payload, reviewer=reviewer)
                    if review.get("eligible_for_export"):
                        snapshot = load_snapshot(root, session_id, task_id, current)
                        review["rendered_markdown"] = render_reviewed(current, snapshot, review)
                updated = {**current,
                           "status": "reviewed" if review.get("eligible_for_export") else "needs_review",
                           "review": review}
            except ValueError as exc:
                raise WebRequestError(str(exc)) from exc
            save_task_explanation(root, session, task_id, updated)
            return {"status": updated["status"], "task_id": task_id,
                    "eligible_for_export": review["eligible_for_export"],
                    "session": _session_state(root, session_id)}
        raise WebRequestError("未知解释接口")
    if path == "/api/session/task/transition":
        new_state = str(payload.get("state") or "")
        # Review J4: ordinary clients may only confirm review outcomes; the
        # internal generation/evidence states are written by the system only.
        if new_state not in ("reviewed", "exportable"):
            raise WebRequestError("普通客户端只能确认审阅结果；内部状态由系统写入")
        if new_state == "reviewed":
            explanation = task.get("explanation") or {}
            if (explanation.get("raw_sha256") and explanation.get("status") != "failed"
                    and not explanation.get("review", {}).get("eligible_for_export")):
                raise WebRequestError("AI解释尚未逐项审阅通过；不能确认整份报告")
            if (task.get("response") or {}).get("kind") == "temporal-report-v1":
                refusal = _temporal_report_core_gate(task)
                if refusal:
                    raise WebRequestError(refusal)
        if new_state == "exportable":
            # Do not allow a direct needs_review→exportable transition, or a
            # later review revision, to leave an exportable task whose current
            # report no longer satisfies the content-bound gate.
            refusal = _draft_gate(task)
            if refusal:
                raise WebRequestError(refusal)
        try:
            task = transition_task(root, session, task_id, new_state,
                                   reason=str(payload.get("reason") or "用户操作"))
        except TaskStateConflict as exc:
            return {"status": "state_conflict", "message": str(exc)}
        if new_state == "reviewed":
            response = task.get("response") or {}
            if response.get("kind") == "temporal-report-v1":
                explanation = task.get("explanation") or {}
                markdown = (response.get("final_markdown")
                            if explanation.get("review", {}).get("eligible_for_export")
                            else response.get("markdown")) or ""
                record_task_confirmation(
                    root, session, task_id,
                    confirmation_type="temporal_draft_confirmation",
                    payload={"report_sha256": response.get("report_sha256"),
                             "markdown_sha256": hashlib.sha256(
                                 markdown.encode("utf-8")).hexdigest(),
                             "evidence_sha256": response.get("evidence_sha256"),
                             "final_report_sha256": response.get("final_report_sha256"),
                             "request_digest": (response.get("evidence") or {}).get(
                                 "request_digest"),
                             "data_version": response.get("data_version"),
                             "response_kind": response.get("kind"),
                             "operator": str(payload.get("operator") or "local-user"),
                             "decision": "accept"})
            else:
                # A3 program-draft confirmation: binds the exact report
                # content, version and operator; a changed report invalidates
                # it.  AI explanations have their own item-by-item gate.
                markdown = response.get("final_markdown") or response.get("a3_markdown") or ""
                record_task_confirmation(root, session, task_id,
                                         confirmation_type="program_draft_confirmation",
                                         payload={"report_sha256": hashlib.sha256(
                                             markdown.encode("utf-8")).hexdigest(),
                                             "data_version": response.get("data_version"),
                                             "catalog_sha256": response.get("catalog_sha256"),
                                             "response_kind": response.get("kind"),
                                             "operator": str(payload.get("operator") or "local-user"),
                                             "decision": "accept"})
                if task.get("explanation", {}).get("review", {}).get("eligible_for_export"):
                    record_task_confirmation(root, session, task_id,
                                             confirmation_type="ai_explanation_confirmation",
                                             payload={"raw_sha256": task["explanation"].get("raw_sha256"),
                                                      "final_report_sha256": hashlib.sha256(
                                                          markdown.encode("utf-8")).hexdigest(),
                                                      "reviewer": task["explanation"]["review"].get("reviewer"),
                                                      "decision": "accept"})
        return {"status": new_state, "task_id": task_id,
                "session": _session_state(root, session_id)}
    raise WebRequestError("未知会话接口")


class DemoBusyError(RuntimeError):
    """The same model-backed demo is already running."""


def _registered_case_products(repository: EvidenceRepository, case: Any) -> set[str]:
    """Read the exact HTS8 set belonging to the selected policy case.

    ``EvidenceRepository.policy_products`` predates multi-case version roots and
    points at the original Section 301 table.  The adapter must use the case's
    own registered product file, otherwise a pinned 2025 case can be mistaken
    for a missing or legacy dataset.
    """

    products_path = repository.paths.root / case.products
    if not products_path.is_file():
        raise RepositoryError("登记政策商品文件不存在")
    with products_path.open(newline="", encoding="utf-8") as handle:
        products = {
            row.get("canonical_hts8", "").replace(".", "").strip()
            for row in csv.DictReader(handle)
            if row.get("policy_id", "").strip() == case.policy_id
        }
    if not products or any(len(code) != 8 or not code.isdigit() for code in products):
        raise RepositoryError("登记政策商品文件无有效HTS8")
    return products


def _month_label(key: tuple[int, int]) -> str:
    return f"{key[0]:04d}-{key[1]:02d}"


def _configured_root(root: Path | None = None) -> Path:
    return (root or default_paths().root).resolve()


def _query_one(query: Mapping[str, list[str]], name: str, default: str = "") -> str:
    values = query.get(name, [])
    if len(values) > 1:
        raise WebRequestError(f"参数 {name} 只能出现一次")
    return values[0].strip() if values else default


def validate_exposure_params(
    query: Mapping[str, list[str]], *, root: Path | None = None
) -> dict[str, str | None]:
    """Validate browser query parameters without broadening the registered scope."""

    origin = _query_one(query, "origin", "China")
    if origin not in {"China", "other_origins", "all_origins"}:
        raise WebRequestError("origin 只能是 China、other_origins 或 all_origins")
    start = _query_one(query, "start", _month_label(EXPOSURE_START))
    end = _query_one(query, "end", _month_label(EXPOSURE_END))
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", start) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", end):
        raise WebRequestError("start 和 end 必须使用 YYYY-MM 格式")
    start_key = (int(start[:4]), int(start[5:]))
    end_key = (int(end[:4]), int(end[5:]))
    if not 1 <= start_key[1] <= 12 or not 1 <= end_key[1] <= 12:
        raise WebRequestError("月份必须位于 01 至 12")
    if start_key < EXPOSURE_START or end_key > EXPOSURE_END:
        raise WebRequestError(
            f"当前页面只支持已验证窗口 {_month_label(EXPOSURE_START)} 至 {_month_label(EXPOSURE_END)}"
        )
    if start_key > end_key:
        raise WebRequestError("start 不能晚于 end")
    hts8 = _query_one(query, "hts8", "") or None
    if hts8 is not None:
        hts8 = hts8.replace(".", "")
        if not HTS8_PATTERN.fullmatch(hts8):
            raise WebRequestError("hts8 必须是八位数字税号")
        # The function below is the source of truth for membership.  This
        # local check gives the page a clear error before reading monthly data.
        products_path = _configured_root(root) / "data/processed/policy/section301_review2025_products.csv"
        if products_path.exists():
            with products_path.open(newline="", encoding="utf-8") as handle:
                registered = {
                    row.get("canonical_hts8", "").replace(".", "").strip()
                    for row in csv.DictReader(handle)
                    if row.get("policy_id", "").strip() == POLICY_EXPOSURE_ID
                }
            if hts8 not in registered:
                raise WebRequestError("hts8 不在当前登记政策的五个税号中")
    return {"origin": origin, "start": start, "end": end, "hts8": hts8}


def _safe_error(exc: Exception) -> str:
    """Return a useful but non-sensitive message for an HTTP response."""

    if isinstance(exc, (WebRequestError, ToolError, RepositoryError, ModelAdapterError, ValueError)):
        message = str(exc).strip()
        # Paths and provider response bodies are not helpful in a browser and
        # can reveal local layout, so keep only the first safe sentence.
        if "api_key" in message.lower() or "secret" in message.lower():
            return "本地模型配置不完整；密钥只应保存在项目 .local 配置中。"
        return message[:300] or "请求无法完成"
    return "服务执行失败；本次运行记录已保留在本地，未生成成功报告。"


def _decode_json_object(raw: bytes) -> dict[str, Any]:
    """Decode the tiny POST contract and reject duplicate top-level keys."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise WebRequestError("请求对象不能包含重复字段")
            result[key] = value
        return result

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebRequestError("请求体必须是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise WebRequestError("请求必须是 JSON 对象")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryError("登记政策元数据无法读取") from exc
    if not isinstance(value, dict):
        raise RepositoryError("登记政策元数据必须是对象")
    return value


def policy_payload(repository: EvidenceRepository | None = None) -> dict[str, Any]:
    """Build a small public-safe description of the registered policy."""

    repository = repository or EvidenceRepository()
    repository = pin_repository(repository)
    root = repository.paths.root
    event_path = root / "data/processed/policy/section301_review2025_event.csv"
    products_path = root / "data/processed/policy/section301_review2025_products.csv"
    manifest_path = root / "data/processed/policy_exposure/manifest.json"
    correction_path = manifest_path.parent / "policy_metadata_corrections.json"
    if not event_path.exists() or not products_path.exists() or not manifest_path.exists():
        raise RepositoryError("登记政策资源不完整")
    with event_path.open(newline="", encoding="utf-8") as handle:
        events = list(csv.DictReader(handle))
    event = next((row for row in events if row.get("policy_id") == POLICY_EXPOSURE_ID), None)
    if event is None:
        raise RepositoryError("登记政策事件不存在")
    with products_path.open(newline="", encoding="utf-8") as handle:
        products = [
            row for row in csv.DictReader(handle)
            if row.get("policy_id", "").strip() == POLICY_EXPOSURE_ID
        ]
    correction = _read_json(correction_path) if correction_path.exists() else {}
    dates = correction.get("dates") if isinstance(correction.get("dates"), dict) else {
        "announcement_date": event.get("announcement_date", ""),
        "federal_register_publication_date": event.get("announcement_date", ""),
        "cbp_guidance_publication_date": "",
        "effective_date": event.get("effective_date", ""),
    }
    correction_products = correction.get("products", {})
    public_products: list[dict[str, Any]] = []
    for row in sorted(products, key=lambda item: item.get("canonical_hts8", "")):
        code = row.get("canonical_hts8", "").replace(".", "").strip()
        revised = correction_products.get(code, {}) if isinstance(correction_products, dict) else {}
        public_products.append({
            "hts8": code,
            "description_zh": revised.get("product_description_zh", row.get("product_description_zh", "")),
            "description": revised.get("product_description", row.get("product_description", "")),
            "additional_rate_percent": row.get("additional_rate_percent", ""),
            "effective_date": row.get("effective_date", ""),
        })
    manifest = _read_json(manifest_path)
    months = manifest.get("months", [])
    snapshot = getattr(repository, 'exposure_snapshot', None)
    if snapshot:
        months = [m for m in months if f"{int(m['year']):04d}-{int(m['month']):02d}" in snapshot['months']]
    manifest_labels = sorted(
        f"{int(item['year']):04d}-{int(item['month']):02d}"
        for item in months
        if isinstance(item, dict) and "year" in item and "month" in item
    )
    window_start = manifest_labels[0] if manifest_labels else _month_label(EXPOSURE_START)
    window_end = manifest_labels[-1] if manifest_labels else _month_label(EXPOSURE_END)
    return {
        "policy_id": POLICY_EXPOSURE_ID,
        "data_version": getattr(repository, 'exposure_version', None),
        "policy_name": event.get("policy_name", ""),
        "target_origin": event.get("target_origin", ""),
        "dates": dates,
        "scope_note": event.get("scope_note", ""),
        "products": public_products,
        "data_window": {
            "start": window_start,
            "end": window_end,
            "months": len(months),
            "raw_archives_retained": bool(manifest.get("raw_archive_retention")),
        },
        "sources": list(POLICY_SOURCE_CARDS),
        "limitations": [
            "页面只覆盖登记政策的五个精确 HTS8，不是完整现行税则。",
            "金额是美国消费进口的描述性暴露，不是损失、出口依赖或政策因果效果。",
            "统计窗口截至 2026-07；页面不会把尚未发布月份补成零。",
        ],
    }


def health_payload() -> dict[str, Any]:
    """Expose model readiness without exposing endpoint details or keys."""

    try:
        config = load_config()
    except Exception as exc:  # configuration errors are user-facing status, not crashes
        return {
            "status": "not_configured",
            "model": None,
            "api_key_configured": False,
            "message": _safe_error(exc),
        }
    return {
        "status": "ready" if bool(config.api_key) else "missing_api_key",
        "model": config.model,
        "api_key_configured": bool(config.api_key),
        "message": "真实模型演示可在点击后运行。" if config.api_key else "未配置本地模型密钥；确定性查询仍可使用。",
    }


def update_payload(root: Path | None = None) -> dict[str, Any]:
    """Return the local version pointer and latest accepted difference."""

    project_root = _configured_root(root)
    try:
        store = ExposureVersionStore(project_root)
        payload = store.status()
        if payload['active_version']:
            store.release_root(payload['active_version'])
        payload['release_verified'] = bool(payload['active_version'])
        public_fields = (
            "version",
            "status",
            "before_version",
            "requires_review",
            "ready_for_activation",
            "created_at_utc",
            "activated_at_utc",
            "difference",
        )

        def public_record(record: Any) -> dict[str, Any] | None:
            if not isinstance(record, Mapping):
                return None
            return {key: record[key] for key in public_fields if key in record}

        payload["active"] = public_record(payload.get("active"))
        public_candidates: list[dict[str, Any]] = []
        for record in payload.get("candidates", []):
            safe_record = public_record(record)
            if safe_record is not None:
                public_candidates.append(safe_record)
        payload["candidates"] = public_candidates
        return payload
    except VersionStoreError as exc:
        return {"status": "error", "message": str(exc)}


def version_bound_exposure(repository: EvidenceRepository, **params: Any) -> dict[str, Any]:
    """Read a single verified release, even if the active pointer changes."""
    repository = pin_repository(repository)
    result = get_policy_exposure_series(repository=repository, **params)
    pin_repository(repository)
    result['data_version'] = getattr(repository, 'exposure_version', None)
    result['version_binding'] = 'release_copy' if result['data_version'] else 'unregistered'
    return result


def safe_report_path(output_root: Path, run_id: str) -> Path:
    """Resolve only a generated report, never an arbitrary browser path."""

    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise WebRequestError("运行编号格式无效")
    root = output_root.resolve()
    report = (root / run_id / "report.zh-CN.md").resolve()
    try:
        report.relative_to(root)
    except ValueError as exc:
        raise WebRequestError("报告路径不在本地运行目录内") from exc
    if not report.is_file():
        raise FileNotFoundError("报告尚未生成或运行失败")
    return report


class DemoCoordinator:
    """Prevent duplicate same-case model calls while allowing other requests."""

    def __init__(self, *, structured_model_factory=None) -> None:
        self._structured_model_factory = structured_model_factory
        self._lock = threading.Lock()
        self._running: set[str] = set()
        # Natural-language v2 previews are deliberately kept in this local
        # process.  A token is single-use and never acts as a remote auth
        # credential; restarting the local server invalidates it.
        from .natural_v2 import NaturalV2Session
        self._natural_v2 = NaturalV2Session()

    def natural_preview(self, question, *, repository, output_root):
        """Parse one natural-language v2 request, without executing it."""
        from dataclasses import replace
        from .research_models import JsonResearchModel
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise WebRequestError('问题需为1至2000字')
        with self._lock:
            if 'business-question' in self._running:
                raise DemoBusyError('研究任务正在处理，请等待完成')
            self._running.add('business-question')
        try:
            from .natural_v2 import scope_clarification
            if scope_clarification(question):
                # A host-only clarification must not require credentials or
                # instantiate a provider. None cannot accidentally call an API.
                return self._natural_v2.preview(
                    question, None, repository=repository,
                    audit_directory=output_root / ('preview-' + uuid.uuid4().hex))
            config = replace(load_config(), timeout_seconds=180.0, temperature=0.0)
            if not config.api_key:
                raise ModelAdapterError('未配置本地模型密钥')
            class Once(JsonResearchModel):
                max_output_tokens = 1536
                calls = 0
                def complete(self, **kwargs):
                    if self.calls:
                        raise ModelAdapterError('单次任务解析预算已用尽')
                    self.calls += 1
                    return super().complete(**kwargs)
            result = self._natural_v2.preview(
                question, Once(config), repository=repository,
                audit_directory=output_root / ('preview-' + uuid.uuid4().hex),
                secret=config.api_key,
            )
            # Keep the public result free of configuration and output paths;
            # the token is only meaningful to this coordinator instance.
            return result
        finally:
            with self._lock:
                self._running.discard('business-question')

    def natural_confirm(self, token, *, repository, output_root):
        """Consume a v2 token, then pass its immutable request to T1."""
        result = self._natural_v2.consume(token, repository=repository)
        if result.get('status') != 'confirmed':
            return result
        request = {**result['request'], 'task':'monthly_exposure'}
        executed = self.structured(
            request, repository=result['repository'], output_root=output_root,
            original_question=result['original_question'], planning_audit=result['planning_audit'],
            month_resolution=result['month_resolution']
        )
        return {**executed, 'confirmation_scope': 'local_single_user_process',
                'confirmed_request': request}

    def structured(self, task, *, repository, output_root, original_question=None, planning_audit=None, month_resolution=None):
        from .structured_task import compile_task
        from .policy_cases import resolve_case
        from .business_workflow import run_business_question
        from .research_models import JsonResearchModel
        from dataclasses import replace
        try:
            question, selected_plan = compile_task(task)
        except (ValueError, TypeError) as exc:
            raise WebRequestError('结构化任务参数无效') from exc
        case = resolve_case(task['policy_id'], require_enabled=False)
        if case.status != 'enabled':
            return {'status':'not_available','model_calls':0,'policy_id':case.policy_id,
                    'message':'此案例尚未开放在线研究。可先查看固定真实结果；没有调用模型。'}
        if not case.start <= task['month'] <= case.end:
            raise WebRequestError('月份超出登记数据窗口')
        # Validate the published copy before loading credentials or requesting AI.
        repo = pin_repository(repository, policy_id=case.policy_id)
        snapshot = getattr(repo,'exposure_snapshot',None)
        if not snapshot or not snapshot['start'] <= task['month'] <= snapshot['end']:
            raise WebRequestError('月份不在已发布数据窗口内')
        # The course-style database tool is adapted as a fixed, version-bound
        # request. It is a preflight contract only: the actual read remains in
        # TradeIntel's existing deterministic workflow and repository.
        requested_products = _registered_case_products(repo, case)
        if selected_plan.get('hts8'):
            requested_products = {selected_plan['hts8']}
        try:
            adapter_query = adapt_course_db_tool({
                'policy_id': case.policy_id,
                'data_version': getattr(repo, 'exposure_version', None),
                'month': task['month'],
                'hts8': sorted(requested_products),
            })
        except AdapterContractError as exc:
            raise WebRequestError('课程工具适配校验未通过；未调用模型') from exc
        with self._lock:
            if 'business-question' in self._running:
                raise DemoBusyError('研究任务正在处理，请等待完成')
            self._running.add('business-question')
        try:
            config = replace(load_config(),timeout_seconds=180.0,temperature=0.0)
            if not config.api_key: raise ModelAdapterError('未配置本地模型密钥')
            class Once(JsonResearchModel):
                max_output_tokens=3072
                calls=0
                def complete(self, **kwargs):
                    if self.calls: raise ModelAdapterError('单次解释预算已用尽')
                    self.calls+=1
                    return super().complete(**kwargs)
            run_id='exposure-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
            selected_model = (self._structured_model_factory(config, task)
                              if self._structured_model_factory else Once(config))
            result=run_business_question(selected_model,question,output_root/run_id,
                repository=repo,secret=config.api_key,policy_id=case.policy_id,
                interpretation_mode=True,structured_task=task,original_question=original_question,
                planning_audit=planning_audit, month_resolution=month_resolution)
            from .interpretation_review_store import FILES
            from .research_data_link import research_data_link
            review_available = result.get('status') == 'interpretation_needs_review' and all(
                (output_root/run_id/name).is_file() for name in FILES)
            return {**result,'run_id':run_id,
                'course_adapter': {
                    'status': 'validated',
                    'tool': 'trade_metrics',
                    'policy_id': adapter_query.policy_id,
                    'data_version': adapter_query.data_version,
                    'month': adapter_query.month,
                    'hts8': list(adapter_query.hts8),
                },
                'data_report':research_data_link(getattr(getattr(repo,'exposure_store',None),'root',repository.paths.root),output_root/run_id),
                'review_url':f'/review/interpretation?run_id={run_id}' if review_available else None,
                'artifacts':[
                {'label':label,'url':f'/api/research-artifact/{run_id}/{name}'}
                for name,label in [('source-packet.zh-CN.md','程序来源资料'),
                                   ('interpretation-pending.zh-CN.md','AI待审阅附件')]
                if (output_root/run_id/name).is_file()]}
        finally:
            with self._lock: self._running.discard('business-question')

    def ask(self, question, *, repository, output_root, policy_id=None):
        from .business_workflow import run_business_question
        from .business_case_selection import select_business_case
        from dataclasses import replace
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise WebRequestError('问题需为1至2000字')
        with self._lock:
            if 'business-question' in self._running:
                raise DemoBusyError('研究问题正在处理，请等待完成')
            self._running.add('business-question')
        try:
            _, selection_status, _ = select_business_case(question, policy_id)
            config = None
            model = None
            class QuestionModel(ResearchPlannerModel):
                max_output_tokens = 2048
            if not selection_status:
                config = load_config()
                if not config.api_key:
                    raise ModelAdapterError('未配置本地模型密钥')
                config = replace(config, timeout_seconds=180.0)
                model = QuestionModel(config)
            run_id = 'exposure-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
            result = run_business_question(model, question, output_root / run_id,
                                          repository=repository, secret=config.api_key if config else '',
                                          policy_id=policy_id)
            available = result['status'] == 'draft_needs_review'
            from .research_data_link import research_data_link
            return {**result, 'run_id': run_id, 'report_available': available,
                    'data_report':research_data_link(repository.paths.root,output_root/run_id),
                    'report_url': f'/api/report/{run_id}' if available else None}
        finally:
            with self._lock:
                self._running.discard('business-question')

    def run(
        self,
        case: str,
        *,
        repository: EvidenceRepository,
        output_root: Path,
    ) -> dict[str, Any]:
        if case not in CASES:
            raise WebRequestError("未知的 AI 演示案例")
        with self._lock:
            if case in self._running:
                raise DemoBusyError("这个案例已经在运行；请等待当前运行结束。")
            self._running.add(case)
        run: Path | None = None
        try:
            config = load_config()
            if not config.api_key:
                raise ModelAdapterError("未配置本地模型密钥；没有调用模型")
            # Match the CLI's bounded timeout and generation class.  No retry
            # is added here: run_exposure_demo records the first failure.
            from dataclasses import replace

            config = replace(config, timeout_seconds=max(float(config.timeout_seconds), 180.0))

            class ExposureModel(ResearchPlannerModel):
                max_output_tokens = 4096

            output_root.mkdir(parents=True, exist_ok=True)
            run_id = "exposure-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            run = output_root / run_id
            result = run_exposure_demo(
                ExposureModel(config),
                run,
                repository=repository,
                secret=config.api_key,
                case=case,
            )
            report = run / "report.zh-CN.md"
            delivered = result.get("status") == "draft_needs_review" and report.is_file()
            return {
                "status": "draft_needs_review" if delivered else "failed",
                "case": case,
                "run_id": run_id,
                "report_available": delivered,
                "report_url": f"/api/report/{run_id}" if delivered else None,
                "model": config.model,
                "model_calls": result.get("model_calls", 0),
                "message": (
                    "已生成受约束初稿；下载前仍需人工审阅。"
                    if delivered
                    else "模型演示未生成可交付报告；原始失败记录已保留。"
                ),
            }
        finally:
            with self._lock:
                self._running.discard(case)


class TradeIntelHandler(BaseHTTPRequestHandler):
    """HTTP adapter kept intentionally thin so business logic stays testable."""

    repository: EvidenceRepository
    output_root: Path
    coordinator: DemoCoordinator
    static_root: Path
    trade_data_root: Path
    version_store: ExposureVersionStore
    trade_model_factory: Any = None

    server_version = "TradeIntelLocal/1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Do not print query contents or model payloads into the terminal.
        return

    def _send_json(self, status: int | HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int | HTTPStatus, body: str, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: int | HTTPStatus, exc: Exception) -> None:
        self._send_json(status, {"status": "error", "message": _safe_error(exc)})

    def _review_run(self, parsed):
        params = parse_qs(parsed.query, keep_blank_values=True)
        if not params:
            return self.repository.paths.root/'tmp/trade-aware-interpretation-v1-first/run'
        if set(params) != {'run_id'} or len(params['run_id']) != 1:
            raise ValueError('invalid review run selector')
        run_id = params['run_id'][0]
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError('invalid review run id')
        root = self.output_root.resolve()
        run = root/run_id
        if run.is_symlink() or not run.is_dir() or run.resolve().parent != root:
            raise ValueError('review run missing or unsafe')
        return run

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == '/api/saved-interpretation-review':
            from .interpretation_review_store import packet
            try:
                run=self._review_run(parsed)
                from .research_data_link import research_data_link
                self._send_json(HTTPStatus.OK,{**packet(run),
                    'data_report':research_data_link(self.repository.paths.root,run)})
            except (ValueError,OSError):
                self._error(HTTPStatus.CONFLICT,WebRequestError('审阅资料缺失或已变更'))
            return
        if parsed.path == '/api/saved-interpretation-draft':
            from .interpretation_review_store import reviewed_draft
            try:
                run=self._review_run(parsed)
                self._send_text(HTTPStatus.OK,reviewed_draft(run),'text/markdown; charset=utf-8')
            except (ValueError,OSError):
                self._error(HTTPStatus.CONFLICT,WebRequestError('审阅稿尚未具备导出条件，或审阅资料已变更'))
            return
        if parsed.path.startswith('/api/research-artifact/'):
            try:
                parts=parsed.path.split('/')
                if len(parts)!=5 or not RUN_ID_PATTERN.fullmatch(parts[3]) or parts[4] not in ('source-packet.zh-CN.md','interpretation-pending.zh-CN.md'):
                    raise WebRequestError('资料路径无效')
                root=self.output_root.resolve()
                path=(root/parts[3]/parts[4]).resolve()
                if not path.is_relative_to(root): raise WebRequestError('资料路径越界')
                self._send_text(HTTPStatus.OK,path.read_text(encoding='utf-8'),'text/plain; charset=utf-8')
            except (ValueError,WebRequestError):
                self._error(HTTPStatus.BAD_REQUEST,WebRequestError('资料路径无效'))
            except FileNotFoundError:
                self._error(HTTPStatus.NOT_FOUND,WebRequestError('资料尚未生成'))
            return
        try:
            if parsed.path == '/api/cases':
                from .policy_cases import public_case_catalog
                self._send_json(HTTPStatus.OK, public_case_catalog())
                return
            if parsed.path == "/api/health":
                self._send_json(HTTPStatus.OK, health_payload())
                return
            if parsed.path == "/api/model/status":
                try:
                    from .local_provider_config import product_status
                    self._send_json(HTTPStatus.OK, product_status())
                except (ModelAdapterError, ValueError, OSError):
                    self._send_json(HTTPStatus.OK, {"configured": False, "model": None})
                return
            if parsed.path == "/api/trade/catalog":
                from .trade_data_repository import TradeDataRepository
                self._send_json(HTTPStatus.OK,
                                TradeDataRepository(self.trade_data_root).catalog())
                return
            if parsed.path == "/api/trade/report-state":
                from .trade_report_store import get_state
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) != {"report_id"} or len(query["report_id"]) != 1:
                    raise WebRequestError("报告编号无效")
                self._send_json(HTTPStatus.OK,
                                get_state(self.repository.paths.root, query["report_id"][0]))
                return
            if parsed.path in {"/preview", "/preview/", "/preview/index.html",
                               "/preview/app.js", "/preview/live.js", "/preview/style.css",
                               "/preview/data.json", "/preview/vendor/cobe.mjs"}:
                relative = ("index.html" if parsed.path in
                            {"/preview", "/preview/"} else parsed.path[len("/preview/"):])
                asset = self.static_root / "design-preview" / relative
                mime = ("text/html" if relative.endswith(".html") else
                        "text/css" if relative.endswith(".css") else
                        "application/javascript" if relative.endswith((".js", ".mjs")) else
                        "application/json")
                self._send_text(HTTPStatus.OK, asset.read_text(encoding="utf-8"),
                                mime + "; charset=utf-8")
                return
            if parsed.path == "/api/policy":
                self._send_json(HTTPStatus.OK, policy_payload(self.repository))
                return
            if parsed.path == '/api/update-brief':
                from .update_brief import current_update_brief
                self._send_text(HTTPStatus.OK,current_update_brief(self.repository.paths.root,self.output_root),'text/plain; charset=utf-8')
                return
            if parsed.path == '/api/version-report':
                from .version_report import version_report
                query=parse_qs(parsed.query, keep_blank_values=True)
                if set(query)-{'version','policy_id'} or ('policy_id' in query and (len(query['policy_id'])!=1 or not query['policy_id'][0])) or ('version' in query and (len(query['version'])!=1 or not re.fullmatch(r'[0-9a-f]{64}',query['version'][0]))):
                    raise WebRequestError('数据版本参数无效')
                self._send_text(HTTPStatus.OK,version_report(self.repository.paths.root,query.get('version',[None])[0],policy_id=query.get('policy_id',[None])[0]),'text/html; charset=utf-8')
                return
            if parsed.path == "/api/update":
                self._send_json(HTTPStatus.OK, update_payload(self.repository.paths.root))
                return
            if parsed.path == "/api/update-status":
                from .controlled_update import update_status
                self._send_json(HTTPStatus.OK,
                                update_status(self.repository.paths.root))
                return
            if parsed.path == "/api/announcements/coverage":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) != {"policy_id", "doc_version"} \
                        or len(query["policy_id"]) != 1 \
                        or len(query["doc_version"]) != 1:
                    raise WebRequestError("公告覆盖查询参数无效")
                result = _handle_announcement_coverage(
                    self.repository.paths.root, query["policy_id"][0],
                    query["doc_version"][0])
                self._send_json(HTTPStatus.OK, result)
                return
            if parsed.path == "/api/announcements/candidates":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) != {"policy_id", "doc_version"} \
                        or len(query["policy_id"]) != 1 \
                        or len(query["doc_version"]) != 1:
                    raise WebRequestError("公告候选模板查询参数无效")
                from .announcement_flow import candidate_template, load_announcement_store
                store = load_announcement_store(self.repository.paths.root, query["policy_id"][0])
                result = {"status": "template", **candidate_template(store, query["doc_version"][0])}
                self._send_json(HTTPStatus.OK, result)
                return
            if parsed.path == "/api/announcements/linkage/assessment":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if (set(query) != {"policy_id", "doc_version"}
                        or any(len(query[key]) != 1 or not query[key][0]
                               for key in ("policy_id", "doc_version"))):
                    raise WebRequestError("公告关联判断查询参数无效")
                from .announcement_linkage import load_linkage_assessment
                self._send_json(HTTPStatus.OK, load_linkage_assessment(
                    self.repository.paths.root, query["policy_id"][0], query["doc_version"][0]))
                return
            if parsed.path == "/api/announcements/linkage/setup":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if (set(query) != {"policy_id", "doc_version"}
                        or any(len(query[key]) != 1 or not query[key][0]
                               for key in ("policy_id", "doc_version"))):
                    raise WebRequestError("公告关联设置查询参数无效")
                from .announcement_linkage import load_linkage_setup
                self._send_json(HTTPStatus.OK, load_linkage_setup(
                    self.repository.paths.root, query["policy_id"][0], query["doc_version"][0]))
                return
            if parsed.path == "/api/session":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) != {"session_id"} or len(query["session_id"]) != 1:
                    raise WebRequestError("session_id 参数无效")
                self._send_json(HTTPStatus.OK,
                                _session_state(self.repository.paths.root, query["session_id"][0]))
                return
            if parsed.path == "/api/session/draft":
                # A deterministic program draft is readable/downloadable as
                # soon as generation finishes.  This is deliberately separate
                # from the reviewed export gate below: it never exposes an
                # unreviewed AI explanation as if it were approved.
                query = parse_qs(parsed.query, keep_blank_values=True)
                if (set(query) != {"session_id", "task_id"}
                        or any(len(query[key]) != 1 or not query[key][0]
                               for key in ("session_id", "task_id"))):
                    raise WebRequestError("草稿参数无效")
                state = _session_state(self.repository.paths.root, query["session_id"][0])
                task = next((item for item in state["tasks"].values()
                             if item.get("task_id") == query["task_id"][0]), None)
                response = (task or {}).get("response") or {}
                if (task is not None
                        and task.get("state") in {"response_saved", "needs_review", "reviewed", "exportable"}
                        and response.get("kind") == "temporal-report-v1"
                        and isinstance(response.get("markdown"), str)
                        and response["markdown"]):
                    self._send_text(HTTPStatus.OK, response["markdown"],
                                    "text/markdown; charset=utf-8")
                    return
                if (task is None
                        or task.get("state") not in {"response_saved", "needs_review",
                                                       "reviewed", "exportable"}
                        or response.get("kind") != "program-report-a3"
                        or not isinstance(response.get("a3_markdown"), str)
                        or not response["a3_markdown"]):
                    raise WebRequestError("程序草稿尚未生成")
                self._send_text(HTTPStatus.OK, response["a3_markdown"],
                                "text/markdown; charset=utf-8")
                return
            if parsed.path == "/api/session/export":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if (set(query) != {"session_id", "task_id"}
                        or any(len(query[key]) != 1 or not query[key][0]
                               for key in ("session_id", "task_id"))):
                    raise WebRequestError("导出参数无效")
                state = _session_state(self.repository.paths.root, query["session_id"][0])
                task = next((item for item in state["tasks"].values()
                             if item.get("task_id") == query["task_id"][0]), None)
                response = (task or {}).get("response", {})
                if response.get("kind") == "temporal-report-v1":
                    # A temporal report uses the deterministic rendering by
                    # default; a reviewed public explanation may replace it
                    # only through the explicit final-kind binding.
                    markdown = (response.get("final_markdown")
                                if response.get("final_kind")
                                == "temporal-report-v1-with-reviewed-explanation"
                                else response.get("markdown"))
                else:
                    markdown = response.get("final_markdown") or response.get("a3_markdown")
                if task is None or task.get("state") != "exportable" or not markdown:
                    raise WebRequestError("审阅稿尚未具备导出条件")
                # Review J-acceptance item 2: dispatch to the matching
                # confirmation protocol; A3 and temporal reports must not
                # share a gate or silently accept each other's records.
                refusal = _draft_gate(task)
                if refusal:
                    raise WebRequestError(refusal)
                self._send_text(HTTPStatus.OK, markdown, "text/markdown; charset=utf-8")
                return
            if parsed.path == "/api/exposure":
                repository = pin_repository(self.repository)
                params = validate_exposure_params(
                    parse_qs(parsed.query, keep_blank_values=True), root=repository.paths.root
                )
                result = version_bound_exposure(repository, **params)
                self._send_json(HTTPStatus.OK, result)
                return
            if parsed.path.startswith("/api/report/"):
                run_id = unquote(parsed.path[len("/api/report/"):])
                report = safe_report_path(self.output_root, run_id)
                self._send_text(HTTPStatus.OK, report.read_text(encoding="utf-8"), "text/markdown; charset=utf-8")
                return
            if parsed.path in {"/", "/index.html"}:
                index = self.static_root / "index.html"
                if not index.is_file():
                    raise FileNotFoundError("页面文件不存在")
                self._send_text(HTTPStatus.OK, index.read_text(encoding="utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == '/demo/solar':
                demo = self.static_root / 'solar-demo.html'
                if not demo.is_file():
                    raise FileNotFoundError('只读示例尚未生成')
                self._send_text(HTTPStatus.OK, demo.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
                return
            if parsed.path == '/demo/research-review':
                review = self.static_root / 'research-review.html'
                if not review.is_file():
                    raise FileNotFoundError('研究审阅页面尚未生成')
                self._send_text(HTTPStatus.OK, review.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
                return
            if parsed.path == '/review/interpretation':
                self._send_text(HTTPStatus.OK,(self.static_root/'interpretation-review.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
                return
            if parsed.path == '/session-research':
                self._send_text(HTTPStatus.OK,(self.static_root/'session-research.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
                return
            if parsed.path == '/update-check':
                self._send_text(HTTPStatus.OK,(self.static_root/'update-check.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
                return
            if parsed.path == '/announcement-import':
                self._send_text(HTTPStatus.OK,
                                (self.static_root/'announcement-import.html').read_text(encoding='utf-8'),
                                'text/html; charset=utf-8')
                return
            self._error(HTTPStatus.NOT_FOUND, WebRequestError("页面或接口不存在"))
        except WebRequestError as exc:
            self._error(HTTPStatus.BAD_REQUEST, exc)
        except FileNotFoundError as exc:
            self._error(HTTPStatus.NOT_FOUND, exc)
        except VersionStoreError as exc:
            self._send_json(HTTPStatus.CONFLICT, {"status": "error", "message": str(exc)})
        except (RepositoryError, ToolError, ValueError) as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc)
        except Exception as exc:  # keep the server alive for another request
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/ai-demo", "/api/research", "/api/research-structured",
                               "/api/research-v2/preview", "/api/research-v2/confirm",
                               "/api/saved-interpretation-review", *SESSION_POST_PATHS):
            self._error(HTTPStatus.NOT_FOUND, WebRequestError("页面或接口不存在"))
            return
        try:
            if (self.coordinator._structured_model_factory is not None and parsed.path not in
                    ('/api/research-structured', '/api/saved-interpretation-review',
                     *SESSION_POST_PATHS)):
                raise WebRequestError('实验服务仅允许冻结的结构化任务，其他模型入口已关闭')
            length = int(self.headers.get("Content-Length", "0"))
            # An official notice and its section-level verbatim citations may
            # be longer than an ordinary API request. Keep the larger limit
            # exclusive to the notice import/confirmation workflow.
            body_limit = 262_144 if parsed.path in {
                "/api/announcements/import", "/api/announcements/submit",
                "/api/announcements/candidates", "/api/announcements/enable",
                "/api/announcements/linkage/confirm", "/api/announcements/linkage/report",
            } else 16_384
            if length < 0 or length > body_limit:
                raise WebRequestError("请求体过大")
            raw = self.rfile.read(length)
            payload = _decode_json_object(raw)
            if parsed.path in SESSION_POST_PATHS:
                if self.headers.get('Origin') and self.headers.get('Origin') != 'http://' + self.headers.get('Host', ''):
                    raise WebRequestError('只允许本地页面调用会话接口')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise WebRequestError('请求必须为application/json')
                if parsed.path == "/api/model/config":
                    if set(payload) not in ({"provider", "model", "api_key"},
                                            {"provider", "model", "api_key", "reasoning"}):
                        raise WebRequestError("模型设置字段不完整")
                    from .local_provider_config import save_product_config
                    result = save_product_config(payload["provider"], payload["model"],
                                                 payload["api_key"], payload.get("reasoning", "default"))
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/model/test":
                    if payload:
                        raise WebRequestError("连接测试不接受报告或密钥正文")
                    from .local_provider_config import probe_product_model
                    self._send_json(HTTPStatus.OK, probe_product_model())
                    return
                if parsed.path == "/api/product/scope":
                    if set(payload) != {"question"}:
                        raise WebRequestError("只接受问题文本")
                    from .product_scope import route_published_case
                    self._send_json(HTTPStatus.OK, route_published_case(payload["question"]))
                    return
                if parsed.path == "/api/trade/query":
                    expected = {"reporter", "flow", "product_code", "start_month",
                                "end_month", "partner", "dataset_version"}
                    if set(payload) != expected or any(not isinstance(payload[key], str)
                                                       for key in expected):
                        raise WebRequestError("贸易查询字段不完整或类型无效")
                    from .trade_data_repository import TradeDataError, TradeDataRepository, TradeQuery
                    try:
                        if payload["flow"] == "export":
                            from .trade_export_repository import ExportDataRepository, ExportTradeQuery
                            result = ExportDataRepository(self.trade_data_root).query(
                                ExportTradeQuery(**payload))
                        else:
                            result = TradeDataRepository(self.trade_data_root).query(
                                TradeQuery(**payload))
                    except TradeDataError as exc:
                        raise WebRequestError(str(exc)) from exc
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/trade/prepare":
                    if (not {"question"} <= set(payload) or
                            not set(payload) <= {"question", "selected_flow", "selected_product_id", "catalog_version"} or
                            ("selected_product_id" in payload) != ("catalog_version" in payload)):
                        raise WebRequestError("问题范围字段无效")
                    from .trade_query_flow import prepare_trade_question
                    from .trade_data_repository import TradeDataError
                    try:
                        result = prepare_trade_question(
                            self.trade_data_root, payload["question"],
                            selected_flow=payload.get("selected_flow"),
                            selected_product_id=payload.get("selected_product_id"),
                            catalog_version=payload.get("catalog_version"))
                    except TradeDataError as exc:
                        raise WebRequestError(str(exc)) from exc
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/trade/report":
                    if (not {"question", "selected_flow", "dataset_version"} <= set(payload) or
                            not set(payload) <= {"question", "selected_flow", "dataset_version",
                                                 "selected_product_id", "catalog_version"} or
                            ("selected_product_id" in payload) != ("catalog_version" in payload)):
                        raise WebRequestError("报告请求字段无效")
                    from .trade_query_flow import generate_trade_report
                    from .trade_data_repository import TradeDataError
                    try:
                        result = generate_trade_report(
                            self.trade_data_root, payload["question"],
                            selected_flow=payload["selected_flow"],
                            dataset_version=payload["dataset_version"],
                            selected_product_id=payload.get("selected_product_id"),
                            catalog_version=payload.get("catalog_version"))
                    except TradeDataError as exc:
                        raise WebRequestError(str(exc)) from exc
                    from .trade_report_store import create_record
                    from .trade_explanation_v4 import PROTOCOL as trade_v4_protocol
                    self._send_json(HTTPStatus.OK,
                                    create_record(self.repository.paths.root, result,
                                                  explanation_protocol=trade_v4_protocol))
                    return
                if parsed.path == "/api/trade/explanation/call":
                    if set(payload) != {"report_id", "report_sha256"}:
                        raise WebRequestError("解释请求只能包含报告编号和摘要")
                    from .trade_explanation import messages as trade_messages, parse as parse_trade
                    from .trade_explanation_v4 import (PROTOCOL as trade_v4_protocol,
                                                       messages as trade_messages_v4,
                                                       parse as parse_trade_v4)
                    from .trade_report_store import (claim_call, finish_parse, get_state,
                                                     load_record, mark_error, save_raw)
                    report_id = payload["report_id"]
                    digest = payload["report_sha256"]
                    record = load_record(self.repository.paths.root, report_id)
                    protocol = record.get("explanation_protocol")
                    if protocol == "none" or record["report"].get("kind") == "announcement-statistics-report-v1":
                        raise WebRequestError("这类公告数据报告没有模型解读入口")
                    from .local_provider_config import (PRODUCT_CONFIG_PATH, load_product_config,
                                                        product_config_identity, product_request_params)
                    from .model_adapter import OpenAICompatibleModel
                    if not PRODUCT_CONFIG_PATH.is_file() or PRODUCT_CONFIG_PATH.is_symlink():
                        raise WebRequestError("请先在模型设置中保存产品专用配置；旧实验凭证不会用于新报告")
                    config = load_product_config()
                    if not config.api_key:
                        raise WebRequestError("本机尚未配置产品模型密钥")
                    if protocol == trade_v4_protocol:
                        prompt = trade_messages_v4(record["report"], record["relation_snapshot"],
                                                   record["relation_snapshot_sha256"])
                    else:
                        prompt = trade_messages(record["report"], digest)
                    request_sha = hashlib.sha256(json.dumps(
                        prompt, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")).encode("utf-8")).hexdigest()
                    params = {**product_request_params(), "max_tokens": 2048}
                    claim_call(self.repository.paths.root, report_id, digest, model=config.model,
                               config_sha256=product_config_identity(),
                               request_sha256=request_sha,
                               expected_protocol=protocol or "trade-data-explanation-v3",
                               expected_relation_sha256=record.get("relation_snapshot_sha256"))
                    try:
                        # Read from the class: a plain test factory stored on a
                        # handler class must not become a bound instance method.
                        factory = type(self).trade_model_factory
                        model = (factory(config, params) if factory is not None else
                                 OpenAICompatibleModel(config, system_prompt="",
                                                       request_params=params))
                        answer = model.complete(messages=prompt, tools=[])
                    except ModelAdapterError as exc:
                        code = exc.details.get("http_status")
                        rejected = type(code) is int and 400 <= code < 500
                        mark_error(self.repository.paths.root, report_id,
                                   "failed" if rejected else "unknown_outcome", str(exc),
                                   details=exc.details)
                        self._send_json(HTTPStatus.OK,
                                        get_state(self.repository.paths.root, report_id))
                        return
                    except Exception:
                        mark_error(self.repository.paths.root, report_id, "unknown_outcome",
                                   "模型结果无法确认；本任务不会自动重试")
                        self._send_json(HTTPStatus.OK,
                                        get_state(self.repository.paths.root, report_id))
                        return
                    raw = getattr(answer, "text", None)
                    if not isinstance(raw, str) or not raw.strip():
                        mark_error(self.repository.paths.root, report_id, "failed",
                                   "模型没有返回正文")
                        self._send_json(HTTPStatus.OK,
                                        get_state(self.repository.paths.root, report_id))
                        return
                    metadata = answer.metadata if isinstance(answer.metadata, dict) else {}
                    save_raw(self.repository.paths.root, report_id, raw,
                             response_model=metadata.get("model"),
                             usage=metadata.get("usage") if isinstance(metadata.get("usage"), dict) else {})
                    try:
                        if protocol == trade_v4_protocol:
                            parsed_answer = parse_trade_v4(
                                raw, record["report"], record["relation_snapshot"],
                                record["relation_snapshot_sha256"])
                        else:
                            parsed_answer = parse_trade(raw, record["report"], digest)
                    except ValueError as exc:
                        mark_error(self.repository.paths.root, report_id, "invalid_answer", str(exc))
                    else:
                        finish_parse(self.repository.paths.root, report_id, parsed_answer)
                    self._send_json(HTTPStatus.OK,
                                    get_state(self.repository.paths.root, report_id))
                    return
                if parsed.path == "/api/trade/explanation/review":
                    if set(payload) != {"report_id", "report_sha256", "raw_sha256",
                                        "revision", "reviewer", "facts_checked", "decisions"}:
                        raise WebRequestError("审阅请求字段无效")
                    from .trade_report_store import load_record, review as review_trade
                    record = load_record(self.repository.paths.root, payload["report_id"])
                    if record.get("explanation_protocol") == "none":
                        raise WebRequestError("这类公告数据报告不支持模型解释审阅")
                    result = review_trade(self.repository.paths.root, payload["report_id"], payload)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/update/check":
                    from .controlled_update import run_update_cycle
                    snapshot = payload.get("snapshot")
                    fetch = (lambda: snapshot) if isinstance(snapshot, dict) else None
                    result = run_update_cycle(self.repository.paths.root, fetch=fetch,
                                              confirm=bool(payload.get("confirm")),
                                              dry_run=bool(payload.get("dry_run", True)))
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/announcements/import":
                    result = _handle_announcement_import(self.repository.paths.root, payload)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/announcements/statistics/prepare":
                    allowed = {"policy_id", "doc_version", "selected_codes", "start_month", "end_month"}
                    if not {"policy_id", "doc_version"}.issubset(payload) or not set(payload).issubset(allowed):
                        raise WebRequestError("公告统计范围字段无效")
                    from .announcement_statistics_report import prepare_announcement_statistics
                    result = prepare_announcement_statistics(
                        self.repository.paths.root, payload["policy_id"], payload["doc_version"],
                        selected_codes=payload.get("selected_codes"),
                        start_month=payload.get("start_month"), end_month=payload.get("end_month"),
                        trade_root=self.trade_data_root)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/announcements/statistics/report":
                    if set(payload) != {"prepared"} or not isinstance(payload.get("prepared"), dict):
                        raise WebRequestError("请提交服务器返回的完整确认范围")
                    from .announcement_statistics_report import generate_announcement_statistics_record
                    result = generate_announcement_statistics_record(self.repository.paths.root,
                                                                       payload["prepared"],
                                                                       trade_root=self.trade_data_root)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/announcements/linkage/confirm":
                    if (set(payload) != {"policy_id", "doc_version", "proposal",
                                         "confirmed_by", "candidate_digest"}
                            or not isinstance(payload.get("proposal"), dict)):
                        raise WebRequestError("关联判断确认字段无效")
                    from .announcement_linkage import confirm_linkage_assessment
                    result = confirm_linkage_assessment(
                        self.repository.paths.root, payload["policy_id"], payload["doc_version"],
                        payload["proposal"], confirmed_by=payload["confirmed_by"],
                        expected_candidate_digest=payload["candidate_digest"])
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/announcements/linkage/prepare":
                    if (not {"policy_id", "doc_version"}.issubset(payload)
                            or not set(payload).issubset({"policy_id", "doc_version",
                                                            "start_month", "end_month"})):
                        raise WebRequestError("关联范围准备字段无效")
                    from .announcement_linkage import prepare_linkage_scope
                    result = prepare_linkage_scope(
                        self.repository.paths.root, payload["policy_id"], payload["doc_version"],
                        start_month=payload.get("start_month"), end_month=payload.get("end_month"),
                        trade_root=self.trade_data_root)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/announcements/linkage/report":
                    if set(payload) != {"prepared"} or not isinstance(payload.get("prepared"), dict):
                        raise WebRequestError("请提交服务器返回的完整关联范围")
                    from .announcement_linkage import validate_prepared_linkage_scope
                    prepared = validate_prepared_linkage_scope(
                        self.repository.paths.root, payload["prepared"],
                        trade_root=self.trade_data_root)
                    if prepared["route"] == "announcement-statistics-report-v1":
                        from .announcement_statistics_report import generate_announcement_statistics_record
                        result = generate_announcement_statistics_record(
                            self.repository.paths.root, prepared["strict_scope"],
                            trade_root=self.trade_data_root)
                    elif prepared["route"] == "announcement-context-report-v1:parent":
                        from .announcement_context_report import generate_parent_context_record
                        result = generate_parent_context_record(
                            self.repository.paths.root, prepared, trade_root=self.trade_data_root)
                    elif prepared["route"] == "announcement-context-report-v1:country":
                        from .announcement_country_context import generate_country_context_record
                        result = generate_country_context_record(
                            self.repository.paths.root, prepared, trade_root=self.trade_data_root)
                    elif prepared["route"] == "source_fact_card_only":
                        from .announcement_source_card import generate_source_fact_record
                        result = generate_source_fact_record(self.repository.paths.root, prepared)
                    else:
                        raise WebRequestError("关联范围路线无效")
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/announcements/coverage/check":
                    result = _handle_announcement_coverage_check(self.repository.paths.root, payload)
                    self._send_json(HTTPStatus.OK, result)
                    return
                if parsed.path.startswith("/api/announcements/"):
                    result = _handle_announcement_flow(self.repository.paths.root,
                                                       parsed.path, payload)
                    self._send_json(HTTPStatus.OK, result)
                    return
                result = _handle_session_post(self.repository.paths.root, parsed.path,
                                              payload, self.repository)
                self._send_json(HTTPStatus.OK, result)
                return
            if parsed.path == '/api/saved-interpretation-review':
                if self.headers.get('Origin') != 'http://'+self.headers.get('Host',''):
                    raise WebRequestError('审阅提交必须来自同源本地页面')
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise WebRequestError('审阅必须为JSON')
                from .interpretation_review_store import submit
                result=submit(self._review_run(parsed),payload)
                self._send_json(HTTPStatus.OK,result)
                return
            if parsed.path == '/api/research-structured':
                origin=self.headers.get('Origin')
                if origin and origin != 'http://'+self.headers.get('Host',''):
                    raise WebRequestError('只允许本地页面提交任务')
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise WebRequestError('请求必须为application/json')
                result=self.coordinator.structured(payload,repository=self.repository,output_root=self.output_root)
                self._send_json(HTTPStatus.BAD_GATEWAY if result['status']=='failed' else HTTPStatus.OK,result)
                return
            if parsed.path == '/api/research-v2/preview':
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host', ''):
                    raise WebRequestError('只允许本地页面提交问题')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise WebRequestError('请求必须为application/json')
                if set(payload) != {'question'} or not isinstance(payload['question'], str):
                    raise WebRequestError('请求必须是 {question: ...} 对象')
                result = self.coordinator.natural_preview(
                    payload['question'], repository=self.repository, output_root=self.output_root
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if parsed.path == '/api/research-v2/confirm':
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host', ''):
                    raise WebRequestError('只允许本地页面提交确认')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise WebRequestError('请求必须为application/json')
                if set(payload) != {'confirmation_token'} or not isinstance(payload['confirmation_token'], str):
                    raise WebRequestError('请求必须是 {confirmation_token: ...} 对象')
                result = self.coordinator.natural_confirm(
                    payload['confirmation_token'], repository=self.repository, output_root=self.output_root
                )
                status = HTTPStatus.CONFLICT if result.get('status') in {
                    'confirmation_rejected', 'confirmation_stale'
                } else HTTPStatus.OK
                self._send_json(status, result)
                return
            if parsed.path == '/api/research':
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host', ''):
                    raise WebRequestError('只允许本地页面提交问题')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise WebRequestError('请求必须为application/json')
                if set(payload) not in ({'question'}, {'question', 'policy_id'}):
                    raise WebRequestError('请求只能包含question及可选policy_id')
                selected = payload.get('policy_id')
                if selected is not None and not isinstance(selected, str):
                    raise WebRequestError('policy_id必须为字符串或null')
                result = self.coordinator.ask(payload['question'], repository=self.repository,
                                              output_root=self.output_root, policy_id=selected)
                self._send_json(HTTPStatus.BAD_GATEWAY if result['status'] == 'failed' else HTTPStatus.OK, result)
                return
            if not isinstance(payload, dict) or set(payload) != {"case"} or not isinstance(payload["case"], str):
                raise WebRequestError("请求必须是 {case: ...} 对象")
            result = self.coordinator.run(
                payload["case"], repository=self.repository, output_root=self.output_root
            )
            self._send_json(HTTPStatus.OK if result["status"] != "failed" else HTTPStatus.BAD_GATEWAY, result)
        except DemoBusyError as exc:
            self._error(HTTPStatus.CONFLICT, exc)
        except WebRequestError as exc:
            self._error(HTTPStatus.BAD_REQUEST, exc)
        except (ModelAdapterError, ValueError) as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY if parsed.path.startswith(
                "/api/announcements/") and isinstance(exc, ValueError)
                else HTTPStatus.SERVICE_UNAVAILABLE, exc)
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, exc)


def create_server(
    *,
    root: Path | None = None,
    host: str = DEFAULT_WEB_HOST,
    port: int = DEFAULT_WEB_PORT,
    output_root: Path | None = None,
    trade_data_root: Path | None = None,
    structured_model_factory=None,
    trade_model_factory=None,
) -> ThreadingHTTPServer:
    """Create a configured local server; useful for the CLI and offline tests."""

    project_root = _configured_root(root)
    data_root = project_root if trade_data_root is None else Path(trade_data_root).expanduser().resolve()
    if trade_data_root is not None and not (
        data_root.is_dir() and (data_root / "BUNDLE_MANIFEST.json").is_file()
        and (data_root / "data").is_dir()
    ):
        raise ValueError("独立贸易数据目录须包含 BUNDLE_MANIFEST.json 和 data/；服务未启动")
    repository = EvidenceRepository()
    # EvidenceRepository resolves the package checkout by default.  Tests can
    # provide an alternate root without changing global process state.
    if root is not None:
        from .repository import DataPaths

        repository = EvidenceRepository(DataPaths(project_root))
    target_output = (output_root or project_root / DEFAULT_OUTPUT_ROOT_NAME).resolve()
    static_root = project_root / "web"

    class ConfiguredHandler(TradeIntelHandler):
        pass

    ConfiguredHandler.repository = repository
    ConfiguredHandler.output_root = target_output
    ConfiguredHandler.coordinator = DemoCoordinator(structured_model_factory=structured_model_factory)
    ConfiguredHandler.static_root = static_root
    ConfiguredHandler.trade_data_root = data_root
    ConfiguredHandler.version_store = ExposureVersionStore(project_root)
    ConfiguredHandler.trade_model_factory = trade_model_factory
    return ThreadingHTTPServer((host, port), ConfiguredHandler)


__all__ = [
    "CASES",
    "DEFAULT_WEB_HOST",
    "DEFAULT_WEB_PORT",
    "DemoBusyError",
    "DemoCoordinator",
    "TradeIntelHandler",
    "create_server",
    "health_payload",
    "policy_payload",
    "safe_report_path",
    "update_payload",
    "validate_exposure_params",
]
