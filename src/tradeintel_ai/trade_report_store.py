"""Local, content-bound records for generic trade reports and their AI drafts."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .trade_explanation import observation_catalog, report_sha256
from .trade_explanation import PROTOCOL as V3_PROTOCOL
from .trade_explanation_v4 import (PROTOCOL as V4_PROTOCOL, build_snapshot,
                                   snapshot_sha256)


SCHEMA = "trade-report-record-v1"
LEGACY_PROTOCOLS = {"trade-data-explanation-v1", "trade-data-explanation-v2"}
NO_EXPLANATION_PROTOCOL = "none"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_LOCAL_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _folder(root: Path) -> Path:
    base = Path(root) / ".local"
    folder = base / "trade-reports"
    for path in (base, folder):
        if path.is_symlink():
            raise ValueError("报告记录目录不安全")
        path.mkdir(mode=0o700, exist_ok=True)
        if not path.is_dir():
            raise ValueError("报告记录目录无效")
    return folder


def _record_path(root: Path, report_id: str) -> Path:
    if not isinstance(report_id, str) or not _ID.fullmatch(report_id):
        raise ValueError("报告编号无效")
    return _folder(root) / f"{report_id}.json"


def _encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise ValueError("报告记录不存在") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
            raise ValueError("报告记录文件无效")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            data = stream.read(2_000_001)
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("报告记录损坏") from exc
    if not isinstance(value, dict):
        raise ValueError("报告记录无效")
    return value


def _protocol(record: dict[str, Any]) -> str:
    pinned = record.get("explanation_protocol")
    if pinned is not None:
        return pinned
    explanation = record.get("explanation")
    parsed = explanation.get("parsed") if isinstance(explanation, dict) else None
    if isinstance(parsed, dict) and parsed.get("schema_version") in LEGACY_PROTOCOLS:
        return parsed["schema_version"]
    return V3_PROTOCOL


def _verify(record: dict[str, Any], report_id: str) -> None:
    if record.get("schema_version") != SCHEMA or record.get("report_id") != report_id:
        raise ValueError("报告记录身份不符")
    report = record.get("report")
    if not isinstance(report, dict) or record.get("report_sha256") != report_sha256(report):
        raise ValueError("报告记录与原报告摘要不符")
    protocol = _protocol(record)
    if protocol not in LEGACY_PROTOCOLS | {V3_PROTOCOL, V4_PROTOCOL, NO_EXPLANATION_PROTOCOL}:
        raise ValueError("报告解释协议无效")
    explanation = record.get("explanation")
    if not isinstance(explanation, dict) or not isinstance(explanation.get("status"), str):
        raise ValueError("解释记录无效")
    if protocol == NO_EXPLANATION_PROTOCOL:
        if (report.get("kind") != "announcement-statistics-report-v1"
                or explanation.get("status") != "not_requested"
                or explanation.get("raw_text") is not None
                or explanation.get("parsed") is not None):
            raise ValueError("此报告类型不支持模型解读")
    if protocol == V4_PROTOCOL:
        snapshot = record.get("relation_snapshot")
        if (not isinstance(snapshot, dict) or
                record.get("relation_snapshot_sha256") != snapshot_sha256(snapshot) or
                snapshot != build_snapshot(report, record["report_sha256"])):
            raise ValueError("报告关系卡快照与原报告不符")
    raw = explanation.get("raw_text")
    if raw is not None and (not isinstance(raw, str) or
                            explanation.get("raw_sha256") != hashlib.sha256(raw.encode()).hexdigest()):
        raise ValueError("模型原答摘要不符")
    parsed = explanation.get("parsed")
    if parsed is not None and (not isinstance(parsed, dict) or
                               parsed.get("raw_sha256") != explanation.get("raw_sha256") or
                               parsed.get("report_sha256") != record["report_sha256"]):
        raise ValueError("模型解析结果与原答或报告不符")
    if parsed is not None and (parsed.get("schema_version") != protocol or
                               (protocol == V4_PROTOCOL and parsed.get("relation_snapshot_sha256") !=
                                record["relation_snapshot_sha256"])):
        raise ValueError("模型解析结果协议或关系卡不符")


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".trade-report-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(_encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _locked(root: Path, report_id: str) -> Iterator[Path]:
    path = _record_path(root, report_id)
    lock_path = path.with_suffix(".lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    with _LOCAL_LOCK:
        fd = os.open(lock_path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("报告锁文件无效")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield path
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def create_record(root: Path, report: dict[str, Any], *,
                  explanation_protocol: str = V3_PROTOCOL) -> dict[str, Any]:
    digest = report_sha256(report)
    if (report.get("kind") == "announcement-statistics-report-v1"
            and explanation_protocol != NO_EXPLANATION_PROTOCOL):
        raise ValueError("公告统计报告必须使用无模型解释协议")
    if explanation_protocol not in {V3_PROTOCOL, V4_PROTOCOL, NO_EXPLANATION_PROTOCOL}:
        raise ValueError("报告解释协议无效")
    if explanation_protocol == NO_EXPLANATION_PROTOCOL:
        if report.get("kind") != "announcement-statistics-report-v1":
            raise ValueError("无模型报告协议只允许用于公告统计报告")
        snapshot = None
    elif explanation_protocol == V3_PROTOCOL:
        observation_catalog(report)
        snapshot = None
    else:
        snapshot = build_snapshot(report, digest)
    report_id = uuid.uuid4().hex
    path = _record_path(root, report_id)
    record = {"schema_version": SCHEMA, "report_id": report_id,
              "report_sha256": digest, "created_at": _now(),
              "report": copy.deepcopy(report),
              "explanation_protocol": explanation_protocol,
              "explanation": {"status": "not_requested", "revision": 0,
                              "review_history": []}}
    if snapshot is not None:
        record["relation_snapshot"] = snapshot
        record["relation_snapshot_sha256"] = snapshot_sha256(snapshot)
    encoded_record = _encode(record)
    if len(encoded_record) > 2_000_000:
        raise ValueError("报告超出本地保存上限，请缩小月份或商品范围")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded_record)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return public_state(record)


def load_record(root: Path, report_id: str) -> dict[str, Any]:
    path = _record_path(root, report_id)
    record = _read(path)
    _verify(record, report_id)
    return record


def public_state(record: dict[str, Any]) -> dict[str, Any]:
    explanation = record["explanation"]
    safe = {key: copy.deepcopy(explanation[key]) for key in
            ("status", "revision", "model", "response_model", "raw_sha256",
             "parsed", "review", "error", "error_details", "usage") if key in explanation}
    protocol = _protocol(record)
    if protocol == V4_PROTOCOL:
        snapshot = record["relation_snapshot"]
        safe["observations"] = copy.deepcopy(snapshot["cards"])
        safe["available"] = bool(snapshot["eligible_card_ids"])
        if not safe["available"]:
            safe["availability_reason"] = "目前没有额外的关系可解释；数据报告仍可阅读。"
    elif protocol == V3_PROTOCOL:
        safe["observations"] = observation_catalog(record["report"])
        safe["available"] = True
    elif protocol == NO_EXPLANATION_PROTOCOL:
        safe["observations"] = []
        safe["available"] = False
        safe["availability_reason"] = "这类数据报告不提供模型解读。"
    else:
        # v1/v2 did not persist their original fact cards. Do not relabel
        # reconstructed v3 cards as evidence for those historical answers.
        safe["observations"] = []
        safe["available"] = False
        safe["availability_reason"] = "旧版模型解释未保存原始事实卡，请对照报告数据核查。"
    safe["protocol"] = protocol
    return {**copy.deepcopy(record["report"]),
            "report_id": record["report_id"], "report_sha256": record["report_sha256"],
            "explanation": safe,
            "ai_status": explanation["status"]}


def get_state(root: Path, report_id: str) -> dict[str, Any]:
    return public_state(load_record(root, report_id))


def _change(root: Path, report_id: str, edit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with _locked(root, report_id) as path:
        record = _read(path)
        _verify(record, report_id)
        edit(record)
        _verify(record, report_id)
        _atomic_write(path, record)
        return copy.deepcopy(record)


def claim_call(root: Path, report_id: str, digest: str, *, model: str,
               config_sha256: str, request_sha256: str,
               expected_protocol: str = V3_PROTOCOL,
               expected_relation_sha256: str | None = None) -> dict[str, Any]:
    def edit(record: dict[str, Any]) -> None:
        if record["report_sha256"] != digest:
            raise ValueError("报告摘要已变化，请重新打开报告")
        protocol = _protocol(record)
        if protocol == NO_EXPLANATION_PROTOCOL:
            raise ValueError("此报告类型不支持模型解读")
        if protocol != expected_protocol:
            raise ValueError("报告解释协议已变化，请重新打开报告")
        if protocol == V4_PROTOCOL and (record.get("relation_snapshot_sha256") != expected_relation_sha256 or
                                       not record["relation_snapshot"]["eligible_card_ids"]):
            raise ValueError("关系卡已变化或没有额外关系可解释")
        current = record["explanation"]
        if current["status"] != "not_requested":
            raise ValueError("这份报告的模型调用已领取或已有结果，不会重复调用")
        current.update(status="provider_call_started", started_at=_now(), model=model,
                       config_sha256=config_sha256, request_sha256=request_sha256)
    return _change(root, report_id, edit)


def save_raw(root: Path, report_id: str, raw: str, *, response_model: str | None,
             usage: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("模型没有返回正文")
    def edit(record: dict[str, Any]) -> None:
        current = record["explanation"]
        if current["status"] != "provider_call_started":
            raise ValueError("模型调用状态已变化")
        current.update(status="raw_saved", raw_text=raw,
                       raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                       response_model=response_model, usage=usage or {})
    return _change(root, report_id, edit)


def finish_parse(root: Path, report_id: str, parsed: dict[str, Any]) -> dict[str, Any]:
    def edit(record: dict[str, Any]) -> None:
        current = record["explanation"]
        if current["status"] != "raw_saved" or parsed.get("raw_sha256") != current.get("raw_sha256"):
            raise ValueError("模型原答状态或摘要已变化")
        current.update(status="needs_review", parsed=copy.deepcopy(parsed))
    return _change(root, report_id, edit)


def mark_error(root: Path, report_id: str, status: str, message: str,
               *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    if status not in {"failed", "unknown_outcome", "invalid_answer"}:
        raise ValueError("模型故障状态无效")
    def edit(record: dict[str, Any]) -> None:
        current = record["explanation"]
        if current["status"] not in {"provider_call_started", "raw_saved"}:
            raise ValueError("模型故障记录状态已变化")
        current.update(status=status, error=str(message)[:300],
                       error_details={key: value for key, value in (details or {}).items()
                                      if key in {"http_status", "code", "param", "category"}})
    return _change(root, report_id, edit)


def review(root: Path, report_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    def edit(record: dict[str, Any]) -> None:
        current = record["explanation"]
        if current["status"] not in {"needs_review", "reviewed", "rejected"}:
            raise ValueError("目前没有可审阅的模型解释")
        if (payload.get("report_sha256") != record["report_sha256"] or
                payload.get("raw_sha256") != current.get("raw_sha256") or
                type(payload.get("revision")) is not int or
                payload["revision"] != current["revision"]):
            raise ValueError("报告、原答或审阅修订已变化，请刷新")
        if type(payload.get("facts_checked")) is not bool or not payload["facts_checked"]:
            raise ValueError("请先核对事实再审阅")
        reviewer = payload.get("reviewer")
        if not isinstance(reviewer, str) or not 1 <= len(reviewer.strip()) <= 80:
            raise ValueError("审阅人无效")
        items = current["parsed"]["interpretations"]
        decisions = payload.get("decisions")
        if not isinstance(decisions, list) or len(decisions) != len(items):
            raise ValueError("请逐项审阅解释")
        clean = []
        for index, decision in enumerate(decisions):
            if not isinstance(decision, dict) or set(decision) != {"index", "verdict", "reason"}:
                raise ValueError("审阅项字段无效")
            if (type(decision["index"]) is not int or decision["index"] != index or
                    decision["verdict"] not in {"accept", "reject", "needs_revision"} or
                    not isinstance(decision["reason"], str) or
                    not 1 <= len(decision["reason"].strip()) <= 1000):
                raise ValueError("审阅项顺序、结论或理由无效")
            clean.append(copy.deepcopy(decision))
        accepted = [items[index] for index, decision in enumerate(clean)
                    if decision["verdict"] == "accept"]
        final = all(decision["verdict"] != "needs_revision" for decision in clean)
        status = "reviewed" if final and accepted else "rejected" if final else "needs_review"
        revision = current["revision"] + 1
        review_record = {"revision": revision, "reviewer": reviewer.strip(),
                         "facts_checked": True, "decisions": clean,
                         "report_sha256": record["report_sha256"],
                         "raw_sha256": current["raw_sha256"],
                         "created_at": _now(), "status": status}
        current["review_history"].append(review_record)
        current.update(status=status, revision=revision, review=review_record,
                       accepted=copy.deepcopy(accepted) if status == "reviewed" else [])
    return public_state(_change(root, report_id, edit))


__all__ = ["create_record", "load_record", "get_state", "public_state",
           "claim_call", "save_raw", "finish_parse", "mark_error", "review"]
