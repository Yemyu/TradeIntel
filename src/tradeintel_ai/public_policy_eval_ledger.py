"""Independent append-only ledger for the isolated policy Q3 diagnostic.

The policy contract is a new experiment and must not inherit the historical
q1→q4 ordering or mutate the public four-question ledger.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid
from typing import Any, Iterator

SCHEMA = "public-policy-q3-ledger-v1"
RELATIVE = Path(".local/experiments/public-policy-q3/ledger.json")
LOCK_RELATIVE = Path(".local/experiments/public-policy-q3/ledger.lock")


class DuplicatePolicyRun(ValueError):
    pass


class PolicyLedgerError(ValueError):
    pass


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(root: Path) -> Path:
    return Path(root) / RELATIVE


def _lock_path(root: Path) -> Path:
    return Path(root) / LOCK_RELATIVE


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".policy-q3-ledger-",
                                         suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _empty() -> dict[str, Any]:
    return {"schema_version": SCHEMA, "events": []}


def load(root: Path) -> dict[str, Any]:
    path = _path(root)
    if not path.is_file():
        return _empty()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyLedgerError("政策Q3账本损坏，拒绝继续") from exc
    if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA
            or not isinstance(value.get("events"), list)):
        raise PolicyLedgerError("政策Q3账本schema不匹配")
    return value


@contextmanager
def locked(root: Path) -> Iterator[None]:
    path = _lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def claim(root: Path, *, base_key: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(base_key, str) or len(base_key) != 64:
        raise ValueError("政策Q3 base_key必须是64位摘要")
    if not isinstance(metadata, dict) or metadata.get("question_id") != "q3":
        raise ValueError("政策Q3领取记录必须绑定q3")
    with locked(root):
        ledger = load(root)
        active = [event for event in ledger["events"]
                  if event.get("base_key") == base_key]
        if active:
            raise DuplicatePolicyRun("同一政策Q3配置已有运行记录，禁止重跑")
        run_id = "policy-q3-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") \
            + "-" + uuid.uuid4().hex[:10]
        event = {"event": "started", "run_id": run_id, "base_key": base_key,
                 "question_id": "q3", "metadata": metadata, "started_at_utc": _utc()}
        ledger["events"].append(event)
        _atomic_write(_path(root), ledger)
        return event


def append(root: Path, *, run_id: str, event: str,
           payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id.startswith("policy-q3-"):
        raise ValueError("政策Q3 run_id无效")
    if not isinstance(event, str) or event == "started" or not event:
        raise ValueError("政策Q3追加事件无效")
    payload = dict(payload or {})
    if set(payload) & {"event", "run_id", "base_key", "question_id", "at_utc"}:
        raise ValueError("政策Q3事件载荷不能覆盖身份字段")
    with locked(root):
        ledger = load(root)
        starts = [item for item in ledger["events"]
                  if item.get("run_id") == run_id and item.get("event") == "started"]
        if len(starts) != 1:
            raise PolicyLedgerError("找不到政策Q3 started记录")
        latest = next((item for item in reversed(ledger["events"])
                       if item.get("run_id") == run_id), None)
        if latest and latest.get("event") in {"completed", "major_error_stop",
                                                "resolved_mark_failed"}:
            raise PolicyLedgerError("政策Q3运行已经终结")
        item = {"event": event, "run_id": run_id,
                "base_key": starts[0]["base_key"], "question_id": "q3",
                "at_utc": _utc(), **dict(payload or {})}
        ledger["events"].append(item)
        _atomic_write(_path(root), ledger)
        return item


__all__ = ["SCHEMA", "DuplicatePolicyRun", "PolicyLedgerError", "append", "claim", "load"]
