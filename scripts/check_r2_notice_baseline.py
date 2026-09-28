"""Record the first deterministic parser result for the frozen R2 notice.

Offline only. This produces diagnostic artifacts, never enables a policy or
edits data registries. Existing output is refused to preserve the first result.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path

from tradeintel_ai.announcement_parser import parse_announcement_text

EXPECTED = "a2b8d9ddeada1a7e0a97926a70da545eb40e883ec547c02e5d52221bf2b6ed78"


class OriginalText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_pre = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.in_pre = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.in_pre = False

    def handle_data(self, text):
        if self.in_pre:
            self.parts.append(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError("R2 source differs from the frozen official HTML")
    html = OriginalText()
    html.feed(raw.decode("utf-8"))
    text = "".join(html.parts)
    if not text.strip():
        raise ValueError("Official HTML has no preformatted original text")
    result = parse_announcement_text(
        "r2_semiconductor_2025", "fr202523912", text,
        url="https://www.govinfo.gov/content/pkg/FR-2025-12-29/html/2025-23912.htm")
    root = Path(__file__).resolve().parents[1]
    code = root / "src/tradeintel_ai/announcement_parser.py"
    result["baseline_metadata"] = {
        "source_sha256": EXPECTED,
        "parser_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
        "model_calls": 0, "policy_enabled": False,
        "boundary": "First parser diagnostic, not a passed migration or model score",
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({f["field"]: f["status"] for f in result["fields"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
