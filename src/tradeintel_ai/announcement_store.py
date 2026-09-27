"""Shared, locked storage for imported announcement documents.

The web layer and the policy workflow both mutate the same policy store.  The
lock and path validation live here so the workflow does not import the web
server merely to save a document.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from .policy_documents import validate_document_store

ANNOUNCEMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class AnnouncementStoreError(ValueError):
    """A malformed or unavailable announcement store."""


class _FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.depth = 0
        self.handle = None
        self.thread_lock = threading.RLock()


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, _FileLock] = {}


def announcement_store_path(root: Path, policy_id: str) -> Path:
    if (not isinstance(policy_id, str) or
            not ANNOUNCEMENT_ID_PATTERN.fullmatch(policy_id) or
            ".." in policy_id):
        raise AnnouncementStoreError("policy_id 含非法字符或格式无效")
    directory = (Path(root) / ".local" / "announcement-docs").resolve()
    path = (directory / f"{policy_id}.json").resolve()
    if directory not in path.parents:
        raise AnnouncementStoreError("policy_id 路径越界")
    return path


@contextmanager
def announcement_lock(root: Path, policy_id: str):
    """Lock one policy store across threads and processes.

    The lock is re-entrant in one thread so a workflow can call the atomic
    writer after loading and validating the store.
    """
    path = announcement_store_path(root, policy_id)
    lock_path = path.with_suffix(".lock")
    key = str(lock_path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _FileLock(lock_path)
            _LOCKS[key] = lock
    with lock.thread_lock:
        with _LOCKS_GUARD:
            lock.depth += 1
            if lock.depth == 1:
                lock.path.parent.mkdir(parents=True, exist_ok=True)
                lock.handle = lock.path.open("a", encoding="utf-8")
                fcntl.flock(lock.handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            with _LOCKS_GUARD:
                lock.depth -= 1
                if lock.depth == 0 and lock.handle is not None:
                    fcntl.flock(lock.handle.fileno(), fcntl.LOCK_UN)
                    lock.handle.close()
                    lock.handle = None


def load_announcement_store(root: Path, policy_id: str) -> dict[str, Any]:
    path = announcement_store_path(root, policy_id)
    if not path.is_file():
        raise AnnouncementStoreError(f"该政策还没有导入任何公告：{policy_id}")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
        validate_document_store(store)
        return store
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AnnouncementStoreError("公告存储文件无法读取") from exc


def save_announcement_store(root: Path, policy_id: str,
                            store: dict[str, Any]) -> Path:
    """Atomically save a validated store; caller should hold announcement_lock."""
    validate_document_store(store)
    path = announcement_store_path(root, policy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent),
                                         prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(store, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
