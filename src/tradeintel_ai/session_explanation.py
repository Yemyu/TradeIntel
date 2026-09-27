"""Session-bound AI explanation and review for the local product chain.

The deterministic A3 report remains the source of numeric and legal facts.
This module only attaches the bounded host-bound explanation contract to an
already-built session task.  It is deliberately provider-neutral: a future
API adapter and a local/chat simulation both submit one raw response through
the same parser and review gates.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import html
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from .brief_fact_catalog import render_fact_catalog, validate_fact_catalog
from .bounded_explanation import VERSION, messages as bounded_messages, parse as parse_bounded, slots

SNAPSHOT_SCHEMA = "session-explanation-snapshot-v1"
RESULT_SCHEMA = "session-explanation-result-v1"
PUBLIC_SNAPSHOT_SCHEMA_V1 = "public-brief-explanation-snapshot-v1"
PUBLIC_SNAPSHOT_SCHEMA = "public-brief-explanation-snapshot-v2"


class HistoricalPublicSnapshotNeedsMigration(ValueError):
    """An intact historical snapshot cannot enter the current input protocol."""


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _review_sha(value: dict[str, Any]) -> str:
    """Digest one sanitized review record for append-only revisions."""
    return _sha(value)


def _safe(value: Any) -> str:
    text = html.escape(str(value), quote=True)
    return re.sub(r"([\\`*_[\]()>#+!|~])", r"\\\1", text)


def _artifact_dir(root: Path, session_id: str, task_id: str) -> Path:
    # session_store validates these identifiers; repeat a narrow check here so
    # this module never turns a browser value into an arbitrary path.
    if not re.fullmatch(r"session-[0-9a-f]{16}", session_id):
        raise ValueError("invalid session id")
    if not re.fullmatch(r"task-[0-9]+", task_id):
        raise ValueError("invalid task id")
    return Path(root) / ".local" / "session-artifacts" / session_id / task_id


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".snapshot-", suffix=".tmp")
    try:
        with open(handle, "w", encoding="utf-8", closefd=True) as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        Path(temporary).replace(path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def build_snapshot(task_response: dict[str, Any], *, question: str,
                   identity: dict[str, str] | None = None) -> dict[str, Any]:
    """Build a content-addressed explanation input from one A3 response."""
    if not isinstance(task_response, dict) or task_response.get("kind") != "program-report-a3":
        raise ValueError("只能从确定性 program-report-a3 创建解释快照")
    catalog = task_response.get("catalog")
    if not isinstance(catalog, dict):
        raise ValueError("程序报告没有保存主事实目录；不能创建解释快照")
    validate_fact_catalog(catalog)
    a3 = task_response.get("a3_markdown")
    expected_a3 = render_fact_catalog(catalog)
    if not isinstance(a3, str) or a3 != expected_a3:
        raise ValueError("程序报告与事实目录不一致；拒绝创建解释快照")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("解释问题不能为空")
    request_messages = bounded_messages(question, catalog)
    binding = slots(catalog)
    unsigned = {
        "schema_version": SNAPSHOT_SCHEMA,
        "protocol": VERSION,
        "question": question,
        "catalog": deepcopy(catalog),
        "messages": deepcopy(request_messages),
        "host_bindings": deepcopy(binding),
        "program_report_a3": a3,
        "policy_id": catalog.get("policy_id"),
        "data_version": catalog.get("data_version"),
        "catalog_sha256": catalog.get("catalog_sha256"),
        "program_report_sha256": _text_sha(a3),
    }
    if identity is not None:
        if (not isinstance(identity, dict)
                or set(identity) != {"session_id", "task_id"}
                or any(not isinstance(identity[key], str) or not identity[key]
                       for key in identity)):
            raise ValueError("解释快照身份无效")
        unsigned["identity"] = deepcopy(identity)
    unsigned["snapshot_sha256"] = _sha(unsigned)
    return unsigned


def save_snapshot(root: Path, session_id: str, task_id: str,
                  snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
        raise ValueError("invalid explanation snapshot")
    if snapshot.get("identity") != {"session_id": session_id, "task_id": task_id}:
        raise ValueError("解释快照必须绑定当前session/task身份")
    identity = snapshot.get("identity")
    loaded = build_snapshot({"kind": "program-report-a3",
                              "catalog": snapshot.get("catalog"),
                              "a3_markdown": snapshot.get("program_report_a3")},
                             question=str(snapshot.get("question") or ""),
                             identity=identity)
    if loaded.get("snapshot_sha256") != snapshot.get("snapshot_sha256"):
        raise ValueError("explanation snapshot hash mismatch")
    path = _artifact_dir(root, session_id, task_id) / "snapshot.json"
    if path.exists():
        if path.is_symlink() or _text_sha(path.read_text(encoding="utf-8")) != _text_sha(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"):
            raise ValueError("解释快照已存在且内容不同；拒绝覆盖")
    else:
        _atomic_json(path, snapshot)
    saved = deepcopy(snapshot)
    saved["path"] = str(path.relative_to(Path(root)))
    saved["path_sha256"] = _text_sha(path.read_text(encoding="utf-8"))
    return saved


def load_snapshot(root: Path, session_id: str, task_id: str,
                  reference: dict[str, Any] | None = None) -> dict[str, Any]:
    path = _artifact_dir(root, session_id, task_id) / "snapshot.json"
    reference_path = (reference.get("path") or reference.get("snapshot_path")) if reference else None
    expected_path = str(path.relative_to(Path(root)))
    if reference_path and reference_path != expected_path:
        raise ValueError("解释快照路径不匹配")
    if reference and reference.get("path_sha256"):
        if not path.is_file() or _text_sha(path.read_text(encoding="utf-8")) != reference["path_sha256"]:
            raise ValueError("解释快照文件摘要不匹配")
    if not path.is_file() or path.is_symlink():
        raise ValueError("解释快照不存在")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
        raise ValueError("解释快照格式无效")
    if snapshot.get("identity") != {"session_id": session_id, "task_id": task_id}:
        raise ValueError("解释快照身份与任务不匹配")
    expected = deepcopy(snapshot)
    recorded = expected.pop("snapshot_sha256", None)
    if not isinstance(recorded, str) or _sha(expected) != recorded:
        raise ValueError("解释快照摘要不匹配")
    # Rebuild every derived part; an edited file cannot change the request or
    # evidence that the model is supposed to see.
    rebuilt = build_snapshot({"kind": "program-report-a3",
                              "catalog": snapshot.get("catalog"),
                              "a3_markdown": snapshot.get("program_report_a3")},
                             question=str(snapshot.get("question") or ""),
                             identity=snapshot.get("identity"))
    if rebuilt != snapshot:
        raise ValueError("解释快照派生内容不一致")
    return snapshot


def prepare(root: Path, session_id: str, task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    response = task.get("response") or {}
    snapshot = build_snapshot(response, question=str(task.get("request_snapshot", {}).get("question")
                                                     or response.get("question")
                                                     or "请解释这份贸易政策研究结果"),
                              identity={"session_id": session_id, "task_id": task_id})
    saved = save_snapshot(root, session_id, task_id, snapshot)
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "ready_for_provider",
        "protocol": VERSION,
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "catalog_sha256": snapshot["catalog_sha256"],
        "program_report_sha256": snapshot["program_report_sha256"],
        "identity": deepcopy(snapshot["identity"]),
        "messages_sha256": _sha(snapshot["messages"]),
        "host_binding_sha256": _sha(snapshot["host_bindings"]),
        "path": saved["path"],
        "path_sha256": saved["path_sha256"],
        # Kept as a read-only compatibility alias for older local clients.
        "snapshot_path": saved["path"],
        # Exact request for a local chat simulation or a future API adapter.
        "messages": deepcopy(snapshot["messages"]),
        "host_bindings": deepcopy(snapshot["host_bindings"]),
        "channel": None,
        "raw_sha256": None,
        "parsed": None,
        "validation": None,
        "flags": [],
        "review": None,
    }


def submit(root: Path, session_id: str, task_id: str, current: dict[str, Any],
           raw_text: str, *, channel: str, model: str | None = None) -> dict[str, Any]:
    if channel not in {"chat_simulation", "stub", "api"}:
        raise ValueError("解释来源必须是chat_simulation、stub或api")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("模型原始回答不能为空")
    snapshot = load_snapshot(root, session_id, task_id, current)
    result = parse_bounded(raw_text, snapshot["catalog"])
    parsed = result["answer"]
    return {
        **deepcopy(current),
        "status": result["status"],
        "channel": channel,
        "model": (model or "unknown")[:120],
        "raw_sha256": result["raw_sha256"],
        "raw_text": raw_text,
        "parsed": parsed,
        "validation": result["validation"],
        "flags": result.get("flags", []),
        "review": None,
    }


def _review_items(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    answer = parsed.get("parsed") if isinstance(parsed.get("parsed"), dict) else parsed
    findings = answer.get("findings", []) if isinstance(answer, dict) else []
    followups = answer.get("followups", []) if isinstance(answer, dict) else []
    finding_items = [{"kind": "finding", "index": i} for i in range(len(findings))]
    offset = len(finding_items)
    return finding_items + [{"kind": "followup", "index": offset + i}
                            for i in range(len(followups))]


def review_result(current: dict[str, Any], payload: dict[str, Any], *, reviewer: str) -> dict[str, Any]:
    if not isinstance(current, dict) or not current.get("raw_sha256") or not current.get("parsed"):
        raise ValueError("模型回答尚未通过结构解析")
    expected = _review_items(current["parsed"])
    from .interpretation_review_store import SESSION_REVIEW_PROTOCOL, validate_review_payload
    review = validate_review_payload(SESSION_REVIEW_PROTOCOL, payload, expected,
                                    reviewer=reviewer)
    review.update({"raw_sha256": current["raw_sha256"],
                   "snapshot_sha256": current.get("snapshot_sha256"),
                   "catalog_sha256": current.get("catalog_sha256"),
                   "program_report_sha256": current.get("program_report_sha256"),
                   "protocol": SESSION_REVIEW_PROTOCOL,
                   "review_revision": int(current.get("review_revision") or 0) + 1,
                   "base_review_digest": (_review_sha(current["review"])
                                          if isinstance(current.get("review"), dict)
                                          else None)})
    return review


def render_reviewed(current: dict[str, Any], snapshot: dict[str, Any], review: dict[str, Any]) -> str:
    if not review.get("eligible_for_export"):
        raise ValueError("解释尚未达到导出门槛")
    parsed = current["parsed"]
    answer = parsed.get("parsed") if isinstance(parsed.get("parsed"), dict) else parsed
    decisions = {(item["kind"], item["index"]): item["verdict"] for item in review["decisions"]}
    lines = ["## AI解释（已逐项人工审阅）", "",
             "以下文字只解释程序已提供的事实，不改写金额、比例、政策条件或统计范围。", ""]
    findings = answer.get("findings", [])
    for index, finding in enumerate(findings):
        if decisions.get(("finding", index)) != "accept":
            continue
        interpretation = finding.get("interpretation", "")
        lines += [f"### 解释 {index + 1}", "", _safe(interpretation), ""]
    finding_count = len(findings)
    accepted_followups = [item for index, item in enumerate(answer.get("followups", []))
                          if decisions.get(("followup", finding_count + index)) == "accept"]
    if accepted_followups:
        lines += ["### 后续核查问题", ""]
        for item in accepted_followups:
            lines += [f"- 待补证据：{_safe(item.get('missing_evidence', ''))}",
                      f"- 要回答的问题：{_safe(item.get('question', ''))}", ""]
    lines += ["### AI边界", "", "模型回答已保存原始摘要并由人工逐项审阅；本节不构成因果、税款、损失或预测结论。", ""]
    return "\n".join(lines)


def _validate_public_policy(context: Any, report: dict[str, Any]) -> None:
    if not isinstance(context, dict):
        raise ValueError("政策上下文必须是对象")
    if context:
        from .policy_facts_contract import validate_policy_facts
        validate_policy_facts(context)
        if (context.get("policy_id") != report["request"]["policy_id"]
                or context.get("data_version") != report.get("data_version")
                or context.get("policy_view") != report["request"]["policy_view"]):
            raise ValueError("政策原文与报告绑定不一致")
        if report.get("policy_context") != context:
            raise ValueError("任务政策上下文与程序报告不一致")
    elif report.get("policy_context"):
        raise ValueError("程序报告已有政策事实，但任务没有绑定政策上下文")


def build_public_snapshot(task_response: dict[str, Any], *, question: str,
                          identity: dict[str, str] | None = None,
                          request_context: dict[str, Any] | None = None,
                          mode: str = "trade") -> dict[str, Any]:
    """Build a content-bound snapshot for the multi-period explanation contract."""
    from .public_brief_explanation import messages as public_messages
    from .public_report import render_public_report
    if not isinstance(task_response, dict) or task_response.get("kind") != "temporal-report-v1":
        raise ValueError("只能从 temporal-report-v1 创建公开解释快照")
    report = task_response.get("report")
    if not isinstance(report, dict):
        raise ValueError("多期程序报告缺失")
    rendered = render_public_report(report)
    if rendered != task_response.get("markdown"):
        raise ValueError("多期程序报告与报告对象不一致")
    # The snapshot must bind to the exact response that the task stored.  A
    # caller cannot provide a valid report object and then attach a digest from
    # another run (or silently omit the evidence digest).
    expected_report_sha = report.get("report_sha256")
    expected_evidence_sha = _sha(report.get("evidence"))
    if (task_response.get("report_sha256") != expected_report_sha
            or task_response.get("evidence_sha256") != expected_evidence_sha):
        raise ValueError("多期程序报告摘要与任务响应不一致")
    if (task_response.get("request") != report.get("request")
            or task_response.get("evidence") != report.get("evidence")
            or task_response.get("data_version") != report.get("data_version")):
        raise ValueError("多期程序报告内容与任务响应不一致")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("解释问题不能为空")
    policy_context = deepcopy(task_response.get("policy_context", {}))
    _validate_public_policy(policy_context, report)
    if mode not in {"trade", "policy"}:
        raise ValueError("解释模式必须是trade或policy")
    if mode == "policy":
        from .public_policy_explanation import messages as policy_messages
        messages = policy_messages(question, report, policy_context=policy_context,
                                   request_context=request_context)
        protocol = "public-policy-explanation-prototype-v2"
    else:
        messages = public_messages(question, report, policy_context=policy_context,
                                   request_context=request_context)
        protocol = "public-brief-explanation-v1"
    unsigned = {
        "schema_version": PUBLIC_SNAPSHOT_SCHEMA,
        "policy_context": policy_context,
        "request_context": deepcopy(request_context) if request_context is not None else None,
        "protocol": protocol,
        "mode": mode,
        "question": question,
        "report": deepcopy(report),
        "messages": deepcopy(messages),
        "request": deepcopy(report.get("request")),
        "data_version": report.get("data_version"),
        "request_digest": report.get("request_digest"),
        "evidence_sha256": expected_evidence_sha,
        "report_sha256": expected_report_sha,
        "program_markdown_sha256": _text_sha(rendered),
    }
    if identity is not None:
        if (not isinstance(identity, dict) or set(identity) != {"session_id", "task_id"}
                or any(not isinstance(identity[key], str) or not identity[key] for key in identity)):
            raise ValueError("解释快照身份无效")
        unsigned["identity"] = deepcopy(identity)
    unsigned["snapshot_sha256"] = _sha(unsigned)
    return unsigned


def save_public_snapshot(root: Path, session_id: str, task_id: str,
                         snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != PUBLIC_SNAPSHOT_SCHEMA:
        raise ValueError("invalid public explanation snapshot")
    if snapshot.get("identity") != {"session_id": session_id, "task_id": task_id}:
        raise ValueError("公开解释快照必须绑定当前session/task身份")
    mode = snapshot.get("mode", "trade")
    expected_protocol = ("public-policy-explanation-prototype-v2"
                         if mode == "policy" else "public-brief-explanation-v1"
                         if mode == "trade" else None)
    if expected_protocol is None or snapshot.get("protocol") != expected_protocol:
        raise ValueError("公开解释快照模式与协议不匹配")
    path = _artifact_dir(root, session_id, task_id) / "public-snapshot.json"
    expected = deepcopy(snapshot)
    recorded = expected.pop("snapshot_sha256", None)
    if not isinstance(recorded, str) or _sha(expected) != recorded:
        raise ValueError("公开解释快照摘要不匹配")
    # Re-check derived fields even when a caller bypasses build_public_snapshot.
    from .public_brief_explanation import messages as public_messages
    from .public_report import render_public_report
    report = snapshot.get("report")
    if not isinstance(report, dict):
        raise ValueError("公开解释快照缺少报告")
    _validate_public_policy(snapshot.get("policy_context", {}), report)
    rendered = render_public_report(report)
    snapshot_mode = snapshot.get("mode", "trade")
    if snapshot_mode == "policy":
        from .public_policy_explanation import messages as policy_messages
        expected_messages = policy_messages(snapshot.get("question"), report,
                                            policy_context=snapshot.get("policy_context"),
                                            request_context=snapshot.get("request_context"))
    elif snapshot_mode == "trade":
        expected_messages = public_messages(snapshot.get("question"), report,
                                            policy_context=snapshot.get("policy_context"),
                                            request_context=snapshot.get("request_context"))
    else:
        raise ValueError("公开解释快照模式无效")
    if (snapshot.get("report_sha256") != report.get("report_sha256")
            or snapshot.get("evidence_sha256") != _sha(report.get("evidence"))
            or snapshot.get("request_digest") != report.get("request_digest")
            or snapshot.get("program_markdown_sha256") != _text_sha(rendered)
            or snapshot.get("messages") != expected_messages):
        raise ValueError("公开解释快照派生字段不一致")
    if path.is_symlink():
        raise ValueError("公开解释快照路径不安全")
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if _text_sha(existing) != _text_sha(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"):
            raise ValueError("公开解释快照已存在且内容不同；拒绝覆盖")
    else:
        _atomic_json(path, snapshot)
    saved = deepcopy(snapshot)
    saved["path"] = str(path.relative_to(Path(root)))
    saved["path_sha256"] = _text_sha(path.read_text(encoding="utf-8"))
    return saved


def load_public_snapshot(root: Path, session_id: str, task_id: str,
                         reference: dict[str, Any] | None = None) -> dict[str, Any]:
    path = _artifact_dir(root, session_id, task_id) / "public-snapshot.json"
    expected_path = str(path.relative_to(Path(root)))
    if reference and reference.get("path") not in (None, expected_path):
        raise ValueError("公开解释快照路径不匹配")
    if reference and reference.get("path_sha256"):
        if not path.is_file() or _text_sha(path.read_text(encoding="utf-8")) != reference["path_sha256"]:
            raise ValueError("公开解释快照文件摘要不匹配")
    if not path.is_file() or path.is_symlink():
        raise ValueError("公开解释快照不存在")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") not in {
            PUBLIC_SNAPSHOT_SCHEMA_V1, PUBLIC_SNAPSHOT_SCHEMA}:
        raise ValueError("公开解释快照格式无效")
    if snapshot.get("identity") != {"session_id": session_id, "task_id": task_id}:
        raise ValueError("公开解释快照身份与任务不匹配")
    mode = snapshot.get("mode", "trade")
    expected_protocol = ("public-policy-explanation-prototype-v2"
                         if mode == "policy" else "public-brief-explanation-v1"
                         if mode == "trade" else None)
    if expected_protocol is None or snapshot.get("protocol") != expected_protocol:
        raise ValueError("公开解释快照模式与协议不匹配")
    recorded = snapshot.get("snapshot_sha256")
    unsigned = deepcopy(snapshot)
    unsigned.pop("snapshot_sha256", None)
    if not isinstance(recorded, str) or _sha(unsigned) != recorded:
        raise ValueError("公开解释快照摘要不匹配")
    if snapshot.get("schema_version") == PUBLIC_SNAPSHOT_SCHEMA_V1:
        raise HistoricalPublicSnapshotNeedsMigration(
            "历史输入版本待迁移：原快照保留；请在新任务中重新准备当前输入，不能沿用旧模型回答")
    from .public_brief_explanation import messages as public_messages
    from .public_report import render_public_report
    rendered = render_public_report(snapshot["report"])
    report = snapshot["report"]
    _validate_public_policy(snapshot.get("policy_context", {}), report)
    if (snapshot.get("report_sha256") != report.get("report_sha256")
            or snapshot.get("evidence_sha256") != _sha(report.get("evidence"))
            or snapshot.get("request_digest") != report.get("request_digest")
            or snapshot.get("program_markdown_sha256") != _text_sha(rendered)):
        raise ValueError("公开解释快照摘要或报告绑定不一致")
    if snapshot.get("mode", "trade") == "policy":
        from .public_policy_explanation import messages as policy_messages
        expected_messages = policy_messages(snapshot["question"], report,
                                            policy_context=snapshot.get("policy_context"),
                                            request_context=snapshot.get("request_context"))
    elif snapshot.get("mode", "trade") == "trade":
        expected_messages = public_messages(snapshot["question"], report,
                                            policy_context=snapshot.get("policy_context"),
                                            request_context=snapshot.get("request_context"))
    else:
        raise ValueError("公开解释快照模式无效")
    if expected_messages != snapshot["messages"]:
        raise ValueError("公开解释快照派生消息不一致")
    return snapshot


def prepare_public(root: Path, session_id: str, task_id: str,
                   task: dict[str, Any], *, mode: str = "trade") -> dict[str, Any]:
    response = task.get("response") or {}
    question = str((task.get("request_snapshot") or {}).get("original_question")
                   or "请用通俗语言解释这份贸易政策与数据简报")
    snapshot = build_public_snapshot(response, question=question,
                                     identity={"session_id": session_id, "task_id": task_id},
                                     request_context=task.get("request_context"), mode=mode)
    saved = save_public_snapshot(root, session_id, task_id, snapshot)
    return {"schema_version": RESULT_SCHEMA, "protocol": snapshot["protocol"],
            "mode": snapshot["mode"],
            "status": "ready_for_provider", "snapshot_sha256": snapshot["snapshot_sha256"],
            "report_sha256": snapshot["report_sha256"],
            "evidence_sha256": snapshot["evidence_sha256"],
            "request_digest": snapshot["request_digest"],
            "data_version": snapshot["data_version"], "identity": snapshot["identity"],
            "messages": deepcopy(snapshot["messages"]), "path": saved["path"],
            "path_sha256": saved["path_sha256"], "raw_sha256": None, "raw_text": None,
            "parsed": None, "validation": None, "flags": [], "review": None}


def submit_public(root: Path, session_id: str, task_id: str, current: dict[str, Any],
                  raw_text: str, *, channel: str, model: str | None = None) -> dict[str, Any]:
    from .public_brief_explanation import parse as parse_public
    if channel not in {"chat_simulation", "stub", "api"}:
        raise ValueError("解释来源必须是chat_simulation、stub或api")
    snapshot = load_public_snapshot(root, session_id, task_id, current)
    if snapshot.get("mode", "trade") == "policy":
        from .public_policy_explanation import parse as parse_policy
        result = parse_policy(raw_text, snapshot["report"], question=snapshot["question"],
                              policy_context=snapshot.get("policy_context") or {},
                              request_context=snapshot.get("request_context"))
    else:
        result = parse_public(raw_text, snapshot["report"])
    parsed = {"interpretations": result.get("interpretations", []),
              "watchlist": result.get("watchlist", [])}
    if "policy_explanations" in result:
        parsed["policy_explanations"] = result["policy_explanations"]
    return {**deepcopy(current), "status": result["status"], "protocol": result["protocol"],
            "channel": channel, "model": (model or "unknown")[:120],
            "raw_sha256": result["raw_sha256"], "raw_text": raw_text,
            "parsed": parsed,
            "validation": result, "flags": [], "review": None}


def review_public_result(current: dict[str, Any], payload: dict[str, Any], *, reviewer: str) -> dict[str, Any]:
    if not isinstance(current, dict) or not current.get("raw_sha256") or not current.get("parsed"):
        raise ValueError("公开解释回答尚未通过结构解析")
    parsed = current["parsed"]
    expected = ([{"kind": "interpretation", "index": index}
                 for index, _ in enumerate(parsed.get("interpretations", []))]
                + [{"kind": "policy_explanation", "index": index}
                   for index, _ in enumerate(parsed.get("policy_explanations", []))]
                + [{"kind": "watchlist", "index": index}
                   for index, _ in enumerate(parsed.get("watchlist", []))])
    from .interpretation_review_store import PUBLIC_SESSION_REVIEW_PROTOCOL, validate_review_payload
    review = validate_review_payload(PUBLIC_SESSION_REVIEW_PROTOCOL, payload, expected,
                                     reviewer=reviewer)
    review.update({"raw_sha256": current["raw_sha256"],
                   "snapshot_sha256": current.get("snapshot_sha256"),
                   "report_sha256": current.get("report_sha256"),
                   "evidence_sha256": current.get("evidence_sha256"),
                   "request_digest": current.get("request_digest"),
                   "protocol": PUBLIC_SESSION_REVIEW_PROTOCOL,
                   "review_revision": int(current.get("review_revision") or 0) + 1,
                   "base_review_digest": (_review_sha(current["review"])
                                          if isinstance(current.get("review"), dict) else None)})
    return review


def render_public_reviewed(current: dict[str, Any], snapshot: dict[str, Any],
                           review: dict[str, Any]) -> dict[str, Any]:
    if not review.get("eligible_for_export"):
        raise ValueError("公开解释尚未达到导出门槛")
    from .public_report import build_public_report, render_public_report, _sha as report_sha
    if (current.get("snapshot_sha256") != snapshot.get("snapshot_sha256")
            or current.get("report_sha256") != snapshot.get("report_sha256")
            or current.get("evidence_sha256") != snapshot.get("evidence_sha256")
            or current.get("request_digest") != snapshot.get("request_digest")):
        raise ValueError("公开解释回答与其绑定快照不一致")
    parsed = current.get("parsed") or {}
    decisions = {(item["kind"], item["index"]): item["verdict"]
                 for item in review.get("decisions", [])}
    interpretations = [item for index, item in enumerate(parsed.get("interpretations", []))
                       if decisions.get(("interpretation", index)) == "accept"]
    policy_explanations = [item for index, item in enumerate(parsed.get("policy_explanations", []))
                           if decisions.get(("policy_explanation", index)) == "accept"]
    watchlist = [item for index, item in enumerate(parsed.get("watchlist", []))
                 if decisions.get(("watchlist", index)) == "accept"]
    if not interpretations:
        raise ValueError("至少需要采纳一条公开解释")
    report = build_public_report(snapshot["report"]["evidence"], snapshot["report"]["request"],
                                 explanations=interpretations, policy_explanations=policy_explanations,
                                 watchlist=watchlist,
                                 policy_context=snapshot.get("policy_context"))
    report["review_status"] = "reviewed"
    unsigned = dict(report)
    unsigned.pop("report_sha256", None)
    report["report_sha256"] = report_sha(unsigned)
    return {"report": report, "markdown": render_public_report(report),
            "report_sha256": report["report_sha256"]}


__all__ = ["SNAPSHOT_SCHEMA", "RESULT_SCHEMA", "PUBLIC_SNAPSHOT_SCHEMA",
           "PUBLIC_SNAPSHOT_SCHEMA_V1",
           "build_snapshot", "save_snapshot", "load_snapshot", "prepare", "submit",
           "review_result", "render_reviewed", "build_public_snapshot",
           "save_public_snapshot", "load_public_snapshot", "prepare_public",
           "submit_public", "review_public_result", "render_public_reviewed"]
