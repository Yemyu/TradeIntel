"""Small append-only ledger for the public four-question model evaluation.

This ledger is deliberately separate from the older bounded-provider ledgers.
It records an attempt before a provider request is made, so changing the
output directory cannot accidentally turn one question into two API calls.
Only standard-library primitives are used: an ``fcntl`` file lock and an
atomic ``os.replace`` write.  Secrets and response bodies never belong in the
ledger; the caller stores those in the run directory and records hashes here.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
from typing import Any, Iterator


LEDGER_SCHEMA = "public-brief-ledger-v1"
LEDGER_RELATIVE = Path(".local/experiments/public-brief-v1/provider-ledger.json")
LOCK_RELATIVE = Path(".local/experiments/public-brief-v1/provider-ledger.lock")
QUESTION_ORDER = ("q1", "q2", "q3", "q4")
REVIEW_CHECKS = ("structure", "facts", "relevance", "usefulness")
HISTORICAL_PREREQUISITE_EVENT = "historical_prerequisite"


def validate_review_checks(checks: object, verdict: str) -> None:
    if not isinstance(checks, dict) or set(checks) != set(REVIEW_CHECKS):
        raise LedgerStateError("审阅必须逐项提供structure/facts/relevance/usefulness")
    for item in checks.values():
        if (not isinstance(item, dict) or set(item) != {"passed", "reason"} or
                type(item["passed"]) is not bool or not isinstance(item["reason"], str) or
                not item["reason"].strip()):
            raise LedgerStateError("每项审阅必须提供布尔结论和具体理由")
    if (verdict == "pass") != all(item["passed"] for item in checks.values()):
        raise LedgerStateError("总判定与逐项检查不一致")
CONSUMING_EVENTS = {
    "started",
    "unknown_outcome",
    "transport_error",
    "invalid_response",
    "blocked_output_budget",
    "awaiting_semantic_review",
    "semantic_review",
    "semantic_review_passed",
    "major_error_stop",
    "completed",
    "resolved_mark_failed",
}


class DuplicatePublicRun(ValueError):
    """The same frozen question has already been attempted or is in flight."""


class LedgerStateError(ValueError):
    """The append-only ledger is malformed or the requested transition is invalid."""


def canonical_sha(value: object) -> str:
    """Return the stable SHA used for keys and binding records."""

    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ledger_path(root: Path) -> Path:
    return Path(root) / LEDGER_RELATIVE


def lock_path(root: Path) -> Path:
    return Path(root) / LOCK_RELATIVE


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".public-brief-ledger-",
                                         suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2,
                      sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _empty() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA, "events": []}


def load(root: Path) -> dict[str, Any]:
    path = ledger_path(root)
    if not path.is_file():
        return _empty()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerStateError("公共评测账本损坏，拒绝继续调用") from exc
    if not isinstance(value, dict) or value.get("schema_version") != LEDGER_SCHEMA:
        raise LedgerStateError("公共评测账本 schema 不匹配，拒绝覆盖")
    events = value.get("events")
    if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
        raise LedgerStateError("公共评测账本 events 不是对象列表")
    return value


def _save(root: Path, value: dict[str, Any]) -> None:
    _atomic_json(ledger_path(root), value)


@contextmanager
def locked(root: Path) -> Iterator[None]:
    """Acquire the cross-process lock used for every ledger transition."""

    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _latest_by_base_key(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        base_key = event.get("base_key")
        if isinstance(base_key, str) and base_key:
            latest[base_key] = event
    return latest


def _question_from_key(base_key: str) -> str | None:
    return next((qid for qid in QUESTION_ORDER if base_key.endswith(":" + qid)), None)


def make_base_key(package_manifest_sha256: str, provider_digest: str,
                  question_id: str) -> str:
    if question_id not in QUESTION_ORDER:
        raise ValueError("question_id 只能是 q1..q4")
    for value, label in ((package_manifest_sha256, "package manifest sha256"),
                         (provider_digest, "provider digest")):
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"{label} 必须是64位摘要")
        try:
            int(value, 16)
        except ValueError as exc:
            raise ValueError(f"{label} 不是十六进制摘要") from exc
    return f"{package_manifest_sha256}:{provider_digest}:{question_id}"


def claim(root: Path, *, base_key: str, metadata: dict[str, Any],
          retry_nonce: str | None = None) -> dict[str, Any]:
    """Persist ``started`` exactly once before a provider request.

    A retry can only happen after an explicit ``resolved_retry_authorized``
    event and must carry a new nonce.  The original base key remains visible,
    so a retry can never erase the first attempt from the audit trail.
    """

    if not isinstance(base_key, str) or base_key.count(":") != 2:
        raise ValueError("base_key 格式不正确")
    if not isinstance(metadata, dict):
        raise ValueError("claim metadata 必须是对象")
    qid = metadata.get("question_id")
    if qid != _question_from_key(base_key):
        raise ValueError("base_key 与 question_id 不一致")
    with locked(root):
        ledger = load(root)
        # Order checks and claiming a question are one locked operation.
        prefix = base_key.rsplit(":", 1)[0]
        anchors = [e for e in ledger["events"]
                   if e.get("event") == HISTORICAL_PREREQUISITE_EVENT
                   and e.get("target_prefix") == prefix]
        if anchors:
            if len(anchors) != 1 or qid == "q1":
                raise LedgerStateError("历史前置配置不能重新领取Q1或存在多个前置记录")
            if metadata.get("freeze_sha256") != anchors[0].get("target_freeze_sha256"):
                raise LedgerStateError("领取配置与历史前置目标冻结不一致")
        prior_starts = [e for e in ledger["events"] if e.get("event") == "started"
                        and e.get("base_key", "").rsplit(":", 1)[0] == prefix]
        config_sha = metadata.get("config_sha256")
        if config_sha and any(e.get("metadata", {}).get("config_sha256") != config_sha or
                              e.get("metadata", {}).get("freeze_sha256") != metadata.get("freeze_sha256")
                              for e in prior_starts):
            raise LedgerStateError("同一配置的四题不能中途更改模型参数")
        require_previous_review(root, base_key=base_key)
        latest = _latest_by_base_key(ledger["events"]).get(base_key)
        if latest is not None:
            if latest.get("event") != "resolved_retry_authorized":
                raise DuplicatePublicRun("同一题已有进行中、未知结果或已完成记录；禁止换目录重跑")
            if not isinstance(retry_nonce, str) or not retry_nonce.strip():
                raise DuplicatePublicRun("只有人工授权重试才可再次调用，必须提供 retry_nonce")
            # A nonce is a one-time explicit decision, not a free retry switch.
            if any(event.get("base_key") == base_key and
                   event.get("retry_nonce") == retry_nonce
                   for event in ledger["events"]):
                raise DuplicatePublicRun("该人工重试 nonce 已经使用")
        elif retry_nonce is not None:
            raise LedgerStateError("没有 unknown_outcome，不能凭空创建重试")
        run_id = "pub-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]
        event = {
            "event": "started",
            "run_id": run_id,
            "base_key": base_key,
            "question_id": qid,
            "metadata": metadata,
            "started_at_utc": _utc(),
        }
        if retry_nonce is not None:
            event["retry_nonce"] = retry_nonce
        ledger["events"].append(event)
        _save(root, ledger)
        return event


def append(root: Path, *, run_id: str, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id.startswith("pub-"):
        raise ValueError("run_id 不正确")
    if not isinstance(event, str) or not event or event == "started":
        raise ValueError("append 需要非 started 事件")
    payload = dict(payload or {})
    if set(payload) & {"event", "run_id", "base_key", "question_id", "at_utc"}:
        raise LedgerStateError("事件payload不得覆盖账本身份")
    with locked(root):
        ledger = load(root)
        starts = [item for item in ledger["events"]
                  if item.get("run_id") == run_id and item.get("event") == "started"]
        if len(starts) != 1:
            raise LedgerStateError("找不到唯一的 started 记录")
        latest = next((item for item in reversed(ledger["events"])
                       if item.get("run_id") == run_id), None)
        if latest and latest.get("event") in {"completed", "major_error_stop", "resolved_mark_failed"}:
            raise LedgerStateError("运行已经终结，不能追加事件")
        item = {"event": event, "run_id": run_id,
                "base_key": starts[0]["base_key"], "question_id": starts[0]["question_id"],
                "at_utc": _utc(), **payload}
        ledger["events"].append(item)
        _save(root, ledger)
        return item


def _validate_historical_event(root: Path, event: dict[str, Any],
                               *, target_prefix: str, question_id: str) -> None:
    """Recheck the files named by a historical prerequisite before each claim."""
    if event.get("event") != HISTORICAL_PREREQUISITE_EVENT:
        raise LedgerStateError("历史前置事件类型不正确")
    if event.get("target_prefix") != target_prefix or event.get("question_id") != question_id:
        raise LedgerStateError("历史前置事件与目标题目不匹配")
    if event.get("verdict") not in {"pass", "minor_error"}:
        raise LedgerStateError("历史前置事件的审阅不是可继续状态")
    try:
        validate_review_checks(event.get("checks"), event["verdict"])
    except (KeyError, ValueError) as exc:
        raise LedgerStateError("历史前置事件的逐项审阅无效") from exc
    paths = event.get("artifact_paths")
    hashes = event.get("artifact_hashes")
    required = {"source_run", "source_raw", "source_freeze", "source_manifest",
                "target_freeze", "target_manifest", "source_review", "source_metadata"}
    for qid in QUESTION_ORDER:
        required.update({f"source_request_{qid}", f"source_host_{qid}",
                         f"target_request_{qid}", f"target_host_{qid}"})
    if (not isinstance(paths, dict) or set(paths) != required or
            not isinstance(hashes, dict) or set(hashes) != required):
        raise LedgerStateError("历史前置事件缺少完整的材料路径或摘要")
    for name in sorted(required):
        raw_path = paths[name]
        expected = hashes[name]
        if (not isinstance(raw_path, str) or not raw_path.startswith("/") or
                not isinstance(expected, str) or len(expected) != 64):
            raise LedgerStateError("历史前置事件路径或摘要格式无效")
        path = Path(raw_path)
        if path.is_symlink() or not path.is_file():
            raise LedgerStateError("历史前置材料缺失或是符号链接：" + name)
        try:
            actual = file_sha256(path)
        except (OSError, ValueError) as exc:
            raise LedgerStateError("历史前置材料缺失：" + name) from exc
        if actual != expected:
            raise LedgerStateError("历史前置材料摘要已变化：" + name)
    try:
        source_run = json.loads(Path(paths["source_run"]).read_text(encoding="utf-8"))
        source_freeze = json.loads(Path(paths["source_freeze"]).read_text(encoding="utf-8"))
        target_freeze = json.loads(Path(paths["target_freeze"]).read_text(encoding="utf-8"))
        source_review = json.loads(Path(paths["source_review"]).read_text(encoding="utf-8"))
        source_metadata = json.loads(Path(paths["source_metadata"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerStateError("历史前置JSON材料不可读取") from exc
    if (source_run.get("run_id") != event.get("source_run_id") or
            source_run.get("question_id") != "q1" or
            source_run.get("status") != "blocked_output_budget" or
            source_run.get("raw_sha256") != hashes["source_raw"]):
        raise LedgerStateError("历史前置的源运行不是绑定的Q1预算结果")
    if source_run.get("response_metadata") != source_metadata or source_metadata.get("finish_reason") != "stop":
        raise LedgerStateError("历史前置响应元数据不一致或响应未完整结束")
    if (canonical_sha(source_freeze) != event.get("source_freeze_sha256") or
            hashes["source_manifest"] != event.get("source_manifest_sha256") or
            source_freeze.get("package_manifest_sha256") != event.get("source_manifest_sha256") or
            source_freeze.get("params", {}).get("budget_protocol", "v2") != "v2"):
        raise LedgerStateError("历史前置源冻结与摘要不一致")
    if (canonical_sha(target_freeze) != event.get("target_freeze_sha256") or
            hashes["target_manifest"] != event.get("target_manifest_sha256") or
            target_freeze.get("package_manifest_sha256") != event.get("target_manifest_sha256") or
            target_freeze.get("params", {}).get("budget_protocol") != "v3"):
        raise LedgerStateError("历史前置目标冻结与v3摘要不一致")
    for key in ("model_id", "base_url", "request_params", "reasoning_effort"):
        if source_freeze.get("provider", {}).get(key) != target_freeze.get("provider", {}).get(key):
            raise LedgerStateError("历史前置源与目标模型参数不同：" + key)
    for key in ("temperature", "max_tokens", "thinking", "reasoning_effort"):
        if source_freeze.get("params", {}).get(key) != target_freeze.get("params", {}).get(key):
            raise LedgerStateError("历史前置源与目标生成参数不同：" + key)
    for qid in QUESTION_ORDER:
        for kind in ("request", "host"):
            if hashes[f"source_{kind}_{qid}"] != hashes[f"target_{kind}_{qid}"]:
                raise LedgerStateError("历史前置源与目标题目材料不同：" + qid)
    if (source_review.get("schema_version") != "public-brief-historical-review-v1" or
            source_review.get("source_run_id") != event.get("source_run_id") or
            source_review.get("verdict") != event.get("verdict") or
            source_review.get("checks") != event.get("checks")):
        raise LedgerStateError("历史前置审阅文件与登记事件不一致")
    if event.get("review_sha256") != hashes["source_review"]:
        raise LedgerStateError("历史前置审阅摘要与文件不一致")
    ledger = load(root)
    source_events = [item for item in ledger["events"]
                     if item.get("run_id") == event.get("source_run_id")]
    source_started = [item for item in source_events if item.get("event") == "started"]
    source_terminal = [item for item in source_events if item.get("event") == "blocked_output_budget"]
    source_run_dir = str(Path(paths["source_run"]).resolve().parent.parent)
    if (len(source_started) != 1 or len(source_terminal) != 1 or
            source_events[-1].get("event") != "blocked_output_budget" or
            source_started[0].get("metadata", {}).get("freeze_sha256") != event.get("source_freeze_sha256") or
            source_run.get("freeze_sha256") != event.get("source_freeze_sha256") or
            source_started[0].get("metadata", {}).get("output_dir") != source_run_dir or
            source_terminal[0].get("raw_sha256") != hashes["source_raw"]):
        raise LedgerStateError("历史前置源运行未在当前账本中完整登记")
    if event.get("target_prefix") != (str(event.get("target_manifest_sha256")) + ":" +
                                      str(event.get("target_provider_digest"))):
        raise LedgerStateError("历史前置目标配置前缀不一致")


def register_historical_prerequisite(root: Path, *, target_prefix: str,
                                     question_id: str, record: dict[str, Any]) -> dict[str, Any]:
    """Register one immutable, non-consuming historical prerequisite.

    It is deliberately not a run and does not unlock q1.  It only supplies an
    auditable predecessor for the normal q2→q4 order check.
    """
    if not isinstance(target_prefix, str) or target_prefix.count(":") != 1:
        raise ValueError("target_prefix 格式不正确")
    if question_id != "q1":
        raise ValueError("历史前置目前只允许登记q1")
    if not isinstance(record, dict):
        raise ValueError("历史前置记录必须是对象")
    if set(record) & {"event", "target_prefix", "question_id", "at_utc", "run_id", "base_key"}:
        raise ValueError("历史前置记录不得覆盖账本身份字段")
    with locked(root):
        ledger = load(root)
        matches = [item for item in ledger["events"]
                   if item.get("event") == HISTORICAL_PREREQUISITE_EVENT and
                   item.get("target_prefix") == target_prefix and
                   item.get("question_id") == question_id]
        candidate = {"event": HISTORICAL_PREREQUISITE_EVENT,
                     "target_prefix": target_prefix, "question_id": question_id,
                     **record}
        if matches:
            comparable = lambda item: {key: value for key, value in item.items()
                                       if key != "at_utc"}
            if (len(matches) == 1 and
                    canonical_sha(comparable(matches[0])) == canonical_sha(candidate)):
                _validate_historical_event(root, matches[0], target_prefix=target_prefix,
                                           question_id=question_id)
                return matches[0]
            raise DuplicatePublicRun("同一目标配置已有冲突的历史前置记录")
        if any(e.get("base_key", "").startswith(target_prefix + ":") for e in ledger["events"]):
            raise LedgerStateError("目标配置已经有运行记录，不能补登记历史前置")
        _validate_historical_event(root, candidate, target_prefix=target_prefix,
                                   question_id=question_id)
        candidate["at_utc"] = _utc()
        ledger["events"].append(candidate)
        _save(root, ledger)
        return candidate


def latest_for_run(root: Path, run_id: str) -> dict[str, Any] | None:
    ledger = load(root)
    return next((item for item in reversed(ledger["events"])
                 if item.get("run_id") == run_id), None)


def latest_for_base_key(root: Path, base_key: str) -> dict[str, Any] | None:
    ledger = load(root)
    return _latest_by_base_key(ledger["events"]).get(base_key)


def resolve_unknown(root: Path, *, run_id: str, resolution: str,
                    decided_by: str, note: str = "") -> dict[str, Any]:
    if resolution not in {"resolved_retry_authorized", "resolved_mark_failed"}:
        raise ValueError("resolution 必须是 resolved_retry_authorized 或 resolved_mark_failed")
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("人工决定者不能为空")
    with locked(root):
        ledger = load(root)
        matching = [item for item in ledger["events"] if item.get("run_id") == run_id]
        if not matching or matching[-1].get("event") != "unknown_outcome":
            raise LedgerStateError("只有 unknown_outcome 才能进入人工决定")
        latest = matching[-1]
        item = {
            "event": resolution, "run_id": run_id,
            "base_key": latest["base_key"], "question_id": latest["question_id"],
            "decided_by": decided_by.strip(), "note": note,
            "at_utc": _utc(),
        }
        ledger["events"].append(item)
        _save(root, ledger)
        return item


def record_review(root: Path, *, run_id: str, raw_sha256: str,
                  verdict: str, reviewer: str, ai_assisted: bool = False,
                  note: str = "", checks: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bind a semantic review to the exact raw response before opening next q."""

    if verdict not in {"pass", "minor_error", "major_error"}:
        raise ValueError("verdict 必须是 pass、minor_error 或 major_error")
    validate_review_checks(checks, verdict)
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("reviewer 不能为空")
    if not isinstance(raw_sha256, str) or len(raw_sha256) != 64:
        raise ValueError("raw_sha256 必须是64位摘要")
    with locked(root):
        ledger = load(root)
        matching = [item for item in ledger["events"] if item.get("run_id") == run_id]
        if not matching or matching[-1].get("event") != "awaiting_semantic_review":
            raise LedgerStateError("该运行还没有待审阅的结构化结果")
        latest = matching[-1]
        expected = latest.get("raw_sha256")
        if expected != raw_sha256:
            raise LedgerStateError("原答摘要已变化，拒绝写入审阅")
        starts = [item for item in matching if item.get("event") == "started"]
        if len(starts) != 1 or not starts[0].get("metadata", {}).get("output_dir"):
            raise LedgerStateError("缺少唯一运行产物路径")
        qdir = Path(starts[0]["metadata"]["output_dir"]) / latest["question_id"]
        try:
            run = json.loads((qdir / "run.json").read_text(encoding="utf-8"))
            validation = json.loads((qdir / "validation.json").read_text(encoding="utf-8"))
            actual = file_sha256(qdir / "raw-response.txt")
        except (OSError, ValueError) as exc:
            raise LedgerStateError("审阅产物缺失或不可读取") from exc
        if (actual != expected or run.get("run_id") != run_id or
                run.get("raw_sha256") != actual or validation.get("raw_sha256") != actual or
                validation.get("status") != "manual_review_required" or
                not validation.get("interpretations")):
            raise LedgerStateError("原答或结构验收产物不一致，拒绝写入审阅")
        event = {
            "event": "semantic_review", "run_id": run_id,
            "base_key": latest["base_key"], "question_id": latest["question_id"],
            "raw_sha256": raw_sha256, "verdict": verdict,
            "reviewer": reviewer.strip(), "ai_assisted": bool(ai_assisted),
            "note": note, "at_utc": _utc(),
            "checks": checks,
        }
        ledger["events"].append(event)
        if verdict == "major_error":
            ledger["events"].append({**event, "event": "major_error_stop", "at_utc": _utc()})
        else:
            ledger["events"].append({**event, "event": "semantic_review_passed", "at_utc": _utc()})
        _save(root, ledger)
        return event


def require_previous_review(root: Path, *, base_key: str) -> None:
    """Require every earlier question to have a non-major semantic review."""

    qid = _question_from_key(base_key)
    if qid is None:
        raise ValueError("base_key 缺少合法题号")
    index = QUESTION_ORDER.index(qid)
    if index == 0:
        return
    ledger = load(root)
    latest = _latest_by_base_key(ledger["events"])
    for previous in QUESTION_ORDER[:index]:
        event = latest.get(base_key[:-len(qid)] + previous)
        target_prefix = base_key.rsplit(":", 1)[0]
        historical = [item for item in ledger["events"]
                      if item.get("event") == HISTORICAL_PREREQUISITE_EVENT and
                      item.get("target_prefix") == target_prefix and
                      item.get("question_id") == previous]
        if historical and event is None:
            if len(historical) != 1:
                raise LedgerStateError(f"{qid} 的 {previous} 历史前置记录冲突")
            _validate_historical_event(root, historical[0],
                                       target_prefix=target_prefix, question_id=previous)
            continue
        if not event or event.get("event") != "semantic_review_passed":
            raise LedgerStateError(f"{qid} 前必须先完成 {previous} 的语义审阅")
        validate_review_checks(event.get("checks"), event.get("verdict"))
        start = next((e for e in ledger["events"] if e.get("event") == "started"
                      and e.get("run_id") == event.get("run_id")), None)
        if not start or not start.get("metadata", {}).get("output_dir"):
            raise LedgerStateError("前题缺少产物路径")
        raw = Path(start["metadata"]["output_dir"]) / previous / "raw-response.txt"
        if not raw.is_file() or file_sha256(raw) != event.get("raw_sha256"):
            raise LedgerStateError("前题原答发生变化，停止后续调用")


__all__ = [
    "CONSUMING_EVENTS", "DuplicatePublicRun", "HISTORICAL_PREREQUISITE_EVENT",
    "LEDGER_SCHEMA", "LedgerStateError",
    "append", "canonical_sha", "claim", "file_sha256", "latest_for_base_key",
    "latest_for_run", "ledger_path", "load", "make_base_key", "record_review",
    "register_historical_prerequisite", "require_previous_review", "resolve_unknown",
]
