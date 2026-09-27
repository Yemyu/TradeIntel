"""Official source registry with guarded fetching (offline-first).

The registry lists the official sources allowed for policy/data updates.
Fetching enforces hard limits at the real ``urllib`` handler level -- a
custom ``HTTPRedirectHandler`` that rejects cross-host or downgraded hops
BEFORE the next request is issued, a hop limit, a response size cap and a
timeout -- and records the ACTUAL final URL from the response.

Fetched bytes are saved atomically next to their metadata only after the
stored content hash is verified; the fetch metadata alone never claims that
the content has been saved.  The HTTP transport is injectable for tests, but
the redirect policy lives in the real handler class and is tested directly,
so a stub returning a fake final URL cannot pass it.  Nothing here publishes
or replaces existing data; every fetch result is a CANDIDATE.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "source-registry-v1"
MAX_BYTES = 20 * 1024 * 1024
DEFAULT_TIMEOUT = 30
MAX_REDIRECTS = 3

OFFICIAL_SOURCES: list[dict[str, Any]] = [
    {"source_id": "cbp-csms-63577329", "name": "CBP CSMS 63577329 (2025-01-01 301 execution)",
     "url": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1",
     "kind": "official_bulletin", "enabled": True},
    {"source_id": "federalregister-2024-29462", "name": "Federal Register 2024-29462",
     "url": "https://www.federalregister.gov/documents/2024/12/16/2024-29462/notice-of-modification-chinas-acts-policies-and-practices-related-to-technology-transfer",
     "kind": "official_notice", "enabled": True},
]


def validate_registry(entries: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [entry.get("source_id") for entry in entries]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("source_id must be unique non-empty strings")
    for entry in entries:
        url = entry.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError(f"official sources must use https: {url!r}")
    return {"status": "valid", "source_count": len(entries)}


class OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Same-host https-only redirect policy at the real handler level.

    Every hop is validated BEFORE the next request is issued: https only,
    same host only, at most ``max_redirects`` hops (counted across the whole
    chain via a shared counter, not per Request object).
    """

    def __init__(self, *, max_redirects: int = MAX_REDIRECTS):
        super().__init__()
        self._max_redirects = max_redirects
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        origin = urllib.parse.urlsplit(req.full_url)
        if parts.scheme != "https":
            raise ValueError(f"拒绝降级跳转（非https）: {newurl}")
        if parts.netloc != origin.netloc:
            raise ValueError(f"拒绝跨主机跳转: {newurl}")
        if self.hops + 1 > self._max_redirects:
            raise ValueError(f"重定向次数超过上限 {self._max_redirects}")
        self.hops += 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_transport(url: str, *, timeout: int,
                      max_bytes: int = MAX_BYTES) -> tuple[bytes, str]:
    """Real HTTP transport with size cap and the official redirect handler.

    Returns (content, ACTUAL final URL from the response object).
    """
    request = urllib.request.Request(url, headers={"User-Agent": "TradeIntel-controlled-update/1.0"})
    opener = urllib.request.build_opener(OfficialRedirectHandler())
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 512)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"响应超过大小上限 {max_bytes} 字节，已中止")
            chunks.append(chunk)
    return b"".join(chunks), final_url


def fetch_source(source_id: str, *, transport: Callable[..., tuple[bytes, str]] | None = None,
                 timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Fetch one registered source through the guarded transport.

    Returns fetch metadata (hashes, size, ACTUAL final URL).  The result is a
    CANDIDATE for the controlled update flow; ``content_saved`` stays False
    until :func:`save_candidate` has persisted and hash-verified the bytes.
    """
    entry = next((item for item in OFFICIAL_SOURCES if item["source_id"] == source_id), None)
    if entry is None or not entry.get("enabled"):
        raise ValueError(f"未登记或未启用的来源: {source_id}")
    validate_registry(OFFICIAL_SOURCES)
    transport = transport or default_transport
    content, final_url = transport(entry["url"], timeout=timeout)
    if not isinstance(content, bytes):
        raise ValueError("transport must return raw bytes")
    if len(content) > MAX_BYTES:
        raise ValueError(f"响应超过大小上限 {MAX_BYTES} 字节")
    return {"source_id": source_id, "url": entry["url"], "final_url": final_url,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "content_saved": False,
            "status": "candidate_not_activated",
            "boundary": "抓取结果只是候选材料；进入正式版本必须走 stage/diff/confirm/activate 流程。"}


def candidates_dir(root: Path) -> Path:
    return Path(root) / ".local" / "update-candidates"


def save_candidate(root: Path, fetched: dict[str, Any], content: bytes) -> dict[str, Any]:
    """Persist candidate bytes and metadata atomically, after hash verification.

    The recorded sha256 must match the actual bytes; only then are the
    content file and the record published (both via atomic replace), and the
    returned path can be used by the parser to read the ORIGINAL bytes back.
    """
    if not isinstance(content, bytes):
        raise ValueError("candidate content must be raw bytes")
    digest = hashlib.sha256(content).hexdigest()
    if digest != fetched.get("sha256"):
        raise ValueError("candidate content hash does not match fetch metadata; refused")
    directory = candidates_dir(root) / f"{fetched['source_id']}-{digest[:12]}"
    directory.mkdir(parents=True, exist_ok=True)
    content_path = directory / "content.bin"
    record_path = directory / "record.json"
    _atomic_write_bytes(content_path, content)
    record = {**{key: value for key, value in fetched.items() if key != "content_saved"},
              "content_saved": True,
              "content_file": str(content_path.relative_to(root)),
              "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _atomic_write_json(record_path, record)
    # Verify what is on disk is byte-identical before declaring success.
    if hashlib.sha256(content_path.read_bytes()).hexdigest() != digest:
        raise ValueError("saved candidate content failed verification")
    return {"record_path": str(record_path), "content_path": str(content_path),
            "sha256": digest, "size": len(content)}


def load_candidate_content(root: Path, record: dict[str, Any]) -> bytes:
    """Read the saved candidate bytes back (the parser's input)."""
    path = Path(root) / record["content_file"]
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        raise ValueError("saved candidate content hash mismatch on read")
    return content


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
