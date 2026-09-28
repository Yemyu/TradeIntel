"""Prepare the pinned notice and review packet, without executing the product.

The HTML is downloaded separately from GovInfo. This extractor retains every
body paragraph, including list labels stored in data-list-text attributes.
It does not call a model, submit candidates, choose routes or generate reports.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path


class NoticeText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.block = None
        self.pending_label = ""
        self.label = ""
        self.parts = []
        self.body_text = []
        self.paragraphs = []
        self.paragraph_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
        if not self.in_body:
            return
        if tag == "li":
            self.pending_label = dict(attrs).get("data-list-text", "")
        if tag in {"p", "h1"}:
            if self.block is not None:
                raise ValueError("Nested paragraph in pinned HTML")
            self.block = tag
            self.parts = []
            self.label, self.pending_label = self.pending_label, ""

    def handle_data(self, text):
        if self.in_body:
            self.body_text.append(text)
            if self.block is not None:
                self.parts.append(text)

    def handle_endtag(self, tag):
        if tag == self.block:
            text = "".join(self.parts).strip()
            self.paragraph_text.append(text)
            self.paragraphs.append((self.label + " " if self.label else "") + text)
            self.block = None
        if tag == "body":
            self.in_body = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference_path = Path(__file__).with_name("reference.json")
    reference_raw = reference_path.read_bytes()
    reference = json.loads(reference_raw)
    raw = args.source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != reference["source_file_sha256"] or len(raw) != reference["source_file_bytes"]:
        raise ValueError("Official source changed; preserve original and stop")
    extractor = NoticeText()
    extractor.feed(raw.decode("utf-8"))
    compact = lambda text: "".join(text.split())
    if compact("".join(extractor.body_text)) != compact("".join(extractor.paragraph_text)):
        raise ValueError("Body text omitted by paragraph extraction")
    if not extractor.paragraphs or extractor.block is not None:
        raise ValueError("Incomplete source extraction")
    text = "\n".join(extractor.paragraphs) + "\n"
    quotes = sorted({quote for row in reference["fields"] for quote in row["quotes"]}
                    | set(reference["linkage"]["quotes"]))
    locations = []
    for quote in quotes:
        matches = [i + 1 for i, paragraph in enumerate(extractor.paragraphs) if quote in paragraph]
        if len(matches) != 1:
            raise ValueError(f"Reference quote is absent or ambiguous: {quote[:80]}")
        locations.append({"quote": quote, "paragraph": matches[0]})
    manifest = {"case_id": reference["case_id"], "preparation_only": True,
                "product_executed": False, "model_calls": 0,
                "reference_sha256": hashlib.sha256(reference_raw).hexdigest(),
                "source_file_sha256": digest, "source_file_bytes": len(raw),
                "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "source_text_bytes": len(text.encode()),
                "paragraphs": len(extractor.paragraphs),
                "unique_reference_quotes": len(locations)}
    args.output.mkdir(parents=True, exist_ok=True)
    outputs = {"source-text.txt": text,
               "quote-locations.json": json.dumps(locations, ensure_ascii=False, indent=2) + "\n",
               "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"}
    if any((args.output / name).exists() for name in outputs):
        raise ValueError("Output already exists; do not overwrite frozen preparation")
    for name, contents in outputs.items():
        (args.output / name).write_text(contents, encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
