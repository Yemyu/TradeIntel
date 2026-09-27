"""Controlled update flow for trade data versions (offline orchestrator).

Implements fetch → stage → validate → diff → candidate → confirm → activate
on top of the existing ``ExposureVersionStore`` so there is exactly one
publishing pointer.  ``fetch`` is an injected callable: real monthly sources
are wired by the operator later; nothing here invents data.

Guarantees (inherited and enforced):
  - no change -> no new version ("无变化不造版本");
  - dry-run reports the difference without touching the registry;
  - staging is idempotent and verifies the active base;
  - candidates requiring review stay candidates until explicit confirmation;
  - activation failure records the failure and leaves the old active version
    untouched; reports keep their pinned versions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from .exposure_version_store import ExposureVersionStore, VersionStoreError, snapshot_difference

CHECK_LOG_LIMIT = 50


def _check_log_path(root: Path) -> Path:
    return Path(root) / ".local" / "update-checks.json"


def record_check(root: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Persist one check event (time + outcome) separately from versions.

    The check log answers "最近检查时间" on the page and is written even when
    nothing changed or no fetch source is configured; it never reuses the
    version's creation timestamp.
    """
    path = _check_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    log: dict[str, Any] = {"schema_version": "update-check-log-v1", "checks": []}
    if path.is_file():
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            log = {"schema_version": "update-check-log-v1", "checks": []}
    entry = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "status": result.get("status"),
             "active_version": result.get("active_version"),
             "difference_status": (result.get("difference") or {}).get("status"),
             "added_months": (result.get("difference") or {}).get("added_months"),
             "revised_months": (result.get("difference") or {}).get("revised_months"),
             "message": result.get("message")}
    log["checks"] = ([entry] + log.get("checks", []))[:CHECK_LOG_LIMIT]
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".update-checks.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(log, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return entry


def read_checks(root: Path) -> list[dict[str, Any]]:
    path = _check_log_path(root)
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("checks", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []


def run_update_cycle(root: Path, *, fetch: Callable[[], dict[str, Any]] | None,
                     versions_dir: Path | None = None, confirm: bool = False,
                     dry_run: bool = False) -> dict[str, Any]:
    """Run one controlled update cycle against the active trade data version."""
    store = (ExposureVersionStore(root, versions_dir) if versions_dir
             else ExposureVersionStore(root))
    active = store.active_version()
    if active is None:
        result: dict[str, Any] = {"status": "no_active_version",
                                  "message": "当前没有活动版本；先执行引导发布，受控更新不猜测初始版本。",
                                  "active_version": None}
        record_check(root, result)
        return result
    before = store.load_snapshot(active)
    result = {"active_version": active,
              "boundary": "受控更新只通过 ExposureVersionStore 的 stage/activate 发布；失败时旧活动版本保持不变。"}
    if fetch is None:
        result.update({"status": "no_fetch_source",
                       "message": "未配置真实抓取源；本轮仅记录检查时间，不做任何数据变更。"})
        record_check(root, result)
        return result
    after = fetch()
    diff = snapshot_difference(before, after)
    result.update({"status": diff["status"], "difference": diff,
                   "dry_run": dry_run, "confirm": confirm})
    if diff["status"] == "unchanged":
        result["message"] = "无变化，不创建新版本。"
        record_check(root, result)
        return result
    if dry_run:
        result["message"] = "dry-run：仅报告差异，未写入任何候选版本。"
        record_check(root, result)
        return result
    staged = store.stage(before, after, diff, source="controlled_update")
    result["staged"] = staged
    if staged.get("requires_review"):
        result["message"] = "候选版本包含修订/删除/政策文件变化，需要人工审查后才能确认激活。"
        record_check(root, result)
        return result
    if not confirm:
        result["message"] = "候选版本已暂存；未确认，不激活。"
        record_check(root, result)
        return result
    try:
        result["activated"] = store.activate(after["version"])
        result["message"] = "候选版本已激活。"
    except VersionStoreError as exc:
        store.record_failure(reason=str(exc), candidate_version=after["version"],
                             source="controlled_update_activation")
        result["status"] = "activation_failed"
        result["message"] = f"激活失败，旧活动版本保持不变：{exc}"
    record_check(root, result)
    return result


def update_status(root: Path, *, versions_dir: Path | None = None) -> dict[str, Any]:
    """Report the active version, cutoff month and the LAST CHECK TIME.

    ``last_checked`` comes from the persisted check log (updated by every
    check, including no-change ones), never from a version's creation time.
    """
    store = (ExposureVersionStore(root, versions_dir) if versions_dir
             else ExposureVersionStore(root))
    checks = read_checks(root)
    active = store.active_version()
    if active is None:
        return {"status": "no_active_version", "last_checked": checks[0]["checked_at"] if checks else None,
                "check_history": checks[:5],
                "data_cutoff_month": None}
    snapshot = store.load_snapshot(active)
    months = sorted(snapshot.get("months", {}))
    return {"status": "ok", "active_version": active,
            "last_checked": checks[0]["checked_at"] if checks else None,
            "last_check_status": checks[0].get("status") if checks else None,
            "check_history": checks[:5],
            "data_cutoff_month": months[-1] if months else None,
            "month_count": len(months)}
