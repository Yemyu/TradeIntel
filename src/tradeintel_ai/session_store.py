"""Local single-user session and research-task persistence (offline).

Sessions persist messages, the current request, the bound policy/data
version, the request digest, a revision counter and every run id, so a page
reload or process restart restores the exact state.

Concurrency (review F7): session IDs are random UUIDs, strictly validated
against path traversal, and creation never overwrites.  Every mutation runs
under an advisory file lock and re-checks the on-disk revision against the
revision the caller loaded (optimistic locking): a stale in-memory copy is
rejected with :class:`StaleSessionError` instead of silently dropping the
other writer's changes.  Opening a generation task is an atomic claim under
the same lock, so a repeated click cannot create two live tasks.

Follow-ups (review F8): ``resolve_followup`` NEVER writes the confirmed
request.  It returns a ``candidate_request`` plus change summary; applying it
requires an explicit ``confirm_request`` after scope re-verification.  Multi
month/multi product questions keep the complete requirement list and ask for
clarification instead of silently picking the last value.

Research tasks carry an explicit state machine (``received → … → exportable``
plus ``failed`` and ``unknown_outcome``).  A task is deduplicated by
``request_digest + policy_version + data_version + model + prompt digest``; a
task whose state is ``generation_started`` without a saved response can never
authorize a second billable call -- it surfaces as ``unknown_outcome`` and
needs an explicit human decision.  Retrying always rebinds to the ORIGINAL
task's request, never to whatever the session currently holds.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

SCHEMA = "research-session-v1"
TASK_SCHEMA = "research-task-v2"

STATES = ("received", "awaiting_confirmation", "evidence_ready", "generation_started",
          "response_saved", "needs_review", "reviewed", "exportable",
          "failed", "unknown_outcome")
TRANSITIONS: dict[str, set[str]] = {
    "received": {"awaiting_confirmation", "evidence_ready", "failed"},
    "awaiting_confirmation": {"evidence_ready", "failed"},
    "evidence_ready": {"generation_started", "failed"},
    "generation_started": {"response_saved", "unknown_outcome", "failed"},
    "response_saved": {"needs_review"},
    "needs_review": {"reviewed", "exportable"},
    "reviewed": {"exportable"},
    "exportable": set(),
    "failed": set(),
    # unknown_outcome is terminal in the map on purpose: only an explicit
    # human decision via resolve_unknown_outcome may close or retry it.
    "unknown_outcome": set(),
}
_TERMINAL_WITHOUT_RESPONSE = ("failed", "unknown_outcome")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SESSION_ID = re.compile(r"^session-[0-9a-f]{16}$")
_PROPOSAL_ID = re.compile(r"^proposal-[0-9a-f]{16}$")


class StaleSessionError(ValueError):
    """Raised when the on-disk session is newer than the caller's copy."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _review_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def sessions_dir(root: Path) -> Path:
    return Path(root) / ".local" / "sessions"


def _session_path(root: Path, session_id: str) -> Path:
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise ValueError(f"invalid session id format: {session_id!r}")
    path = (sessions_dir(root) / f"{session_id}.json").resolve()
    if sessions_dir(root).resolve() not in path.parents:
        raise ValueError("session path escapes the sessions directory")
    return path


class _FileLock:
    """Re-entrant per-key lock: flock across processes, RLock across threads."""

    def __init__(self, path: Path):
        self.path = path
        self.depth = 0
        self.handle = None
        self.thread_lock = threading.RLock()


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, _FileLock] = {}


@contextmanager
def _session_lock(root: Path, session_id: str):
    """Advisory cross-process lock for one session's read-check-write cycle.

    Re-entrant within a thread (a mutator may call another mutator or the
    writer), mutually exclusive between threads of one process and between
    processes via flock.
    """
    directory = sessions_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    key = str(directory / f"{session_id}.lock")
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _FileLock(Path(key))
            _LOCKS[key] = lock
    with lock.thread_lock:
        with _LOCKS_GUARD:
            lock.depth += 1
            if lock.depth == 1:
                lock.handle = open(lock.path, "w", encoding="utf-8")
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


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_session(root: Path, *, title: str | None = None) -> dict[str, Any]:
    """Create a new session file; never overwrite an existing one."""
    session_id = "session-" + uuid.uuid4().hex[:16]
    path = _session_path(root, session_id)
    sessions_dir(root).mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"session file already exists: {session_id}")
    session = {"schema_version": SCHEMA, "session_id": session_id,
               "title": title or "未命名研究会话",
               "created_at": _now(), "updated_at": _now(),
               "messages": [], "current_request": None,
               "policy_version": None, "data_version": None,
               "policy_binding": None,
               "request_context": None,
               "request_digest": None, "revision": 0, "run_ids": [],
               "tasks": {}, "task_counter": 0, "scope_proposals": {},
               "_loaded_revision": 0}
    with _session_lock(root, session_id):
        if path.exists():
            raise ValueError(f"session file already exists: {session_id}")
        _atomic_write_json(path, _stripped(session))
    return session


def _stripped(session: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in session.items() if key != "_loaded_revision"}


def save_session(root: Path, session: dict[str, Any]) -> None:
    """Persist the session under the advisory lock with a revision check.

    Raises :class:`StaleSessionError` when the on-disk revision does not match
    the revision the caller loaded; the caller must reload and reapply.
    """
    if not isinstance(session, dict) or session.get("schema_version") != SCHEMA:
        raise ValueError("invalid session schema")
    session_id = session.get("session_id")
    path = _session_path(root, session_id)
    session["updated_at"] = _now()
    with _session_lock(root, session_id):
        if path.exists():
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            if int(on_disk.get("revision", -1)) != int(session.get("_loaded_revision", -1)):
                raise StaleSessionError(
                    "session changed on disk since it was loaded; reload before saving")
        _atomic_write_json(path, _stripped(session))
        session["_loaded_revision"] = session["revision"]


def load_session(root: Path, session_id: str) -> dict[str, Any]:
    path = _session_path(root, session_id)
    if not path.is_file():
        raise ValueError(f"unknown session: {session_id}")
    session = json.loads(path.read_text(encoding="utf-8"))
    if session.get("schema_version") != SCHEMA:
        raise ValueError("session file schema mismatch")
    session["_loaded_revision"] = int(session.get("revision", 0))
    return session


def append_message(root: Path, session: dict[str, Any], role: str, content: str) -> dict[str, Any]:
    if role not in ("user", "assistant", "system"):
        raise ValueError("message role must be user/assistant/system")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("message content must be non-empty text")
    with _session_lock(root, session["session_id"]):
        session["messages"].append({"role": role, "content": content, "at": _now()})
        session["revision"] += 1
        save_session(root, session)
    return session


def request_digest(request: dict[str, Any]) -> str:
    if isinstance(request, dict) and request.get("schema_version") == "analysis-request-v1":
        from .analysis_request import request_digest as analysis_digest
        return analysis_digest(request)
    keys = ("policy_id", "month", "product", "products", "focus")
    payload = {key: request.get(key) for key in keys}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _validate_policy_binding(binding: Any, *, request_policy_id: str) -> dict[str, Any] | None:
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise ValueError("policy_binding must be an object")
    required = {"policy_id", "doc_version", "candidate_digest"}
    optional = {"data_version", "status", "coverage_month", "coverage_status",
                "trade_coverage_digest", "requested_codes", "coverage_scope"}
    if set(binding) - (required | optional) or not required <= set(binding):
        raise ValueError("policy_binding must contain policy_id/doc_version/candidate_digest")
    if binding.get("policy_id") != request_policy_id:
        raise ValueError("policy_binding policy_id must match request policy_id")
    for name in ("policy_id", "doc_version", "candidate_digest"):
        if not isinstance(binding.get(name), str) or not binding[name].strip():
            raise ValueError(f"policy_binding {name} must be non-empty text")
        if "data_version" in binding and binding["data_version"] is not None \
            and (not isinstance(binding["data_version"], str) or not binding["data_version"].strip()):
            raise ValueError("policy_binding data_version must be non-empty when supplied")
    for name in ("coverage_month", "coverage_status", "trade_coverage_digest"):
        if name in binding and binding[name] is not None \
                and (not isinstance(binding[name], str) or not binding[name].strip()):
            raise ValueError(f"policy_binding {name} must be non-empty when supplied")
    if "requested_codes" in binding:
        codes = binding["requested_codes"]
        if (not isinstance(codes, list) or not codes or len(codes) != len(set(codes))
                or any(not isinstance(code, str) or not re.fullmatch(r"\d{8}", code)
                       for code in codes)):
            raise ValueError("policy_binding requested_codes must be a unique HTS8 list")
    if "coverage_scope" in binding and binding["coverage_scope"] not in ("full", "selected"):
        raise ValueError("policy_binding coverage_scope is invalid")
    return deepcopy(binding)


def _validate_request_context(context: Any, request: dict[str, Any]) -> dict[str, Any] | None:
    if context is None:
        return None
    if not isinstance(context, dict) or context.get("schema_version") != "public-request-context-v1":
        raise ValueError("request_context schema is invalid")
    required = {"schema_version", "kind", "parent_request_digest", "parent_data_version",
                "parent_task_id", "parent_window", "selected_products", "summary"}
    if set(context) != required:
        raise ValueError("request_context fields are invalid")
    if context.get("kind") != "prior_program_report":
        raise ValueError("request_context kind is invalid")
    if (not isinstance(context.get("parent_request_digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", context["parent_request_digest"])):
        raise ValueError("request_context parent digest is invalid")
    if context.get("parent_data_version") != request.get("data_version"):
        raise ValueError("request_context data version must match request")
    if (not isinstance(context.get("parent_task_id"), str)
            or not context["parent_task_id"].strip()):
        raise ValueError("request_context parent task is required")
    if (not isinstance(context.get("selected_products"), list)
            or not context["selected_products"]
            or any(not isinstance(code, str) or not re.fullmatch(r"\d{8}", code)
                   for code in context["selected_products"])):
        raise ValueError("request_context selected_products is invalid")
    if not isinstance(context.get("parent_window"), dict) or not isinstance(context.get("summary"), list):
        raise ValueError("request_context window or summary is invalid")
    if len(context["summary"]) > 8:
        raise ValueError("request_context summary is too long")
    for item in context["summary"]:
        if (not isinstance(item, dict)
                or set(item) != {"observation_id", "kind", "period", "fact_sentence"}
                or not all(isinstance(item[key], str) for key in item)):
            raise ValueError("request_context summary item is invalid")
    return deepcopy(context)


def set_request(root: Path, session: dict[str, Any], request: dict[str, Any],
                *, policy_version: str | None = None,
                data_version: str | None = None,
                policy_binding: dict[str, Any] | None = None,
                request_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bind a fully confirmed request; caller must have verified the scope."""
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    if request.get("schema_version") == "analysis-request-v1":
        from .analysis_request import validate_analysis_request
        canonical = validate_analysis_request(request)
        request_context = _validate_request_context(request_context, canonical)
        if data_version != canonical["data_version"]:
            raise ValueError("analysis-request-v1 必须绑定请求中的 data_version")
        request_binding = canonical.get("policy_binding")
        if policy_binding is None:
            policy_binding = request_binding
        elif request_binding != policy_binding:
            raise ValueError("服务端 policy_binding 与请求快照不一致")
        # The new contract owns its own full request digest and has no legacy
        # month/product/focus fields.  Keep all older session behavior below.
        with _session_lock(root, session["session_id"]):
            session["current_request"] = deepcopy(canonical)
            session["request_digest"] = request_digest(canonical)
            session["policy_version"] = policy_version or (
                policy_binding.get("doc_version") if isinstance(policy_binding, dict) else None)
            session["data_version"] = data_version
            session["policy_binding"] = deepcopy(policy_binding)
            session["request_context"] = deepcopy(request_context)
            for task in session.get("tasks", {}).values():
                if (task.get("request_digest") == session["request_digest"]
                        and task.get("state") in ("received", "awaiting_confirmation")):
                    task["policy_version"] = session.get("policy_version")
                    task["data_version"] = session.get("data_version")
                    task["policy_binding"] = deepcopy(session.get("policy_binding"))
                    task["request_context"] = deepcopy(session.get("request_context"))
            session["revision"] += 1
            save_session(root, session)
        return session
    if not _MONTH.fullmatch(str(request.get("month") or "")):
        raise ValueError("request month must be YYYY-MM")
    if request.get("product") != "all" and not re.fullmatch(r"\d{8}", str(request.get("product") or "")):
        raise ValueError("request product must be 'all' or an HTS8 code")
    products = request.get("products")
    if products is not None:
        if (not isinstance(products, list) or not products or len(products) != len(set(products))
                or any(not isinstance(code, str) or not re.fullmatch(r"\d{8}", code)
                       for code in products)):
            raise ValueError("request products must be a unique HTS8 list")
        if policy_binding is None:
            raise ValueError("products list is supported only for an announcement binding")
    if request.get("focus") not in ("china_amount", "china_share", "contrast"):
        raise ValueError("request focus is unsupported")
    if not str(request.get("policy_id") or "").strip():
        raise ValueError("request policy_id is required")
    binding = _validate_policy_binding(policy_binding,
                                      request_policy_id=str(request["policy_id"]))
    if session.get("policy_binding") is not None and binding is None:
        old = session.get("policy_binding") or {}
        if old.get("policy_id") != request.get("policy_id"):
            raise ValueError("切换公告必须重新提交服务器确认的 policy_binding")
        # Keeping an old binding for a same-policy follow-up is safe only when
        # the caller did not try to replace it.  It remains in the session.
        binding = deepcopy(old)
    with _session_lock(root, session["session_id"]):
        session["current_request"] = deepcopy(request)
        session["request_digest"] = request_digest(request)
        session["request_context"] = None
        if binding is not None:
            # A policy binding is a new server-owned scope.  Do not carry a
            # previous case's data hash into it when this announcement has no
            # verified trade snapshot yet.
            session["policy_version"] = policy_version or binding["doc_version"]
            session["data_version"] = data_version
            session["policy_binding"] = binding
        else:
            session["policy_version"] = policy_version or session.get("policy_version")
            session["data_version"] = data_version or session.get("data_version")
            if session.get("policy_binding") is None:
                session["policy_binding"] = None
        # A page normally starts a task before the user confirms its scope.
        # Once that confirmation succeeds, carry the server-owned binding into
        # the still-awaiting task.  Otherwise the evidence gate would compare
        # the newly confirmed session against the task's old ``None`` binding
        # and reject the valid start-then-confirm order.
        for task in session.get("tasks", {}).values():
            if (task.get("request_digest") == session["request_digest"]
                    and task.get("state") in ("received", "awaiting_confirmation")):
                task["policy_version"] = session.get("policy_version")
                task["data_version"] = session.get("data_version")
                task["policy_binding"] = deepcopy(session.get("policy_binding"))
        session["revision"] += 1
        save_session(root, session)
    return session


def _validate_scope_proposal(proposal: Any, *, expected_proposal_id: str | None = None) -> dict[str, Any]:
    """Validate and canonicalise a server-owned multi-period proposal.

    A proposal is only a preview.  It must carry a complete
    ``analysis-request-v1`` and the digest calculated from that request.  The
    checks live here, at the persistence boundary, so callers cannot store a
    client-edited request under an apparently valid proposal id.
    """
    if not isinstance(proposal, dict):
        raise ValueError("scope proposal must be an object")
    if proposal.get("schema_version") != "analysis-scope-proposal-v1":
        raise ValueError("unsupported scope proposal schema")
    if proposal.get("status") != "proposal_only":
        raise ValueError("scope proposal must remain proposal_only")
    if proposal.get("confirmation_required") is not True:
        raise ValueError("scope proposal must require confirmation")
    if proposal.get("query_executed") is not False:
        raise ValueError("scope proposal must not claim a query was executed")
    request = proposal.get("request")
    if not isinstance(request, dict) or request.get("schema_version") != "analysis-request-v1":
        raise ValueError("scope proposal must contain analysis-request-v1")
    from .analysis_request import validate_analysis_request
    canonical = validate_analysis_request(request)
    digest = request_digest(canonical)
    if proposal.get("request_digest") != digest:
        raise ValueError("scope proposal request_digest does not match request")
    if proposal.get("policy_id") != canonical["policy_id"]:
        raise ValueError("scope proposal policy_id does not match request")
    if proposal.get("data_version") != canonical["data_version"]:
        raise ValueError("scope proposal data_version does not match request")
    if expected_proposal_id is not None and proposal.get("proposal_id") != expected_proposal_id:
        raise ValueError("scope proposal id does not match its storage key")
    parent_digest = proposal.get("parent_request_digest")
    if parent_digest is not None and (
            not isinstance(parent_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", parent_digest)):
        raise ValueError("scope proposal parent_request_digest is invalid")
    result = deepcopy(proposal)
    result["request"] = canonical
    result["request_digest"] = digest
    if "request_context" in result:
        result["request_context"] = _validate_request_context(result["request_context"], canonical)
    return result


def save_scope_proposal(root: Path, session: dict[str, Any],
                        proposal: dict[str, Any]) -> dict[str, Any]:
    """Persist a server-owned proposal without confirming or executing it.

    The complete proposal is stored under a generated, non-overwritable id.
    Supplying an existing id is idempotent only when the stored bytes are the
    same; a different request is rejected.  The mutation uses the caller's
    loaded revision and the same session lock as the rest of the workflow.
    """
    candidate = _validate_scope_proposal(proposal)
    supplied_id = candidate.get("proposal_id")
    if supplied_id is not None and (
            not isinstance(supplied_id, str) or not _PROPOSAL_ID.fullmatch(supplied_id)):
        raise ValueError("scope proposal proposal_id is invalid")
    if not isinstance(session, dict) or not _SESSION_ID.fullmatch(str(session.get("session_id") or "")):
        raise ValueError("invalid session")
    proposal_id = supplied_id or ("proposal-" + uuid.uuid4().hex[:16])
    candidate["proposal_id"] = proposal_id
    with _session_lock(root, session["session_id"]):
        fresh = load_session(root, session["session_id"])
        if int(fresh.get("revision", -1)) != int(session.get("_loaded_revision", -1)):
            raise StaleSessionError(
                "session changed on disk since it was loaded; reload before saving proposal")
        proposals = fresh.setdefault("scope_proposals", {})
        existing = proposals.get(proposal_id)
        if existing is not None:
            if _canonical(existing) != _canonical(candidate):
                raise StaleSessionError("scope proposal id already belongs to a different proposal")
            session.clear()
            session.update(fresh)
            return deepcopy(existing)
        candidate.setdefault("created_at", _now())
        proposals[proposal_id] = deepcopy(candidate)
        fresh["revision"] += 1
        save_session(root, fresh)
    session.clear()
    session.update(fresh)
    return deepcopy(candidate)


def load_scope_proposal(root: Path, session: dict[str, Any],
                        proposal_id: str) -> dict[str, Any]:
    """Load and revalidate one persisted proposal under the session lock."""
    if not isinstance(session, dict) or not _SESSION_ID.fullmatch(str(session.get("session_id") or "")):
        raise ValueError("invalid session")
    if not isinstance(proposal_id, str) or not _PROPOSAL_ID.fullmatch(proposal_id):
        raise ValueError("scope proposal proposal_id is invalid")
    with _session_lock(root, session["session_id"]):
        fresh = load_session(root, session["session_id"])
        proposal = (fresh.get("scope_proposals") or {}).get(proposal_id)
        if proposal is None:
            raise ValueError(f"unknown scope proposal: {proposal_id}")
        checked = _validate_scope_proposal(proposal, expected_proposal_id=proposal_id)
    session.clear()
    session.update(fresh)
    return checked


def _previous_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year - (mon == 1)}-{(mon - 1) or 12:02d}"


def _month_distance(start: str, end: str) -> int:
    if not _MONTH.fullmatch(str(start or "")) or not _MONTH.fullmatch(str(end or "")):
        raise ValueError("请求窗口月份无效")
    return (int(end[:4]) - int(start[:4])) * 12 + int(end[5:7]) - int(start[5:7])


def _shift_month(month: str, offset: int) -> str:
    year, number = int(month[:4]), int(month[5:7])
    absolute = year * 12 + number - 1 + offset
    if absolute < 0:
        raise ValueError("月份计算超出支持范围")
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def resolve_followup(session: dict[str, Any], text: str, *,
                     published_last_month: str | None = None) -> dict[str, Any]:
    """Resolve a follow-up into a ``candidate_request`` WITHOUT writing it.

    Only explicitly mentioned fields change.  ``上月`` resolves to one month
    before the confirmed month; ``最新可用`` to the published snapshot's last
    month (when provided).  Multiple months or product codes keep the full
    requirement list and ask for clarification -- the current single month /
    single product boundary is stated, never silently narrowed.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("follow-up text must be non-empty")
    request = deepcopy(session.get("current_request") or {})
    changes: list[str] = []
    clarifications: list[str] = []
    reconfirm = False

    if request.get("schema_version") == "analysis-request-v1":
        from .analysis_request import validate_analysis_request
        window = request.get("window") or {}
        old_start, old_end, old_anchor = (window.get("start"), window.get("end"),
                                           window.get("anchor_month"))
        explicit = re.findall(r"(?<!\d)(\d{4}-(?:0[1-9]|1[0-2]))(?!\d)", text)
        asks_latest = bool(re.search(r"最新可用|最近(?:发布|可用)|最新数据", text))
        if asks_latest and explicit:
            clarifications.append("问题同时指定了‘最新可用’和明确月份；请只保留一种时间要求。")
        elif len(explicit) > 1:
            clarifications.append("问题包含多个明确月份；请先指定新的统计锚点。")
        elif asks_latest:
            if not _MONTH.fullmatch(str(published_last_month or "")):
                clarifications.append("服务器没有提供已发布快照的最新统计月份，不能猜测‘最新可用’。")
            else:
                new_anchor = str(published_last_month)
                start_shift = _month_distance(old_start, old_anchor)
                end_shift = _month_distance(old_end, old_anchor)
                request["window"] = {**window,
                    "start": _shift_month(new_anchor, -start_shift),
                    "end": _shift_month(new_anchor, end_shift),
                    "anchor_month": new_anchor, "mode": "latest",
                    "selection_reason": "采用服务器已登记发布快照的最新统计月份；重新核对发布版本覆盖。"}
                changes.append(f"anchor_month -> {new_anchor}（服务器已发布快照）")
                reconfirm = True
        elif re.search(r"上月|上个月", text):
            new_anchor = (_previous_month(old_anchor)
                          if _MONTH.fullmatch(str(old_anchor or "")) else None)
            if new_anchor is None:
                clarifications.append("没有已确认的统计锚点，无法确定‘上月’。")
            else:
                start_shift = _month_distance(old_start, old_anchor)
                end_shift = _month_distance(old_end, old_anchor)
                request["window"] = {**window,
                    "start": _shift_month(new_anchor, -start_shift),
                    "end": _shift_month(new_anchor, end_shift),
                    "anchor_month": new_anchor, "mode": "explicit",
                    "selection_reason": "根据已确认锚点向前移动一个月；重新核对发布版本覆盖。"}
                changes.append(f"anchor_month -> {new_anchor}（以已确认锚点移动一个月）")
                reconfirm = True
        elif explicit:
            new_anchor = explicit[0]
            start_shift = _month_distance(old_start, old_anchor)
            end_shift = _month_distance(old_end, old_anchor)
            request["window"] = {**window,
                "start": _shift_month(new_anchor, -start_shift),
                "end": _shift_month(new_anchor, end_shift),
                "anchor_month": new_anchor, "mode": "explicit",
                "selection_reason": "采用追问中明确的统计锚点；重新核对发布版本覆盖。"}
            changes.append(f"anchor_month -> {new_anchor}（问题中明确指定）")
            reconfirm = True
        codes = set(re.findall(r"(?<!\d)(\d{8})(?!\d)", text))
        if len(codes) > 1:
            clarifications.append("问题包含多个商品税号；请先确认一个商品或保留当前完整范围。")
        elif len(codes) == 1:
            new_code = next(iter(codes))
            request["products"] = [new_code]
            changes.append(f"products -> {new_code}（换商品，需重新核对登记范围）")
            reconfirm = True
        if changes:
            request["original_question"] = request.get("original_question", "") + "\n追问：" + text
            try:
                validate_analysis_request(request)
            except ValueError as exc:
                clarifications.append(str(exc))
        return {"changed": bool(changes), "changes": changes,
                "needs_clarification": clarifications,
                "candidate_request": request,
                "scope_reconfirm_required": reconfirm,
                "multi_request": None,
                "confirmation_required": bool(changes)}

    if re.search(r"上月|上个月", text):
        if _MONTH.fullmatch(str(request.get("month") or "")):
            request["month"] = _previous_month(request["month"])
            changes.append(f"month -> {request['month']}（以已确认统计月份减一个月）")
            reconfirm = True
        else:
            clarifications.append("没有已确认的统计月份作为基准，无法确定“上月”；请先明确月份。")
    explicit = re.findall(r"(?<!\d)(\d{4}-(?:0[1-9]|1[0-2]))(?!\d)", text)
    if len(explicit) > 1:
        clarifications.append("问题包含多个月份：" + "、".join(explicit) +
                              "；当前边界为单月分析，需求已完整保留，请确认先做哪一个月。")
    elif explicit:
        request["month"] = explicit[0]
        changes.append(f"month -> {explicit[0]}（问题中明确指定）")
        reconfirm = True
    if re.search(r"最新可用|最近已发布|最新已发布", text):
        if published_last_month:
            request["month"] = published_last_month
            changes.append(f"month -> {published_last_month}（已发布快照末月，不是实时数据）")
            reconfirm = True
        else:
            clarifications.append("需要已发布快照的末月才能解释“最新可用”；未提供时不猜测。")
    codes = set(re.findall(r"(?<!\d)(\d{8})(?!\d)", text))
    old_product = str(request.get("product") or "")
    codes.discard(old_product)
    if len(codes) > 1:
        clarifications.append("问题包含多个商品税号：" + "、".join(sorted(codes)) +
                              "；当前边界为单品分析，需求已完整保留，请确认先做哪一个。")
    elif len(codes) == 1:
        new_code = codes.pop()
        request["product"] = new_code
        changes.append(f"product -> {new_code}（换商品，需重新核对税号与政策范围）")
        reconfirm = True
    if re.search(r"换个政策|切换政策|另一项政策", text) and not codes:
        clarifications.append("换政策需要重新核对税号与范围；请提供政策名称或公告。")
        reconfirm = True
    multi = {}
    if len(explicit) > 1:
        multi["months"] = explicit
    if len(codes) > 1:
        multi["codes"] = sorted(codes)
    if not changes and not clarifications:
        return {"changed": False, "changes": [], "needs_clarification": [
            "追问未包含可明确识别的字段变化；当前请求保持不变。"],
            "candidate_request": request, "confirmation_required": False}
    return {"changed": bool(changes), "changes": changes,
            "needs_clarification": clarifications,
            "candidate_request": request,
            "scope_reconfirm_required": reconfirm,
            "multi_request": multi or None,
            "confirmation_required": bool(changes)}


def confirm_request(root: Path, session: dict[str, Any], candidate: dict[str, Any],
                    *, policy_version: str | None = None,
                    data_version: str | None = None,
                    policy_binding: dict[str, Any] | None = None,
                    request_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply a follow-up candidate_request after scope re-verification."""
    return set_request(root, session, candidate,
                       policy_version=policy_version, data_version=data_version,
                       policy_binding=policy_binding,
                       request_context=request_context)


# -- research tasks ----------------------------------------------------------

def _task_key(request_digest_value: str, policy_version: str | None,
              data_version: str | None, model: str, prompt_digest: str,
              policy_binding: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(_canonical({
        "request_digest": request_digest_value,
        "policy_version": policy_version,
        "data_version": data_version,
        "model": model, "prompt_digest": prompt_digest,
        # A candidate can be re-confirmed under the same document version;
        # include its server-owned digest so a changed binding cannot reuse an
        # older task merely because the doc_version string stayed unchanged.
        "policy_binding": {
            "policy_id": policy_binding.get("policy_id"),
            "doc_version": policy_binding.get("doc_version"),
            "candidate_digest": policy_binding.get("candidate_digest"),
            "coverage_month": policy_binding.get("coverage_month"),
            "coverage_status": policy_binding.get("coverage_status"),
            "trade_coverage_digest": policy_binding.get("trade_coverage_digest"),
            "requested_codes": policy_binding.get("requested_codes"),
            "coverage_scope": policy_binding.get("coverage_scope"),
        } if isinstance(policy_binding, dict) else None,
    }).encode("utf-8")).hexdigest()[:16]


def _validate_request_shape(request: dict[str, Any]) -> None:
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    if request.get("schema_version") == "analysis-request-v1":
        from .analysis_request import validate_analysis_request
        validate_analysis_request(request)
        return
    if not _MONTH.fullmatch(str(request.get("month") or "")):
        raise ValueError("request month must be YYYY-MM")
    if request.get("product") != "all" and not re.fullmatch(r"\d{8}", str(request.get("product") or "")):
        raise ValueError("request product must be 'all' or an HTS8 code")
    products = request.get("products")
    if products is not None and (
            not isinstance(products, list) or not products or len(products) != len(set(products))
            or any(not isinstance(code, str) or not re.fullmatch(r"\d{8}", code)
                   for code in products)):
        raise ValueError("request products must be a unique HTS8 list")
    if request.get("focus") not in ("china_amount", "china_share", "contrast"):
        raise ValueError("request focus is unsupported")
    if not str(request.get("policy_id") or "").strip():
        raise ValueError("request policy_id is required")


def start_task(root: Path, session: dict[str, Any], *, model: str, prompt_digest: str,
               run_id: str | None = None, request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Open (or deduplicate) a generation task; the claim is atomic.

    ``request`` is the proposed scope.  When it matches the session's
    confirmed request the task starts as ``received`` (already confirmed);
    otherwise it starts as ``awaiting_confirmation`` and any evidence query
    is refused until the scope is confirmed.  Deduplication keys on the
    proposed request digest + policy/data version + model + prompt digest,
    so a repeated click cannot create a second task.

    Returns ``{"action": ...}``:
      - ``reuse``: an identical finished task exists; do not call the model.
      - ``in_progress``: an identical task is still working; wait for it.
      - ``blocked_unknown_outcome``: an identical task started but has no
        saved response, or ended failed/unknown; a human must decide first.
      - ``create``: a new task was created and persisted.
    """
    if not str(model).strip() or not str(prompt_digest).strip():
        raise ValueError("model and prompt_digest are required for deduplication")
    if request is not None:
        _validate_request_shape(request)
        digest = request_digest(request)
    else:
        digest = session.get("request_digest")
        if not digest:
            raise ValueError("session has no confirmed request; pass request or set_request first")
        request = deepcopy(session.get("current_request") or {})
    key = _task_key(digest, session.get("policy_version"), session.get("data_version"),
                    model, prompt_digest, session.get("policy_binding"))
    confirmed = session.get("request_digest") == digest
    if (request.get("schema_version") == "analysis-request-v1" and not confirmed):
        # v1 carries a server-pinned data snapshot as part of its identity.
        # Starting it before confirmation would create a key with null
        # version/binding and a second task after confirmation; require the
        # explicit request-confirmation route first.
        raise ValueError("analysis-request-v1 必须先完成服务器版本确认，再创建任务")
    with _session_lock(root, session["session_id"]):
        fresh = load_session(root, session["session_id"])
        existing = fresh["tasks"].get(key)
        if existing is not None:
            state = existing["state"]
            if state == "generation_started" and not existing.get("response"):
                outcome = {"action": "blocked_unknown_outcome", "task_id": existing["task_id"],
                           "task": existing,
                           "reason": "同名任务已开始生成但没有保存的响应；不能自动再次调用（可能重复收费）。"}
            elif state in ("received", "awaiting_confirmation", "evidence_ready"):
                outcome = {"action": "in_progress", "task_id": existing["task_id"],
                           "task": existing,
                           "reason": "同名任务尚未完成，继续等待；不创建第二个任务。"}
            elif state not in _TERMINAL_WITHOUT_RESPONSE:
                outcome = {"action": "reuse", "task_id": existing["task_id"], "task": existing,
                           "reason": "同一请求+版本+模型+提示摘要的任务已有结果，直接复用，不重复调用。"}
            else:
                outcome = {"action": "blocked_unknown_outcome", "task_id": existing["task_id"],
                           "task": existing,
                           "reason": "同名任务处于失败/未知结果状态；需要人工决定后才能重试。"}
        else:
            fresh["task_counter"] += 1
            initial_state = "received" if confirmed else "awaiting_confirmation"
            task = {"schema_version": TASK_SCHEMA, "task_id": f"task-{fresh['task_counter']}",
                    "key": key,
                    "request_digest": digest,
                    "policy_version": fresh.get("policy_version"),
                    "data_version": fresh.get("data_version"),
                    "policy_binding": deepcopy(fresh.get("policy_binding")),
                    "request_context": deepcopy(fresh.get("request_context")),
                    "request_snapshot": deepcopy(request),
                    "state": initial_state, "model": model,
                    "prompt_digest": prompt_digest, "run_id": run_id,
                    "created_at": _now(),
                    "history": [{"state": initial_state, "at": _now(),
                                 "reason": None if confirmed else "等待用户确认范围"}],
                    "response": None, "usage": None, "error": None}
            fresh["tasks"][key] = task
            if run_id:
                fresh["run_ids"].append(run_id)
            fresh["revision"] += 1
            save_session(root, fresh)
            outcome = {"action": "create", "task_id": task["task_id"], "task": task}
    session.clear()
    session.update(fresh)
    return outcome


class TaskStateConflict(ValueError):
    """A concurrent/stale transition lost the race for a state change.

    Raised when the on-disk task state no longer allows the requested
    transition -- notably the generation claim: only ONE writer may move a
    task into ``generation_started``; every other stale copy gets this
    conflict instead of a second permission to call the model.
    """


def transition_task(root: Path, session: dict[str, Any], task_id: str, new_state: str, *,
                    reason: str | None = None, response: dict[str, Any] | None = None,
                    usage: dict[str, Any] | None = None,
                    evidence: dict[str, Any] | None = None,
                    error: str | None = None) -> dict[str, Any]:
    """Move a task to a new state; the legality check happens INSIDE the lock.

    The task state on disk is the only authority: the caller's possibly-stale
    copy is never trusted for the from/to decision.  A stale writer that lost
    the race (e.g. for the single ``generation_started`` permission) gets
    :class:`TaskStateConflict`, so a concurrent generation can only be
    claimed once.
    """
    if new_state not in STATES:
        raise ValueError(f"unknown task state: {new_state}")
    if new_state == "response_saved" and response is None:
        raise ValueError("response payload is required to save a response")
    with _session_lock(root, session["session_id"]):
        fresh = load_session(root, session["session_id"])
        stored = next((item for item in fresh["tasks"].values()
                       if item["task_id"] == task_id), None)
        if stored is None:
            raise ValueError(f"unknown task: {task_id}")
        if new_state not in TRANSITIONS[stored["state"]]:
            if new_state == "generation_started":
                raise TaskStateConflict(
                    f"生成许可已被领取（磁盘状态 {stored['state']}）；并发或旧副本不能再次获得调用许可")
            raise TaskStateConflict(
                f"invalid transition on disk: {stored['state']} -> {new_state}（旧副本已被拒绝）")
        stored["state"] = new_state
        stored["history"].append({"state": new_state, "at": _now(), "reason": reason})
        if response is not None:
            stored["response"] = deepcopy(response)
        if evidence is not None:
            stored["evidence"] = deepcopy(evidence)
        if usage is not None:
            stored["usage"] = deepcopy(usage)
        if error is not None:
            stored["error"] = error
        fresh["revision"] += 1
        save_session(root, fresh)
    session.clear()
    session.update(fresh)
    return stored


def record_task_confirmation(root: Path, session: dict[str, Any], task_id: str, *,
                             confirmation_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a confirmation record to the task (J4: A3 program-draft gate).

    The record binds WHAT was confirmed (exact report hash, version, catalog
    digest) and WHO decided; the export gate re-checks it against the current
    response so a changed report invalidates the confirmation.
    """
    if not isinstance(payload, dict) or not confirmation_type:
        raise ValueError("confirmation type and payload are required")
    with _session_lock(root, session["session_id"]):
        fresh = load_session(root, session["session_id"])
        stored = next((item for item in fresh["tasks"].values()
                       if item["task_id"] == task_id), None)
        if stored is None:
            raise ValueError(f"unknown task: {task_id}")
        stored.setdefault("confirmations", []).append(
            {**deepcopy(payload), "confirmation_type": confirmation_type, "at": _now()})
        fresh["revision"] += 1
        save_session(root, fresh)
    session.clear()
    session.update(fresh)
    return {"status": "recorded", "task_id": task_id}


def save_task_explanation(root: Path, session: dict[str, Any], task_id: str,
                          explanation: dict[str, Any]) -> dict[str, Any]:
    """Persist the provider-neutral explanation result under the task lock.

    The explanation is supplementary to the deterministic A3 response.  It is
    deliberately not represented as a state-machine transition: a malformed
    or unreviewed answer must never make a task look exportable.
    """
    if not isinstance(explanation, dict):
        raise ValueError("explanation must be an object")
    with _session_lock(root, session["session_id"]):
        fresh = load_session(root, session["session_id"])
        stored = next((item for item in fresh["tasks"].values()
                       if item["task_id"] == task_id), None)
        if stored is None:
            raise ValueError(f"unknown task: {task_id}")
        if stored.get("state") not in ("response_saved", "needs_review", "reviewed"):
            raise TaskStateConflict("任务尚未保存确定性程序报告；不能附加AI解释")
        previous = stored.get("explanation") or {}
        current_revision = int(stored.get("explanation_revision", 0))
        supplied_revision = explanation.get("explanation_revision")
        if supplied_revision is not None:
            try:
                if int(supplied_revision) != current_revision:
                    raise TaskStateConflict("解释结果已被其他操作更新；请刷新后重试")
            except (TypeError, ValueError) as exc:
                raise TaskStateConflict("解释结果版本无效；请刷新后重试") from exc
        new_explanation = deepcopy(explanation)
        new_explanation["explanation_revision"] = current_revision + 1
        identity = new_explanation.get("identity")
        if identity is not None and identity != {"session_id": session["session_id"],
                                                "task_id": task_id}:
            raise TaskStateConflict("解释结果身份与任务不匹配")
        raw_changed = bool(previous.get("raw_sha256")
                           and previous.get("raw_sha256") != new_explanation.get("raw_sha256"))
        if raw_changed:
            # A new provider answer starts a new review chain.  The previous
            # answer (including its review history) remains in the immutable
            # explanation_history below, but its revision number cannot be
            # reused for the new answer.
            new_explanation["review_revision"] = 0
            new_explanation.pop("review", None)
        new_review = new_explanation.get("review")
        previous_review = previous.get("review")
        if new_review:
            if new_review.get("protocol") not in {
                    "session-explanation-review-v1",
                    "public-brief-explanation-review-v1"}:
                raise TaskStateConflict("AI审阅协议不匹配")
            expected_review_revision = int(stored.get("review_revision", 0)) + 1
            try:
                supplied_review_revision = int(new_review.get("review_revision"))
            except (TypeError, ValueError) as exc:
                raise TaskStateConflict("AI审阅版本无效；请刷新后重试") from exc
            if supplied_review_revision != expected_review_revision:
                raise TaskStateConflict("AI审阅已被其他操作更新；请刷新后重试")
            expected_base = (_review_digest(previous_review)
                             if isinstance(previous_review, dict) else None)
            if new_review.get("base_review_digest") != expected_base:
                raise TaskStateConflict("AI审阅基准已变化；请刷新后重试")
            stored["review_revision"] = supplied_review_revision
            if isinstance(previous_review, dict) and previous_review != new_review:
                stored.setdefault("review_history", []).append(deepcopy(previous_review))
        elif raw_changed:
            stored["review_revision"] = 0
        if previous and previous.get("raw_sha256") != new_explanation.get("raw_sha256"):
            stored.setdefault("explanation_history", []).append(deepcopy(previous))
        stored["explanation"] = new_explanation
        stored["explanation_revision"] = current_revision + 1
        review = new_explanation.get("review") or {}
        if review:
            fields = ("snapshot_sha256", "catalog_sha256", "program_report_sha256")
            if review.get("protocol") == "public-brief-explanation-review-v1":
                fields = ("snapshot_sha256", "report_sha256", "evidence_sha256",
                          "request_digest")
            for field in fields:
                expected = new_explanation.get(field)
                recorded = review.get(field)
                if expected is not None and recorded != expected:
                    raise TaskStateConflict(f"AI审阅绑定字段不一致：{field}")
        if review.get("eligible_for_export"):
            rendered = review.get("rendered_markdown")
            response = stored.get("response")
            if isinstance(rendered, str) and rendered and isinstance(response, dict):
                if review.get("protocol") == "public-brief-explanation-review-v1":
                    response["final_markdown"] = rendered
                    response["final_report"] = deepcopy(review.get("final_report"))
                    response["final_report_sha256"] = review.get("final_report_sha256")
                    response["final_kind"] = "temporal-report-v1-with-reviewed-explanation"
                else:
                    response["final_markdown"] = response.get("a3_markdown", "") + "\n\n" + rendered
                    response["final_kind"] = "program-report-a3-with-reviewed-explanation"
                response["final_markdown_sha256"] = hashlib.sha256(
                    response["final_markdown"].encode("utf-8")).hexdigest()
        else:
            response = stored.get("response")
            if isinstance(response, dict):
                for field in ("final_markdown", "final_markdown_sha256", "final_kind",
                              "final_report", "final_report_sha256"):
                    response.pop(field, None)
        fresh["revision"] += 1
        save_session(root, fresh)
    session.clear()
    session.update(fresh)
    return stored


def resolve_unknown_outcome(root: Path, session: dict[str, Any], task_id: str, *,
                            resolution: str, decided_by: str, note: str | None = None) -> dict[str, Any]:
    """Human decision for a task whose model outcome is unknown.

    ``retry_authorized`` keeps the unknown task for audit under an archived
    key and opens a NEW task bound to the ORIGINAL task's request snapshot --
    even if the session's current request has changed since.  ``mark_failed``
    closes the task; both record who decided and why.  These are the only
    paths that may leave the ``unknown_outcome`` state.
    """
    if resolution not in ("retry_authorized", "mark_failed"):
        raise ValueError("resolution must be retry_authorized or mark_failed")
    task = next((item for item in session["tasks"].values() if item["task_id"] == task_id), None)
    if task is None or task["state"] != "unknown_outcome":
        raise ValueError("task is not in unknown_outcome state")
    with _session_lock(root, session["session_id"]):
        fresh = load_session(root, session["session_id"])
        stored = next((item for item in fresh["tasks"].values()
                       if item["task_id"] == task_id), None)
        if stored is None or stored["state"] != "unknown_outcome":
            raise ValueError("task is not in unknown_outcome state on disk")
        if resolution == "mark_failed":
            # Explicit human path: the transition map intentionally forbids
            # this edge; only this function may apply it, with the decider
            # and reason recorded for audit.
            stored["state"] = "failed"
            stored["history"].append({"state": "failed", "at": _now(),
                                      "reason": f"human decision by {decided_by}: {note or ''}",
                                      "decided_by": decided_by})
            fresh["revision"] += 1
            save_session(root, fresh)
            task.clear()
            task.update(stored)
            session.clear()
            session.update(fresh)
            return {"action": "mark_failed", "task_id": task_id, "task": stored}
        archived_key = f"{stored['key']}:archived-{stored['task_id']}"
        fresh["tasks"][archived_key] = stored
        fresh["tasks"].pop(stored["key"], None)
        # Retry binds to the ORIGINAL task request, not the session's current.
        key = _task_key(stored["request_digest"], stored.get("policy_version"),
                        stored.get("data_version"), stored["model"], stored["prompt_digest"],
                        stored.get("policy_binding"))
        fresh["task_counter"] += 1
        new_task = {"schema_version": TASK_SCHEMA,
                    "task_id": f"task-{fresh['task_counter']}",
                    "key": key,
                    "request_digest": stored["request_digest"],
                    "policy_version": stored.get("policy_version"),
                    "data_version": stored.get("data_version"),
                    "policy_binding": deepcopy(stored.get("policy_binding")),
                    "request_snapshot": deepcopy(stored.get("request_snapshot") or {}),
                    "retry_of": task_id,
                    "request_note": ("重试绑定原任务请求；与会话当前请求可能不同。"
                                     if fresh.get("request_digest") != stored["request_digest"]
                                     else None),
                    "state": "received", "model": stored["model"],
                    "prompt_digest": stored["prompt_digest"], "run_id": stored.get("run_id"),
                    "created_at": _now(), "history": [{"state": "received", "at": _now()}],
                    "response": None, "usage": None, "error": None}
        fresh["tasks"][key] = new_task
        fresh["revision"] += 1
        save_session(root, fresh)
        session.clear()
        session.update(fresh)
        return {"action": "create", "task_id": new_task["task_id"], "task": new_task,
                "retry_of": task_id}
