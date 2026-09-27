"""New-announcement confirmation flow (offline): candidates -> enable -> rebind.

Second stage of the separate new-announcement path (J4/E2 contract): a
disabled candidate document registered by the import endpoint gets a
13-field candidate template, a human fills values with verbatim quotes,
``build_candidates``/``confirm_candidate`` verify and bind the digest, and
only then may the document move disabled -> enabled.  Enabling always
returns ``rebind_required``: every previously confirmed research scope was
bound to the OLD policy set, so sessions must re-confirm before any new
report.  Trade coverage stays ``not_checked`` until a trusted trade query
is supplied.  This module performs no network access and never auto-enables.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .announcement_store import (announcement_lock, load_announcement_store as _load_store,
                                 save_announcement_store as _save_store)
from .policy_candidates import (REQUIRED_FIELDS, build_candidates, build_coverage,
                                candidate_digest, confirm_candidate, parse_code_precision)
from .policy_documents import get_section, set_document_status, validate_document_store


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_announcement_store(root: Path, policy_id: str) -> dict[str, Any]:
    return _load_store(root, policy_id)


def _announcement_document(store: dict[str, Any], doc_version: str) -> dict[str, Any]:
    """Return one registered announcement or fail closed.

    The enable operation must target the exact disabled document named by the
    caller.  Without this check an all-``unknown`` candidate (which has no
    evidence locations to bind) could accidentally enable another document in
    the same policy store.
    """
    for document in store.get("documents", []):
        if document.get("doc_version") == doc_version:
            return document
    raise ValueError(f"unknown announcement document: {doc_version}")


def save_announcement_store(root: Path, policy_id: str, store: dict[str, Any]) -> None:
    _save_store(root, policy_id, store)


def _candidate_record(store: dict[str, Any], doc_version: str) -> dict[str, Any] | None:
    record = (store.get("announcement_candidates") or {}).get(doc_version)
    return record if isinstance(record, dict) else None


def candidate_template(store: dict[str, Any], doc_version: str) -> dict[str, Any]:
    """13-field template for one disabled candidate announcement.

    Every field starts ``unknown`` with an explicit placeholder reason; the
    human (or a later confirmed extraction) must supply values plus verbatim
    quotes before confirmation.  The document must exist in the store as a
    disabled candidate.
    """
    validate_document_store(store)
    found = get_section(store, doc_version, _any_section_id(store, doc_version))
    if found is None:
        raise ValueError(f"unknown announcement document: {doc_version}")
    document = found["document"]
    if document.get("status") != "disabled":
        raise ValueError("只有disabled候选公告可以生成确认模板")
    return {"schema_version": "announcement-candidate-template-v1",
            "doc_version": doc_version,
            "policy_id": document.get("policy_id"),
            "source_provenance": (store.get("announcement_imports") or {}).get(
                doc_version, {}).get("source_provenance", "unknown"),
            "source_url": document.get("url"),
            "sections": [{"section_id": section["id"], "text": section["text"]}
                         for section in document["sections"]],
            "fields": [{"field": name, "status": "unknown", "value": None,
                        "reason": "待人工确认：填写值并粘贴原文逐字引文"}
                       for name in REQUIRED_FIELDS],
            "boundary": "模板是确认工作的起点；unknown是诚实状态，不代表没有该字段。"}


def _any_section_id(store: dict[str, Any], doc_version: str) -> str:
    for document in store.get("documents", []):
        if document.get("doc_version") == doc_version:
            for section in document.get("sections", []):
                return section["id"]
    return ""


def submit_candidates(root: Path, policy_id: str, doc_version: str,
                      fields: list[dict[str, Any]]) -> dict[str, Any]:
    """Build and verify the candidate record from human-supplied fields.

    Known fields need verbatim quotes into the saved announcement text; the
    disabled candidate document is the allowed citation target here.  The
    candidate is RETURNED, not enabled -- enabling is a separate step.
    """
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        document = _announcement_document(store, doc_version)
        if document.get("status") != "disabled":
            raise ValueError("只有disabled候选公告可以提交确认字段")
        candidate = build_candidates(fields, store, allowed_statuses=("enabled", "disabled"))
        # A candidate for this path is bound to the exact announcement being
        # reviewed, even when every field is unknown and carries no quote yet.
        for field in candidate.get("fields", []):
            for item in field.get("evidence", []):
                if item["doc_version"] != doc_version:
                    raise ValueError(f"字段 {field['field']} 的引文不是本公告（{doc_version}）")
        store.setdefault("announcement_candidates", {})[doc_version] = {
            "candidate": candidate,
            "candidate_digest": candidate["candidate_digest"],
            "status": "candidate_ready",
        }
        save_announcement_store(root, policy_id, store)
        return {"status": "candidate_ready", "candidate": candidate,
                "candidate_digest": candidate["candidate_digest"],
                "boundary": "候选已通过引文校验；quote匹配不代表语义正确，启用需人工确认。"}


def confirm_and_enable(root: Path, policy_id: str, doc_version: str,
                       fields: list[dict[str, Any]], *, confirmed_by: str,
                       expected_candidate_digest: str | None = None) -> dict[str, Any]:
    """Confirm the candidate (digest-bound) and enable the announcement.

    Enable gate: all 13 required fields present with explicit statuses
    (unknown needs a reason; conflicts need two evidence entries -- both are
    enforced by build_candidates).  After enabling, every existing confirmed
    research scope is stale: the response carries ``rebind_required``.
    """
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        document = _announcement_document(store, doc_version)
        if document.get("status") != "disabled":
            raise ValueError("只有disabled候选公告可以启用；已启用或旧版本需走更新流程")
        candidate = build_candidates(fields, store, allowed_statuses=("enabled", "disabled"))
        record = _candidate_record(store, doc_version)
        recorded_digest = (record or {}).get("candidate_digest")
        if not isinstance(recorded_digest, str) or not recorded_digest:
            raise ValueError("必须先提交候选并使用服务器登记摘要确认")
        if expected_candidate_digest is None:
            raise ValueError("确认启用必须携带提交后显示的 candidate_digest")
        if candidate.get("candidate_digest") != recorded_digest:
            raise ValueError("候选内容已变化；请重新提交候选并重新确认")
        if not isinstance(expected_candidate_digest, str) or expected_candidate_digest != recorded_digest:
            raise ValueError("候选摘要与服务器登记记录不一致；请重新提交候选")
        # Every citation must point at the announcement being enabled.
        for field in candidate.get("fields", []):
            for item in field.get("evidence", []):
                if item["doc_version"] != doc_version:
                    raise ValueError(f"字段 {field['field']} 的引文不是本公告（{doc_version}）；拒绝启用")
        if candidate.get("missing_required_fields"):
            raise ValueError("存在缺失的必选字段；不能启用")
        confirmation = confirm_candidate(candidate, store, confirmed_by=confirmed_by,
                                         allowed_statuses=("enabled", "disabled"))
        set_document_status(store, doc_version, "enabled")
        # Keep the accepted candidate and its confirmation with the local store so
        # the coverage endpoint and a page refresh can show exactly what was
        # enabled.  These metadata keys do not participate in doc_version hashing.
        store.setdefault("announcement_candidates", {})[doc_version] = {
            "candidate": candidate,
            "candidate_digest": candidate["candidate_digest"],
            "confirmation": confirmation,
            "status": "enabled",
        }
        save_announcement_store(root, policy_id, store)
        coverage = build_coverage(candidate)
        return {"status": "enabled", "doc_version": doc_version,
                "candidate_digest": candidate["candidate_digest"],
                "confirmed_by": confirmed_by,
                "confirmation": confirmation,
                "rebind_required": True,
                "policy_binding": {
                    "policy_id": policy_id, "doc_version": doc_version,
                    "candidate_digest": candidate["candidate_digest"]},
                "coverage": coverage,
                "boundary": "启用=字段确认完成且引文可回溯；贸易覆盖在受信任查询前保持not_checked；"
                            "既有研究范围全部需要重新确认（rebind_required）。"}


def coverage_report(root: Path, policy_id: str, doc_version: str) -> dict[str, Any]:
    """Read the coverage state for an enabled announcement.

    Coverage is deliberately read-only.  It can report ``not_checked``
    without inventing trade evidence; a later trusted query may replace it in
    the controlled update path.
    """
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        document = _announcement_document(store, doc_version)
        if document.get("status") != "enabled":
            raise ValueError("只有已启用公告可以查看覆盖状态")
        record = (store.get("announcement_candidates") or {}).get(doc_version)
        if not isinstance(record, dict) or not isinstance(record.get("candidate"), dict):
            raise ValueError("该公告没有可核验的候选记录；需要重新走确认流程")
        trade_record = ((store.get("trade_coverage") or {}).get(doc_version) or {})
        # A report must be tied to the currently confirmed candidate.  A
        # hand-edited or stale coverage record is visible as not_checked, never
        # promoted to an exact result.
        trade_evidence = None
        if isinstance(trade_record, dict) and \
                trade_record.get("candidate_digest") == record["candidate"].get("candidate_digest"):
            trade_evidence = trade_record.get("trade_evidence")
        coverage = build_coverage(record["candidate"], trade_evidence=trade_evidence)
        result = {"status": "coverage", "policy_id": policy_id,
                "doc_version": doc_version,
                "candidate_digest": record["candidate"].get("candidate_digest"),
                "policy_binding": {
                    "policy_id": policy_id, "doc_version": doc_version,
                    "candidate_digest": record["candidate"].get("candidate_digest")},
                "coverage": coverage,
                "rebind_required": True,
                "boundary": "未提供受信任贸易查询时，trade_coverage 保持 not_checked。"}
        if isinstance(trade_record, dict) and trade_record.get("coverage_digest"):
            result["trade_coverage"] = {
                key: trade_record.get(key) for key in
                ("coverage_digest", "source_case_id", "month", "data_version",
                 "candidate_codes", "requested_codes", "covered_codes", "missing_codes",
                 "scope", "availability", "reason") if key in trade_record
            }
        return result


def load_trade_coverage(store: dict[str, Any], doc_version: str,
                        coverage_digest_value: str | None = None) -> dict[str, Any]:
    """Load a verified immutable coverage record, never silently latest."""
    latest = ((store.get("trade_coverage") or {}).get(doc_version) or {})
    record = latest
    if coverage_digest_value:
        history = ((store.get("trade_coverage_history") or {}).get(doc_version) or {})
        record = history.get(coverage_digest_value) or {}
    if not isinstance(record, dict) or not record.get("coverage_digest"):
        raise ValueError("公告覆盖记录不存在；请重新核对覆盖")
    from .announcement_report import coverage_digest
    if record.get("coverage_digest") != coverage_digest(record):
        raise ValueError("公告覆盖记录摘要不一致；请重新核对覆盖")
    if coverage_digest_value and record["coverage_digest"] != coverage_digest_value:
        raise ValueError("公告覆盖记录不是当前任务绑定的版本")
    return record


def check_trade_coverage(root: Path, policy_id: str, doc_version: str, *,
                         month: str, source_case_id: str = "us_301_review2025_tungsten_solar",
                         data_version: str | None = None,
                         requested_codes: list[str] | None = None) -> dict[str, Any]:
    """Create a server-side, version-bound coverage record for one month.

    The caller can request a source case and month, but cannot submit amounts
    or mark them exact.  Only an enabled registered case and the existing
    read-only exposure tool can create the record.
    """
    from .announcement_report import (candidate_hts_entries, coverage_digest,
                                      query_bound_trade_partial)
    import re
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("覆盖月份必须是 YYYY-MM")
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        document = _announcement_document(store, doc_version)
        if document.get("status") != "enabled":
            raise ValueError("只有已启用公告可以核对贸易覆盖")
        record = _candidate_record(store, doc_version)
        candidate = (record or {}).get("candidate") if isinstance(record, dict) else None
        if not isinstance(candidate, dict):
            raise ValueError("公告缺少已确认候选；不能核对贸易覆盖")
        recorded_digest = candidate.get("candidate_digest")
        if not isinstance(recorded_digest, str) or not recorded_digest:
            raise ValueError("公告候选摘要缺失；不能核对贸易覆盖")
        # Verify the candidate and every quote again before querying data.
        confirm_candidate(candidate, store, confirmed_by="server-coverage",
                          digest=recorded_digest, allowed_statuses=("enabled", "disabled"))
        entries = candidate_hts_entries(candidate)
        candidate_codes = [item["code"] for item in entries]
        whole_codes = [item["code"] for item in entries if item.get("precision") == "whole_hts8"]
        statistical_codes = [item["code"] for item in entries if len(item.get("code", "")) == 8]
        if requested_codes is None:
            # For a partial legal scope there may be no ``whole_hts8`` entry,
            # but its eight-digit statistical lines can still be compared as
            # partial evidence.  They remain partial and never become an
            # exact policy exposure.
            query_codes = sorted(whole_codes or statistical_codes)
        else:
            if (not isinstance(requested_codes, list) or not requested_codes
                    or len(requested_codes) != len(set(requested_codes))
                    or any(not isinstance(code, str) or not re.fullmatch(r"\d{8}", code)
                           for code in requested_codes)
                    or not set(requested_codes).issubset(set(whole_codes))):
                raise ValueError("requested_codes 必须是公告 whole HTS8 的唯一子集")
            query_codes = sorted(requested_codes)
        query_statistical_codes = [code for code in query_codes if code in set(statistical_codes)]
        fields = {item.get("field"): item for item in candidate.get("fields", [])}
        origin = fields.get("origin", {}).get("value") if fields.get("origin", {}).get("status") == "known" else None
        record_base: dict[str, Any] = {
            "policy_id": policy_id, "doc_version": doc_version,
            "candidate_digest": recorded_digest, "month": month,
            "source_case_id": source_case_id,
            "candidate_codes": candidate_codes, "requested_codes": query_codes,
            "scope": "full" if query_codes == sorted(whole_codes) else "selected",
            "covered_codes": [], "missing_codes": query_codes,
            "data_version": None, "availability": "none",
            "reason": None, "trade_evidence": None,
        }
        if not entries:
            record_base["reason"] = "公告没有完成可核验的 HTS 范围字段。"
        elif len(whole_codes) != len(entries):
            record_base["reason"] = "公告范围含 HS6、ex、文字限定或部分 HTS10；不能扩成完整 HTS8。"
            record_base["availability"] = "partial"
            # An eight-digit ex/text-limited line may still be compared with
            # the statistical table, but its result remains partial because
            # the legal scope is narrower than the whole HTS8 line.
            if query_statistical_codes and origin in ("China", "中国", "China origin", "中国原产"):
                try:
                    trade, covered, missing, version = query_bound_trade_partial(
                        root, announcement_policy_id=policy_id,
                        source_case_id=source_case_id, requested_codes=query_statistical_codes,
                        month=month, data_version=data_version)
                except (ValueError, RuntimeError) as exc:
                    record_base["reason"] += "；统计表核对失败：" + str(exc)
                else:
                    record_base.update({
                        "covered_codes": covered,
                        "missing_codes": missing,
                        "data_version": version,
                        "trade_evidence": {
                            "codes": covered, "requested_codes": query_statistical_codes,
                            "month": month, "data_version": version, "availability": "partial",
                        },
                        "trade_result": trade,
                    })
        elif origin not in ("China", "中国", "China origin", "中国原产"):
            record_base["reason"] = "当前贸易来源只登记中国原产地查询；公告原产地字段未确认成该范围。"
            record_base["availability"] = "partial"
        else:
            try:
                trade, covered, missing, version = query_bound_trade_partial(
                    root, announcement_policy_id=policy_id,
                    source_case_id=source_case_id, requested_codes=query_codes,
                    month=month, data_version=data_version)
            except (ValueError, RuntimeError) as exc:
                record_base["reason"] = str(exc)
            else:
                record_base.update({
                    "covered_codes": covered, "missing_codes": missing,
                    "data_version": version,
                    "availability": "exact" if not missing else ("partial" if covered else "none"),
                    "trade_evidence": {
                        "codes": covered, "requested_codes": query_codes, "month": month,
                        "data_version": version,
                        "availability": "exact" if not missing else ("partial" if covered else "none"),
                    },
                    # Keep the exact server-created result so a report can be
                    # rebuilt after a refresh and compared byte-for-byte.
                    "trade_result": trade,
                    })
        # Even a failed/partial source query can be classified honestly when
        # the registered source version is known: ``none``/``partial`` is
        # different from ``not_checked``.  No amount is synthesized here.
        if record_base.get("trade_evidence") is None and \
                (query_statistical_codes or record_base.get("availability") == "partial"):
            try:
                from .announcement_report import _repository_for_version
                _repo, source_version, _active = _repository_for_version(
                    root, source_case_id, data_version)
            except (ValueError, RuntimeError):
                source_version = None
            if source_version:
                record_base["data_version"] = source_version
                record_base["trade_evidence"] = {
                    "codes": [], "requested_codes": list(query_statistical_codes), "month": month,
                    "data_version": source_version,
                    "availability": record_base["availability"],
                }
        record_base["coverage_digest"] = coverage_digest(record_base)
        history = store.setdefault("trade_coverage_history", {}).setdefault(doc_version, {})
        history[record_base["coverage_digest"]] = record_base
        store.setdefault("trade_coverage", {})[doc_version] = record_base
        save_announcement_store(root, policy_id, store)
        return coverage_report(root, policy_id, doc_version)


def resolve_policy_binding(root: Path, policy_id: str, doc_version: str,
                          candidate_digest_value: str | None = None,
                          month: str | None = None,
                          requested_codes: list[str] | None = None) -> dict[str, Any]:
    """Resolve a server-owned enabled announcement binding for a session.

    The caller supplies only an expected digest.  The document, candidate and
    confirmation are loaded from the locked local store; an arbitrary frontend
    value can never turn a disabled or unknown document into a policy binding.
    """
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        document = _announcement_document(store, doc_version)
        if document.get("status") != "enabled":
            raise ValueError("公告尚未启用；不能绑定到研究会话")
        record = (store.get("announcement_candidates") or {}).get(doc_version)
        candidate = (record or {}).get("candidate") if isinstance(record, dict) else None
        if not isinstance(candidate, dict):
            raise ValueError("公告缺少已确认候选；不能绑定到研究会话")
        recorded = candidate.get("candidate_digest")
        if not isinstance(recorded, str) or not recorded:
            raise ValueError("公告候选摘要缺失；不能绑定到研究会话")
        if candidate_digest_value is not None and candidate_digest_value != recorded:
            raise ValueError("客户端公告摘要与服务器登记版本不一致；请重新确认")
        # Re-run the expensive checks at the binding boundary.  This catches a
        # manually edited candidate even if its surrounding JSON still parses.
        verified = confirm_candidate(candidate, store,
                                     confirmed_by="server-rebind",
                                     digest=recorded,
                                     allowed_statuses=("enabled", "disabled"))
        binding = {"policy_id": policy_id, "doc_version": doc_version,
                   "candidate_digest": recorded,
                   "data_version": store.get("data_version"),
                   "confirmation": verified, "status": "enabled"}
        if isinstance(month, str) and month:
            trade_record = None
            history = ((store.get("trade_coverage_history") or {}).get(doc_version) or {})
            candidates = list(history.values())
            if not candidates:
                candidates = [((store.get("trade_coverage") or {}).get(doc_version) or {})]
            if requested_codes is None:
                # A request without an explicit subset means the announcement
                # full scope, not “whichever coverage record was checked most
                # recently”.  This prevents a later selected-2 record from
                # being reused by a full-scope URL.
                hts_field = next((field for field in candidate.get("fields", [])
                                  if field.get("field") == "hts_codes"), None)
                if isinstance(hts_field, dict) and hts_field.get("status") == "known":
                    try:
                        expected_codes = sorted(
                            item["code"] for item in parse_code_precision(hts_field.get("value"))
                            if item.get("precision") == "whole_hts8")
                    except ValueError:
                        expected_codes = None
                else:
                    expected_codes = None
            else:
                expected_codes = sorted(requested_codes)
            for item in reversed(candidates):
                if (item.get("month") == month and item.get("candidate_digest") == recorded
                        and (expected_codes is None or sorted(item.get("requested_codes") or []) == expected_codes)):
                    trade_record = item
                    break
            if isinstance(trade_record, dict) and trade_record.get("coverage_digest"):
                binding["coverage_month"] = month
                binding["coverage_status"] = trade_record.get("availability", "none")
                binding["trade_coverage_digest"] = trade_record.get("coverage_digest")
                binding["requested_codes"] = list(trade_record.get("requested_codes") or [])
                binding["coverage_scope"] = trade_record.get("scope", "full")
                if trade_record.get("data_version"):
                    # The source snapshot can be known even when only a
                    # subset of the requested codes is available.  Binding
                    # the version preserves auditability; the exact/partial
                    # gate below still decides whether a report is allowed.
                    binding["data_version"] = trade_record.get("data_version")
        return binding


def search_policy_binding(root: Path, binding: dict[str, Any], question: str, *,
                          hts8: str | None = None, as_of: str | None = None,
                          top_k: int = 6) -> dict[str, Any]:
    """Search only the server-resolved announcement bound to a request.

    A missing or stale binding fails closed.  The caller cannot silently fall
    back to the primary case or to another enabled document.
    """
    if not isinstance(binding, dict):
        raise ValueError("policy_binding must be an object")
    resolved = resolve_policy_binding(
        root, str(binding.get("policy_id") or ""),
        str(binding.get("doc_version") or ""), binding.get("candidate_digest"))
    store = load_announcement_store(root, resolved["policy_id"])
    from .policy_search import PolicySearch
    searcher = PolicySearch(store, policy_id=resolved["policy_id"])
    result = searcher.search(question, hts8=hts8, as_of=as_of, top_k=top_k,
                             doc_versions=[resolved["doc_version"]])
    result["policy_binding"] = resolved
    return result
