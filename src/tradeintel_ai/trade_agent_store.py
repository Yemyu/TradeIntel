"""Small local session ledger for at-most-once trade-agent turns."""
from __future__ import annotations

import copy
import fcntl
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
from typing import Any, Iterator


_ID = re.compile(r"[0-9a-f]{32}\Z")
_LOCAL_LOCK = threading.RLock()


def _folder(root: Path) -> Path:
    base = Path(root) / ".local"
    folder = base / "trade-agent-sessions"
    for part in (base, folder):
        if part.is_symlink():
            raise ValueError("会话目录不安全")
        part.mkdir(mode=0o700, exist_ok=True)
    return folder


def _path(root: Path, session_id: str) -> Path:
    if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
        raise ValueError("会话编号无效")
    return _folder(root) / f"{session_id}.json"


@contextmanager
def _locked(root: Path, session_id: str) -> Iterator[Path]:
    path = _path(root, session_id)
    lock = path.with_suffix(".lock")
    with _LOCAL_LOCK:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield path
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _read(path: Path) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
            raise ValueError("会话文件无效")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            state = json.loads(stream.read(1_000_001))
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(state, dict) or state.get("schema") != "trade-agent-session-v1":
        raise ValueError("会话记录损坏")
    return state


def _write(path: Path, state: dict[str, Any]) -> None:
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 1_000_000:
        raise ValueError("会话记录已满，请创建新会话")
    fd, temporary = tempfile.mkstemp(prefix=".agent-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_session(root: Path, session_id: str) -> dict[str, Any]:
    try:
        return copy.deepcopy(_read(_path(root, session_id)))
    except FileNotFoundError as exc:
        raise ValueError("会话不存在") from exc


def public_session(state: dict[str, Any]) -> dict[str, Any]:
    """One public projection for HTTP reads, fresh turns and idempotent replay.

    Old completed turns contained unreviewed model prose. Keep their on-disk
    audit unchanged, but do not republish that prose after the boundary fix.
    """
    safe = copy.deepcopy(state)
    for turn in safe["turns"]:
        if turn.get("status") == "completed" and turn.get("message_kind") != "program_summary_v1":
            turn["message"] = "旧版模型文字未经本规则核验，已隐藏；数据报告仍可查看。"
            turn["message_kind"] = "legacy_unreviewed_hidden"
            turn["model_note"] = "旧版未审核解释不对外展示。"
    return {"session_id": safe["session_id"], "scope": safe.get("scope"),
            "turns": safe["turns"]}


def begin_turn(root: Path, session_id: str | None, request_id: str,
               question: str) -> tuple[dict[str, Any], bool]:
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        raise ValueError("请求编号无效")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ValueError("请输入1至2000字的问题")
    # The first request ID is also the session ID, so retrying a lost first
    # HTTP response remains idempotent even before the browser learns the SID.
    sid = session_id or request_id
    with _locked(root, sid) as path:
        if path.exists():
            state = _read(path)
        elif session_id is not None:
            raise ValueError("会话不存在")
        else:
            state = {"schema": "trade-agent-session-v1", "session_id": sid,
                     "created_at": datetime.now(timezone.utc).isoformat(), "turns": [],
                     "scope": None}
        for turn in state["turns"]:
            if turn["request_id"] == request_id:
                if turn["question"] != question.strip():
                    raise ValueError("同一请求编号不能改问题")
                return state, False
        if state["turns"] and state["turns"][-1]["status"] == "in_progress":
            raise ValueError("上一轮模型结果未知；请先查看会话，不自动重新发起请求")
        if len(state["turns"]) >= 20:
            raise ValueError("当前会话已满，请创建新会话")
        state["turns"].append({"request_id": request_id, "question": question.strip(),
                               "status": "in_progress", "started_at": datetime.now(timezone.utc).isoformat(),
                               "execution_metrics": {"schema": "trade-execution-metrics-v1", "attempts": []},
                               "tool_calls": [], "report_ids": []})
        _write(path, state)
        return copy.deepcopy(state), True


def record_attempt(root: Path, session_id: str, request_id: str,
                   response: dict | None = None, *, configuration: dict | None = None,
                   failure: dict | None = None) -> None:
    """Write before provider entry; interruption leaves an explicit started event."""
    with _locked(root, session_id) as path:
        state = _read(path)
        turn = state["turns"][-1]
        if turn["request_id"] != request_id or turn["status"] != "in_progress":
            raise ValueError("请求状态已变化")
        events = turn["execution_metrics"]["attempts"]
        if response is None and failure is None:
            if events and events[-1]["status"] == "started":
                raise ValueError("上次调用结果未知，不允许重复领取")
            events.append({"status": "started", **(configuration or {})})
        else:
            if not events or events[-1]["status"] != "started":
                raise ValueError("没有待完成的调用")
            events[-1].update(response or failure or {})
            events[-1]["status"] = "response_received" if response is not None else "failed_or_unknown"
        _write(path, state)


def finish_turn(root: Path, session_id: str, request_id: str, result: dict[str, Any],
                scope: dict[str, Any] | None = None) -> dict[str, Any]:
    with _locked(root, session_id) as path:
        state = _read(path)
        turn = state["turns"][-1]
        if turn["request_id"] != request_id or turn["status"] != "in_progress":
            raise ValueError("请求状态已变化")
        if result["status"] not in {"completed", "needs_clarification", "failed", "unknown_outcome"}:
            raise ValueError("终态无效")
        turn.update(result)
        if "execution_metrics" in turn:
            from .trade_agent_metrics import summarize_metrics
            turn["execution_metrics"]["tools_executed"] = len(turn.get("tool_calls", []))
            turn["execution_metrics"] = summarize_metrics(turn["execution_metrics"])
        turn["finished_at"] = datetime.now(timezone.utc).isoformat()
        if scope is not None and result["status"] == "completed":
            state["scope"] = scope
        _write(path, state)
        return copy.deepcopy(state)
