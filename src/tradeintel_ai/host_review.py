"""Immutable, restartable host-review submissions; no automatic semantic judge.

This store resumes review documents only, not the workflow or provider calls.
Callers must still verify dependency snapshots and enforce ledger transitions.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .prospective_acceptance import (
    AcceptanceGuardError, digest, validate_fact_review, validate_structured_review,
)


class HostReviewPending(AcceptanceGuardError):
    """An actual host judgement has not been submitted for this packet."""

    def __init__(self, packet_path: Path):
        self.packet_path = packet_path
        super().__init__("host review pending: " + str(packet_path))


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AcceptanceGuardError("review artifact missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AcceptanceGuardError("review artifact unreadable") from exc
    if not isinstance(value, dict):
        raise AcceptanceGuardError("review artifact must be an object")
    return value


def _publish(path: Path, value: Mapping[str, Any]) -> None:
    """Publish complete bytes atomically without overwriting a prior decision."""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    normalized = json.loads(data)
    fd, name = tempfile.mkstemp(prefix=".review-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            if _read(path) != normalized:
                raise AcceptanceGuardError("review artifact conflicts with immutable record")
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.unlink(name)


class HostReviewStore:
    """Persist exact packets and explicit host decisions bound to one batch.

    Reopening requires the same complete snapshot and reviewer identity. A
    submitted rejection is a valid review, and remains a rejection. Nothing
    here infers truth from keywords or creates a passing submission.
    """

    def __init__(self, directory: str | Path, *, snapshot: Mapping[str, Any], reviewer: str):
        if not isinstance(snapshot, Mapping) or not snapshot:
            raise AcceptanceGuardError("review snapshot required")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise AcceptanceGuardError("explicit host reviewer required")
        self.directory = Path(directory)
        if self.directory.is_symlink():
            raise AcceptanceGuardError("review directory cannot be a symlink")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.reviewer = reviewer
        self.manifest = {
            "version": "host-review-store-0131", "reviewer": reviewer,
            "reviewer_type": "ai_assisted", "snapshot": deepcopy(dict(snapshot)),
            "snapshot_sha256": digest(snapshot), "workflow_resume_supported": False,
        }
        self.manifest = json.loads(json.dumps(self.manifest, ensure_ascii=False, allow_nan=False))
        _publish(self.directory / "manifest.json", self.manifest)

    def _verify(self) -> None:
        if self.directory.is_symlink() or _read(self.directory / "manifest.json") != self.manifest:
            raise AcceptanceGuardError("host review snapshot changed")

    def _paths(self, slot: str) -> tuple[Path, Path]:
        if not isinstance(slot, str) or not slot.strip():
            raise AcceptanceGuardError("review slot required")
        stem = digest({"slot": slot})
        return self.directory / (stem + ".packet.json"), self.directory / (stem + ".submission.json")

    def request(self, slot: str, packet: Mapping[str, Any], *, kind: str) -> Path:
        self._verify()
        if kind not in {"plan", "answer", "facts", "gap"} or not isinstance(packet, Mapping):
            raise AcceptanceGuardError("invalid host review kind or packet")
        path, _ = self._paths(slot)
        _publish(path, {
            "slot": slot, "kind": kind, "packet": deepcopy(dict(packet)),
            "packet_sha256": digest(packet), "snapshot_sha256": self.manifest["snapshot_sha256"],
        })
        return path

    def _packet(self, slot: str) -> dict[str, Any]:
        self._verify()
        path, _ = self._paths(slot)
        envelope = _read(path)
        if (envelope.get("slot") != slot
                or envelope.get("snapshot_sha256") != self.manifest["snapshot_sha256"]
                or not isinstance(envelope.get("packet"), dict)
                or envelope.get("packet_sha256") != digest(envelope["packet"])):
            raise AcceptanceGuardError("host review packet changed")
        return envelope

    def _validate(self, envelope: Mapping[str, Any], submission: Mapping[str, Any]) -> dict[str, Any]:
        packet = envelope["packet"]
        if envelope['kind'] == 'gap':
            from .quote_gap_audit import validate_gap_review
            if submission.get('packet_sha256') != digest(packet):
                raise AcceptanceGuardError('gap review must bind complete packet')
            return validate_gap_review(packet['gap_audit'], submission, self.reviewer)
        if envelope["kind"] == "facts":
            return validate_fact_review(packet, submission, reviewer=self.reviewer)
        if envelope["kind"] not in {"plan", "answer"}:
            raise AcceptanceGuardError("invalid persisted review kind")
        return validate_structured_review(
            packet, submission, reviewer=self.reviewer, stage=envelope["kind"],
            expected_kind=packet.get("expected_kind", "support"),
            expected_tasks=packet.get("expected_tasks"),
        )

    def submit(self, slot: str, submission: Mapping[str, Any]) -> dict[str, Any]:
        envelope = self._packet(slot)
        if not isinstance(submission, Mapping):
            raise AcceptanceGuardError("host submission must be an object")
        decision = self._validate(envelope, submission)
        _, path = self._paths(slot)
        _publish(path, {
            "slot": slot, "reviewer": self.reviewer,
            "envelope_sha256": digest(envelope), "submission": deepcopy(dict(submission)),
            "submission_sha256": digest(submission), "validation": decision,
        })
        return decision

    def receive(self, slot: str) -> dict[str, Any]:
        envelope = self._packet(slot)
        packet_path, path = self._paths(slot)
        if not path.exists() and not path.is_symlink():
            raise HostReviewPending(packet_path)
        receipt = _read(path)
        submission = receipt.get("submission")
        if (receipt.get("slot") != slot or receipt.get("reviewer") != self.reviewer
                or receipt.get("envelope_sha256") != digest(envelope)
                or not isinstance(submission, dict)
                or receipt.get("submission_sha256") != digest(submission)
                or receipt.get("validation") != self._validate(envelope, submission)):
            raise AcceptanceGuardError("host review submission changed")
        return deepcopy(submission)

    def callback(self, *, kind: str):
        """Adapt to existing review callbacks; missing review raises explicitly."""
        def review(packet: Mapping[str, Any]) -> dict[str, Any]:
            case_id = packet.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise AcceptanceGuardError("host review case id required")
            slot = f"{case_id}:{kind}:{packet.get('arm', '')}"
            self.request(slot, packet, kind=kind)
            return self.receive(slot)
        return review
