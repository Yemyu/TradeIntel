"""Deterministic session brief builder (offline; no model, no network).

Turns a confirmed session request (policy_id, month, product, focus) into the
same evidence bundle / fact catalog / A3 program report used by the offline
preparation pipeline, so the web session flow can show a complete, reviewable
program baseline while the AI explanation contract (v3) stays unadopted.  The
response clearly states that it contains NO model-generated content.

Version binding (review J2): the builder REQUIRES the explicit registered
data version that the user confirmed.  A missing or unknown version is
refused -- an empty value never silently means "whatever is active now".  A
version other than the active one is built from that version's verified
release dataset, so evidence and report stay on the confirmed version even
when the active pointer moves afterwards.
"""
from __future__ import annotations

import re
from pathlib import Path
import sys
from typing import Any

from .evidence_bundle import build_evidence_bundle
from .brief_fact_catalog import build_fact_catalog, render_fact_catalog, validate_fact_catalog
from .brief_business_view import build_view
from .exposure_version_store import ExposureVersionStore, VersionStoreError, pin_repository
from .repository import EvidenceRepository, DataPaths

_VERSION_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def build_session_brief(root: Path, request: dict[str, Any], *,
                        data_version: str | None = None) -> dict[str, Any]:
    """Build the deterministic brief for one confirmed request at a FIXED version.

    Only the registered primary case is wired here; other policy cases need
    their own enabled registration before this entry serves them.
    """
    policy_id = str(request.get("policy_id") or "")
    month = str(request.get("month") or "")
    product = request.get("product") or "all"
    focus = str(request.get("focus") or "contrast")
    if policy_id != "us_301_review2025_tungsten_solar":
        raise ValueError("当前会话简报仅接入已登记主案例；其他政策需先完成登记与启用。")
    if not data_version or not _VERSION_PATTERN.fullmatch(str(data_version)):
        raise ValueError("必须绑定明确的已登记数据版本；空版本不得暗指不断变化的活动版。")
    data_version = str(data_version)
    sys.path[:0] = [str(root), str(root / "src")]
    from tradeintel_ai.policy_cases import CASES  # noqa: E402  (project-root import)
    from tradeintel_ai.policy_exposure_tools import get_policy_exposure_series  # noqa: E402
    from tradeintel_ai.exposure_policy import retrieve_exposure_policy  # noqa: E402
    from tradeintel_ai.primary_fact_sheet import build_primary_fact_sheet  # noqa: E402
    from tradeintel_ai.structured_task import compile_task  # noqa: E402

    case = CASES[policy_id]
    store = ExposureVersionStore(root, root / case.versions)
    active = store.active_version()
    if active is None:
        raise ValueError("当前没有已登记的活动数据版本；无法构建会话简报。")
    try:
        snapshot = store.load_snapshot(data_version)
    except VersionStoreError as exc:
        raise ValueError(
            f"绑定的数据版本不存在或未登记；需要重新确认范围：{data_version[:12]}…") from exc
    if snapshot["policy_id"] != policy_id:
        raise ValueError("绑定的数据版本属于其他政策；拒绝构建。")
    if data_version == active:
        repo = pin_repository(EvidenceRepository(DataPaths(root)), policy_id=policy_id)
        repo.exposure_store = store
        repo.exposure_snapshot = snapshot
    else:
        # The active pointer moved after confirmation: keep the report on the
        # CONFIRMED version by building from its verified release dataset.
        try:
            release = store.release_root(data_version)
        except VersionStoreError as exc:
            raise ValueError(
                f"确认版本 {data_version[:12]}… 没有已核验的发布副本，需要重新确认范围") from exc
        repo = EvidenceRepository(DataPaths(release))
        repo.exposure_version = data_version
        repo.exposure_store = store
        repo.exposure_snapshot = snapshot
    task = dict(policy_id=policy_id, month=month, product=product, focus=focus,
                task="monthly_exposure", schema_version="research-request-v2",
                policy_view="archived_event")
    question, _ = compile_task(task)
    trade = get_policy_exposure_series(
        policy_id=policy_id, hts8=None if product == "all" else product,
        start=month, end=month, repository=repo)
    built_version = trade.get("data_version")
    if built_version != data_version:
        raise ValueError(
            f"实际构建版本 {built_version} 与确认绑定版本 {data_version} 不一致；拒绝生成")
    evidence = retrieve_exposure_policy(repo.paths.root, question, as_of="2026-09-15")
    facts = build_primary_fact_sheet(evidence, repo.exposure_version, root=repo.paths.root)
    bundle = build_evidence_bundle(trade, facts, focus=focus)
    catalog = build_fact_catalog(bundle)
    validate_fact_catalog(catalog)
    view, sidecar = build_view(question, catalog)
    evidence_rows = []
    for profile in bundle.get("profiles", []):
        share = profile.get("china_share_of_product_percent")
        evidence_rows.append({
            "hts8": profile["hts8"],
            "world_import_usd": profile["world_import_usd"],
            "china_import_usd": profile["china_import_usd"],
            "china_share_percent": None if share is None else float(share),
            "share_status": "unknown" if share is None else "known",
        })
    return {
        "kind": "program-report-a3",
        "policy_id": policy_id, "month": month, "product": product, "focus": focus,
        "data_version": data_version,
        "active_version": active,
        "catalog_sha256": catalog["catalog_sha256"],
        # The catalog is the immutable host-owned input for the optional AI
        # explanation stage.  Callers may persist it server-side, but should
        # not expose the full source text in a browser state response.
        "catalog": catalog,
        "fact_count": len(catalog["facts"]),
        "observation_count": len(catalog["observations"]),
        "question": question,
        "evidence_rows": evidence_rows,
        "a3_markdown": render_fact_catalog(catalog),
        "boundary": "本响应是确定性程序报告（A3基准），不含任何模型生成内容；"
                    "AI解释合同（v3）尚未采纳，真实模型输出须另行审阅。",
    }


def build_temporal_session_brief(root: Path, request: dict[str, Any], *,
                                 data_version: str | None = None) -> dict[str, Any]:
    """Build a multi-period deterministic brief for ``analysis-request-v1``."""
    import hashlib
    import json

    from .analysis_request import resolve_query_plan, validate_analysis_request
    from .policy_exposure_tools import get_policy_exposure_series
    from .public_report import build_public_report, render_public_report
    from .temporal_evidence import (build_temporal_evidence,
                                    render_temporal_evidence,
                                    validate_temporal_evidence)

    canonical = validate_analysis_request(request)
    policy_id = canonical["policy_id"]
    from .policy_cases import CASES
    case = CASES.get(policy_id)
    if case is None or case.status != "enabled":
        raise ValueError("多期简报只接入已登记开放政策")
    if not data_version or not _VERSION_PATTERN.fullmatch(str(data_version)):
        raise ValueError("必须绑定明确的已登记数据版本")
    store = ExposureVersionStore(root, root / case.versions)
    snapshot = store.load_snapshot(str(data_version))
    if snapshot["policy_id"] != policy_id:
        raise ValueError("绑定数据版本属于其他政策")
    if str(data_version) == store.active_version():
        repo = pin_repository(EvidenceRepository(DataPaths(root)), policy_id=policy_id)
    else:
        repo = EvidenceRepository(DataPaths(store.release_root(str(data_version))))
        repo.exposure_version = str(data_version)
    repo.exposure_version = str(data_version)
    repo.exposure_store = store
    repo.exposure_snapshot = snapshot

    available: dict[str, dict[str, list[str]]] = {}
    for month, entry in snapshot.get("months", {}).items():
        metrics = entry.get("metrics") if isinstance(entry, dict) else None
        breakdown = metrics.get("product_breakdown") if isinstance(metrics, dict) else []
        available[month] = {"products": [item.get("hts8") for item in breakdown
                                           if isinstance(item, dict) and item.get("hts8")]}
    plan = resolve_query_plan(canonical, available=available)
    required = list(plan["required_months"])
    trade = get_policy_exposure_series(
        policy_id=policy_id, origin="all_origins", start=min(required), end=max(required),
        repository=repo, include_origins=True)
    if trade.get("data_version") != str(data_version):
        raise ValueError("实际贸易查询版本与请求绑定版本不一致")

    comparability = {"records": []}
    transition_path = root / "data/processed/policy_exposure/code_transition_review.json"
    if transition_path.exists():
        raw = transition_path.read_bytes()
        review = json.loads(raw.decode("utf-8"))
        if review.get("status") != "reviewed_specific_transition":
            raise ValueError("编码过渡复核记录不是已审阅状态")
        # The review is a global official-evidence record, but its two
        # monthly inputs must still match the pinned release dataset.  This
        # prevents an old snapshot from silently borrowing a newer transition
        # decision after the working tree changes.
        review_sources = review.get("sources")
        if not isinstance(review_sources, list) or not review_sources:
            raise ValueError("编码过渡复核缺少绑定的月度来源指纹")
        for item in review_sources:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) \
                    or not _VERSION_PATTERN.fullmatch(str(item.get("sha256") or "")):
                raise ValueError("编码过渡复核来源指纹无效")
            relative = Path(item["path"])
            candidates = [(repo.paths.root / relative).resolve(),
                          (root / relative).resolve()]
            source = next((candidate for candidate in candidates
                           if candidate.is_file()), None)
            if source is None or not source.is_relative_to(repo.paths.root.resolve()) \
                    and not source.is_relative_to(root.resolve()):
                raise ValueError("编码过渡复核来源不在绑定数据范围内")
            if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("编码过渡复核来源指纹与绑定数据版本不一致")
        source_id = "review:" + hashlib.sha256(raw).hexdigest()
        comparability["records"].append({
            "product": "38180000", "metric": "trade_exposure", "kind": "mom",
            "base_period": str(review.get("reference_month")),
            "period": str(review.get("current_month")),
            "status": "reviewed" if review.get("status") == "reviewed_specific_transition"
                      else "unverified",
            "source_id": source_id,
            "source": {"source_id": source_id, "kind": "official_code_transition_review",
                       "url": review.get("source_url"), "path": str(transition_path),
                       "sha256": hashlib.sha256(raw).hexdigest()},
        })
    evidence = build_temporal_evidence(trade, canonical, query_plan=plan,
                                       comparability=comparability)
    validate_temporal_evidence(evidence, canonical)
    # Reuse the reviewed, hash-checked archived clauses on the pinned release.
    # A new announcement binding must not silently receive the primary case's
    # old clauses. That path requires its own confirmed document integration.
    if canonical.get("policy_binding") is not None or canonical["policy_view"] != "archived_event":
        raise ValueError("多期政策解释暂仅支持未替换绑定的已登记存档案例")
    from .exposure_policy import retrieve_exposure_policy
    from .primary_fact_sheet import build_primary_fact_sheet
    policy_evidence = retrieve_exposure_policy(
        repo.paths.root, "2025年钨、硅片与多晶硅存档政策条款", as_of="2026-09-15")
    policy_context = build_primary_fact_sheet(
        policy_evidence, str(data_version), root=repo.paths.root)
    report = build_public_report(evidence, canonical, policy_context=policy_context)
    evidence_bytes = json.dumps(evidence, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8")
    return {
        "kind": "temporal-report-v1", "policy_id": policy_id,
        "data_version": str(data_version), "request": canonical,
        "query_plan": plan, "evidence": evidence,
        "policy_context": policy_context,
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "report": report,
        "report_sha256": report["report_sha256"],
        "markdown": render_public_report(report),
        "boundary": "本报告由已核验官方贸易数据程序生成，不含模型生成内容；"
                    "未核验的跨期口径只显示为未知，不解释为政策因果。",
    }
