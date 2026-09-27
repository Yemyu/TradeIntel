"""Durable, local version records for the registered exposure dataset.

The store is deliberately separate from the data extraction code. A refresh
first writes a candidate snapshot, validates its content and only then moves
the small active pointer. Existing monthly evidence is never overwritten by
this module, so a failed candidate leaves the previous active version usable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


STORE_SCHEMA = "exposure-version-store-1"
VERSION_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_STORE_RELATIVE = Path("data/processed/policy_exposure/versions")


class VersionStoreError(RuntimeError):
    """Raised when a candidate cannot be safely registered or activated."""


def content_digest(value: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 used as a snapshot version."""

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _without_version(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "version"}


def validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the immutable identity fields before writing a snapshot."""

    if not isinstance(snapshot, Mapping):
        raise VersionStoreError("版本快照必须是对象")
    value = dict(snapshot)
    version = value.get("version")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise VersionStoreError("版本快照缺少合法 SHA-256 version")
    if version != content_digest(_without_version(value)):
        raise VersionStoreError("版本快照内容与 version 不一致")
    for field in ("policy_id", "start", "end", "months", "policy_files"):
        if field not in value:
            raise VersionStoreError(f"版本快照缺少字段：{field}")
    if not isinstance(value["months"], Mapping) or not value["months"]:
        raise VersionStoreError("版本快照必须包含至少一个月份")
    if not isinstance(value["policy_files"], Mapping):
        raise VersionStoreError("版本快照的政策文件指纹必须是对象")
    return value


def snapshot_difference(before, after):
    old, new = validate_snapshot(before), validate_snapshot(after)
    if old['policy_id'] != new['policy_id'] or old['start'] != new['start']:
        raise VersionStoreError('政策或起始窗口变化，不能作为增量发布')
    a, b = old['months'], new['months']
    removed = sorted(set(a) - set(b))
    revised = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    added = sorted(set(b) - set(a))
    policy_changed = old['policy_files'] != new['policy_files']
    return dict(before_version=old['version'], after_version=new['version'],
                added_months=added, removed_months=removed, revised_months=revised,
                policy_changed=policy_changed,
                requires_review=bool(removed or revised or policy_changed),
                status='changed' if added or removed or revised or policy_changed else 'unchanged')


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    """Write JSON beside the target and replace it atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VersionStoreError("版本登记文件无法读取") from exc
    if not isinstance(value, dict):
        raise VersionStoreError("版本登记文件必须是对象")
    return value


class ExposureVersionStore:
    """Manage immutable candidate snapshots and one active version pointer."""

    def __init__(self, root: Path, directory: Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.directory = (directory or self.root / DEFAULT_STORE_RELATIVE).resolve()
        try:
            self.directory.relative_to(self.root)
        except ValueError as exc:
            raise VersionStoreError("版本目录必须位于项目根目录内") from exc
        self.registry_path = self.directory / "registry.json"

    def _empty_registry(self) -> dict[str, Any]:
        return {"schema": STORE_SCHEMA, "active_version": None, "versions": {}, "failures": []}

    def _registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return self._empty_registry()
        registry = _read_object(self.registry_path)
        if registry.get("schema") != STORE_SCHEMA or not isinstance(registry.get("versions"), dict):
            raise VersionStoreError("版本登记 schema 不匹配")
        if not isinstance(registry.get("failures", []), list):
            raise VersionStoreError("版本失败记录必须是列表")
        active = registry.get("active_version")
        if active is not None and (not isinstance(active, str) or not VERSION_PATTERN.fullmatch(active)):
            raise VersionStoreError("active_version 无效")
        return registry

    def _save_registry(self, registry: Mapping[str, Any]) -> None:
        _atomic_write(self.registry_path, registry)

    def _snapshot_path(self, version: str) -> Path:
        if not VERSION_PATTERN.fullmatch(version):
            raise VersionStoreError("版本编号无效")
        return self.directory / version / "snapshot.json"

    def _record(
        self,
        version: str,
        *,
        status: str,
        before_version: str | None,
        difference: Mapping[str, Any] | None,
        source: str,
    ) -> dict[str, Any]:
        requires_review = bool((difference or {}).get("requires_review", False))
        return {
            "version": version,
            "status": status,
            "before_version": before_version,
            "requires_review": requires_review,
            "ready_for_activation": not requires_review,
            "source": source,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "snapshot_path": str(self._snapshot_path(version).relative_to(self.root)),
            "difference": dict(difference) if difference is not None else None,
        }

    def active_version(self) -> str | None:
        return self._registry().get("active_version")

    def version_record(self, version: str) -> dict[str, Any]:
        """Return the server-owned registry record for a version.

        Callers use this before binding a request so a snapshot file that
        merely exists on disk cannot be mistaken for a published version.
        """
        registry = self._registry()
        record = registry.get("versions", {}).get(version)
        if not isinstance(record, dict):
            raise VersionStoreError("数据版本未登记")
        return deepcopy(record)

    def verify_working_files(self) -> dict[str, Any] | None:
        """Bind working files to the active fingerprint; never imply a backup."""
        registry = self._registry()
        version = registry.get("active_version")
        if version is None:
            return None
        record = registry["versions"].get(version)
        if not isinstance(record, dict) or record.get("status") != "active":
            raise VersionStoreError("活动版本登记不完整")
        snapshot = self.load_snapshot(version)
        policy = snapshot["policy_id"]
        if not isinstance(policy, str) or not re.fullmatch(r"[a-zA-Z0-9_]+", policy):
            raise VersionStoreError("版本政策编号无效")
        fingerprints = dict(snapshot["policy_files"])
        if not fingerprints:
            raise VersionStoreError("活动版本缺少政策指纹")
        for month, entry in snapshot["months"].items():
            if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
                raise VersionStoreError("版本月份无效")
            if not isinstance(entry, dict):
                raise VersionStoreError("版本月份指纹无效")
            from .policy_cases import resolve_case
            case = resolve_case(policy, require_enabled=False)
            name = f"{case.monthly}/{policy}_{month.replace('-', '_')}.csv"
            fingerprints[name] = entry.get("output_sha256")
        for relative, expected in fingerprints.items():
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root):
                raise VersionStoreError("版本来源超出项目范围")
            if not isinstance(expected, str) or not VERSION_PATTERN.fullmatch(expected):
                raise VersionStoreError("版本文件指纹无效")
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise VersionStoreError("活动版本来源文件缺失，查询已停止") from exc
            if actual != expected:
                raise VersionStoreError("当前文件与活动版本不一致，查询已停止；需审查数据更新")
        if self.active_version() != version:
            raise VersionStoreError("校验期间活动版本变化，请重新查询")
        return snapshot

    def load_snapshot(self, version: str) -> dict[str, Any]:
        snapshot = validate_snapshot(_read_object(self._snapshot_path(version)))
        if snapshot["version"] != version:
            raise VersionStoreError("快照路径和内容版本不一致")
        return snapshot

    def prepare_release(self, version: str) -> Path:
        """Copy only bound evidence, validate it, then publish the directory."""
        from .repository import EvidenceRepository, DataPaths
        from .policy_exposure_tools import get_policy_exposure_series
        snapshot = self.load_snapshot(version)
        from .policy_cases import resolve_case
        case = resolve_case(snapshot['policy_id'])
        registry = self._registry()
        if registry['versions'].get(version, {}).get('release_digest'):
            return self.release_root(version)
        destination = self.directory / version / 'dataset'
        if destination.exists():
            raise VersionStoreError('存在未登记的数据副本，请审查后处理')
        temporary = self.directory / version / ('candidate-' + uuid.uuid4().hex)
        temporary.mkdir()
        files = dict(snapshot['policy_files'])
        for month, entry in snapshot['months'].items():
            files[f"{case.monthly}/{snapshot['policy_id']}_{month.replace('-', '_')}.csv"] = entry['output_sha256']
        receipt_name = f"window_validation_{snapshot['start']}_{snapshot['end']}.json"
        receipt_relative = Path(case.manifest).parent / receipt_name
        if not (self.root / receipt_relative).exists():
            # Keep the original registered receipt name readable for legacy
            # snapshots whose metadata predates the versioned window name.
            receipt_relative = Path(case.manifest).parent / "window_validation_2025-01_2026-07.json"
        for relative_path in (Path(case.manifest), receipt_relative):
            relative = str(relative_path)
            files[relative] = hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
        corpus_name = case.corpus
        if corpus_name in files:
            corpus_bytes = (self.root / corpus_name).read_bytes()
            if hashlib.sha256(corpus_bytes).hexdigest() != files[corpus_name]:
                raise VersionStoreError('政策索引已变化')
            for chunk in json.loads(corpus_bytes)['chunks']:
                files[chunk['local_path']] = chunk['sha256']
        try:
            for relative, expected in files.items():
                source = (self.root / relative).resolve()
                target = (temporary / relative).resolve()
                if not source.is_relative_to(self.root) or not target.is_relative_to(temporary):
                    raise VersionStoreError('发布文件路径超出范围')
                content = source.read_bytes()
                if hashlib.sha256(content).hexdigest() != expected:
                    raise VersionStoreError('候选文件指纹不一致')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            repo = EvidenceRepository(DataPaths(temporary))
            result = get_policy_exposure_series(repository=repo, policy_id=case.policy_id,
                                               start=snapshot['start'], end=snapshot['end'])
            if not result['data']['coverage_complete']:
                raise VersionStoreError('候选数据窗口不完整')
            for row in result['data']['series']:
                if row != snapshot['months'][row['month']]['metrics']:
                    raise VersionStoreError('候选明细复算与快照指标不一致')
            _atomic_write(temporary / 'release.json', {'version': version, 'files': files})
            os.rename(temporary, destination)
            registry = self._registry()
            registry['versions'][version]['release_digest'] = content_digest({'version': version, 'files': files})
            self._save_registry(registry)
            return self.release_root(version)
        except Exception:
            self.record_failure(reason='发布副本校验失败；候选保留供诊断', candidate_version=version)
            raise

    def release_root(self, version: str) -> Path:
        registry = self._registry()
        record = registry['versions'].get(version, {})
        self.load_snapshot(version)
        root = self.directory / version / 'dataset'
        receipt = _read_object(root / 'release.json')
        if receipt.get('version') != version or content_digest(receipt) != record.get('release_digest'):
            raise VersionStoreError('发布副本清单与登记不一致')
        for relative, expected in receipt['files'].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()):
                raise VersionStoreError('副本文件越界')
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise VersionStoreError('发布副本文件损坏')
        return root

    def bootstrap(
        self, snapshot: Mapping[str, Any], *, source: str = "bootstrap"
    ) -> dict[str, Any]:
        """Register the first known-good snapshot as active, idempotently."""

        value = validate_snapshot(snapshot)
        registry = self._registry()
        active = registry.get("active_version")
        if active is not None:
            if active == value["version"] and value["version"] in registry["versions"]:
                return {**registry["versions"][value["version"]], "idempotent": True}
            raise VersionStoreError("已有活动版本，不能用 bootstrap 覆盖")
        path = self._snapshot_path(value["version"])
        if path.exists() and self.load_snapshot(value["version"]) != value:
            raise VersionStoreError("同版本快照内容不一致")
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, value)
        record = self._record(
            value["version"],
            status="active",
            before_version=None,
            difference=None,
            source=source,
        )
        registry["active_version"] = value["version"]
        registry["versions"][value["version"]] = record
        self._save_registry(registry)
        return record

    def stage(
        self,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        difference: Mapping[str, Any],
        *,
        source: str = "candidate",
    ) -> dict[str, Any]:
        """Persist an immutable candidate after checking its active base."""

        old = validate_snapshot(before)
        new = validate_snapshot(after)
        diff = dict(difference)
        computed = snapshot_difference(old, new)
        for key, value in computed.items():
            if key in diff and diff[key] != value:
                raise VersionStoreError('提交的差异与快照重算不一致')
        diff.update(computed)
        if diff.get("before_version") != old["version"] or diff.get("after_version") != new["version"]:
            raise VersionStoreError("差异记录与前后版本不一致")
        registry = self._registry()
        active = registry.get("active_version")
        if active != old["version"]:
            raise VersionStoreError("候选版本基于的旧版本不是当前 active_version")
        existing = registry["versions"].get(new["version"])
        if existing is not None:
            stored = self.load_snapshot(new["version"])
            if stored != new:
                raise VersionStoreError("同版本已有不同内容，停止写入")
            if existing.get("status") in {"active", "superseded"}:
                return {**existing, "idempotent": True}
            if existing.get("difference") != diff:
                raise VersionStoreError("同候选版本的差异记录不一致")
            return {**existing, "idempotent": True}
        path = self._snapshot_path(new["version"])
        if path.exists() and self.load_snapshot(new["version"]) != new:
            raise VersionStoreError("候选快照已存在但内容不同")
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, new)
        record = self._record(
            new["version"],
            status="candidate",
            before_version=old["version"],
            difference=diff,
            source=source,
        )
        registry["versions"][new["version"]] = record
        registry["last_update"] = diff
        self._save_registry(registry)
        return record

    def activate(self, version: str) -> dict[str, Any]:
        """Move the active pointer only for a validated, review-free candidate."""

        registry = self._registry()
        record = registry["versions"].get(version)
        if record is None:
            raise VersionStoreError("候选版本不存在")
        if record.get("status") == "active" and registry.get("active_version") == version:
            return {**record, "idempotent": True}
        if record.get("status") != "candidate":
            raise VersionStoreError("只有 candidate 可以激活")
        if record.get("requires_review"):
            raise VersionStoreError("候选版本仍需要人工审查，不能激活")
        if registry.get("active_version") != record.get("before_version"):
            raise VersionStoreError("活动版本在候选生成后已变化，停止切换")
        candidate = self.load_snapshot(version)
        actual = snapshot_difference(self.load_snapshot(record['before_version']), candidate)
        if actual['requires_review']:
            raise VersionStoreError('快照重算仍需审查，不能激活')
        self.release_root(version)
        previous = registry.get("active_version")
        if previous and previous in registry["versions"]:
            registry["versions"][previous]["status"] = "superseded"
        record["status"] = "active"
        record["activated_at_utc"] = datetime.now(timezone.utc).isoformat()
        registry["versions"][version] = record
        registry["active_version"] = version
        self._save_registry(registry)
        return {**record, "previous_version": previous}

    def record_failure(
        self,
        *,
        reason: str,
        source: str = "candidate_validation",
        candidate_version: str | None = None,
    ) -> dict[str, Any]:
        """Record a failed candidate attempt without touching the active pointer."""

        registry = self._registry()
        failure = {
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "candidate_version": candidate_version,
            "reason": str(reason)[:300],
        }
        registry.setdefault("failures", []).append(failure)
        registry["failures"] = registry["failures"][-20:]
        self._save_registry(registry)
        return {"status": "recorded", "active_version": registry.get("active_version"), **failure}

    def status(self) -> dict[str, Any]:
        """Return browser-safe current status and the latest difference."""

        registry = self._registry()
        versions = registry.get("versions", {})
        active = registry.get("active_version")
        candidates = [
            record for record in versions.values() if record.get("status") == "candidate"
        ]
        candidates.sort(key=lambda item: item.get("created_at_utc", ""), reverse=True)
        return {
            "status": "ready" if active else "uninitialized",
            "active_version": active,
            "active": versions.get(active) if active else None,
            "candidates": candidates[:10],
            "last_update": registry.get("last_update"),
            "failure_count": len(registry.get("failures", [])),
            "schema": STORE_SCHEMA,
        }


def pin_repository(repository, policy_id='us_301_review2025_tungsten_solar'):
    """Resolve once per workflow; subsequent calls retain this exact version."""
    from .repository import EvidenceRepository, DataPaths
    from .policy_cases import resolve_case
    case = resolve_case(policy_id)
    if getattr(repository, 'exposure_version', None):
        snapshot = repository.exposure_store.load_snapshot(repository.exposure_version)
        if snapshot['policy_id'] != case.policy_id:
            raise VersionStoreError('已绑定版本属于其他政策，禁止跨案例复用')
        repository.exposure_store.release_root(repository.exposure_version)
        return repository
    store = ExposureVersionStore(repository.paths.root, repository.paths.root / case.versions)
    version = store.active_version()
    if version is None:
        return repository
    snapshot = store.load_snapshot(version)
    if snapshot['policy_id'] != case.policy_id:
        raise VersionStoreError('案例版本目录包含其他政策快照，查询已停止')
    root = store.release_root(version)
    pinned = EvidenceRepository(DataPaths(root))
    pinned.exposure_version = version
    pinned.exposure_store = store
    pinned.exposure_snapshot = snapshot
    return pinned


__all__ = [
    "DEFAULT_STORE_RELATIVE",
    "ExposureVersionStore",
    "STORE_SCHEMA",
    "VersionStoreError",
    "content_digest",
    "validate_snapshot",
]
