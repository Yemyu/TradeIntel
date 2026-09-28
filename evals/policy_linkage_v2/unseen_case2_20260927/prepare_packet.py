"""Extract a pinned GovInfo PRE document and verify every reference quote."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT / "tmp/unseen-linkage-case2-20260927"


class PreText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def main():
    ref_path = Path(__file__).with_name("reference.json")
    ref = json.loads(ref_path.read_text())
    raw = (CASE / "2025-16733.htm").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ref["source_file_sha256"]
    assert len(raw) == ref["source_file_bytes"]
    parser = PreText()
    parser.feed(raw.decode())
    original = "".join(parser.parts)
    # Original bytes remain separately pinned. Only whitespace is normalized;
    # blank lines and four-space paragraph starts delimit stored paragraphs.
    groups = re.split(r"\n\s*\n|\n(?=    \S)", original.strip())
    paragraphs = [" ".join(group.split()) for group in groups if group.strip()]
    text = "\n".join(paragraphs) + "\n"
    assert "".join(text.split()) == "".join(original.split())
    locations = []
    quotes = sorted({q for f in ref["fields"] for q in f["quotes"]} | set(ref["linkage"]["quotes"]))
    for quote in quotes:
        indices = [i + 1 for i, p in enumerate(paragraphs) if quote in p]
        if len(indices) != 1:
            raise ValueError(f"Quote absent or ambiguous ({indices}): {quote}")
        locations.append({"quote": quote, "paragraph": indices[0]})
    out = CASE / "frozen-packet"
    out.mkdir(exist_ok=False)
    manifest = {"case_id": ref["case_id"], "product_executed": False,
                "reference_sha256": hashlib.sha256(ref_path.read_bytes()).hexdigest(),
                "source_sha256": ref["source_file_sha256"],
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "paragraphs": len(paragraphs), "unique_reference_quotes": len(quotes),
                "normalization": "whitespace only; full PRE character content retained"}
    (out / "source-text.txt").write_text(text)
    (out / "quote-locations.json").write_text(json.dumps(locations, ensure_ascii=False, indent=2) + "\n")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
