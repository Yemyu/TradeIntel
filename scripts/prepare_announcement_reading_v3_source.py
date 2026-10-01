"""Extract one saved Federal Register notice into a disabled v3 source store.

This is an offline provenance step, not a model call or policy activation.
The downloaded Federal Register response is an HTML wrapper around one <pre>.
"""
from __future__ import annotations

import argparse
from datetime import date as Date
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path

from tradeintel_ai.policy_documents import build_document, build_document_store


class _PreText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pre_count = 0
        self.inside = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "pre":
            if self.inside:
                raise ValueError("nested pre element")
            self.inside = True
            self.pre_count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            if not self.inside:
                raise ValueError("unmatched pre end tag")
            self.inside = False

    def handle_data(self, data: str) -> None:
        if self.inside:
            self.parts.append(data)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(raw_path: Path, metadata_path: Path, reading_path: Path,
            store_path: Path) -> dict[str, str | int]:
    if any(path.is_symlink() or not path.is_file()
           for path in (raw_path, metadata_path)):
        raise ValueError("raw notice and metadata must be regular files")
    if reading_path.exists() or store_path.exists():
        raise FileExistsError("refusing to overwrite a frozen source artifact")
    if reading_path.parent != store_path.parent or not reading_path.parent.is_dir():
        raise ValueError("output files must share an existing directory")

    original = raw_path.read_bytes()
    metadata = json.loads(metadata_path.read_bytes())
    number = metadata.get("document_number")
    publication_date = metadata.get("publication_date")
    url = metadata.get("raw_text_url")
    if not isinstance(number, str) or not isinstance(publication_date, str) \
            or not isinstance(url, str) or not url.startswith("https://www.federalregister.gov/"):
        raise ValueError("official notice metadata is incomplete")
    Date.fromisoformat(publication_date)
    parser = _PreText()
    parser.feed(original.decode("utf-8"))
    parser.close()
    if parser.pre_count != 1 or parser.inside:
        raise ValueError("expected one complete pre element")
    text = "".join(parser.parts)
    if f"[FR Doc No: {number}]" not in text \
            or f"[FR Doc. {number} Filed" not in text:
        raise ValueError("source notice identity or closing marker missing")
    if "[Notices]" not in text or not text.strip():
        raise ValueError("source notice body is missing")
    policy_id = f"FR-{number}"
    source_id = f"fr:{number}:p1"
    doc = build_document({
        "policy_id": policy_id,
        "data_version": "announcement-reading-v3-candidate",
        "sources": [{"id": source_id, "url": url, "text": text,
                     "document_sha256": _sha256(original)}],
    }, doc_id=policy_id, publication_time=publication_date, status="disabled")
    store = build_document_store([doc], policy_id=policy_id)
    reading_bytes = text.encode("utf-8")
    store_bytes = (json.dumps(store, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")) + "\n").encode("utf-8")
    reading_path.write_bytes(reading_bytes)
    store_path.write_bytes(store_bytes)
    return {"document_number": number, "publication_date": publication_date,
            "doc_version": doc["doc_version"], "status": doc["status"],
            "raw_sha256": _sha256(original), "reading_sha256": _sha256(reading_bytes),
            "store_sha256": _sha256(store_bytes), "reading_bytes": len(reading_bytes)}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--raw", required=True, type=Path)
    cli.add_argument("--metadata", required=True, type=Path)
    cli.add_argument("--reading", required=True, type=Path)
    cli.add_argument("--store", required=True, type=Path)
    args = cli.parse_args()
    print(json.dumps(prepare(args.raw, args.metadata, args.reading, args.store),
                     ensure_ascii=False, indent=2))
