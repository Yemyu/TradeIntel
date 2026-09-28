"""Extract *search-only* Chinese HS4 headings from the official 2026 tariff PDF.

Run with a Python environment containing pypdf. The output is not used as a
US classification authority: every candidate still requires a Census heading
for the selected direction and month, and the reader confirms that scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader


SOURCE_URL = "https://gss.mof.gov.cn/gzdt/zhengcefabu/202512/t20251231_3981044.htm"
HEADING = re.compile(r"^\s*(\d{2})\.(\d{2})\s+(.+)$")
ITEM = re.compile(r"^\s*\d{1,5}\s+\d{4}\.\d{2,4}")


def extract(source: Path) -> dict:
    raw = source.read_bytes()
    reader = PdfReader(source)
    candidates: dict[str, list[dict]] = {}
    for page_index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if "序号 税则号列 货品名称" not in text:
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = HEADING.match(line)
            if not match:
                continue
            code = match[1] + match[2]
            if int(code[:2]) > 97:
                continue
            parts = [match[3].strip()]
            for next_line in lines[index + 1:index + 9]:
                if "：" in "".join(parts) or ":" in "".join(parts):
                    break
                if HEADING.match(next_line) or ITEM.match(next_line):
                    break
                parts.append(next_line.strip())
            joined = "".join(parts)
            colon = joined.find("：")
            if colon < 0:
                continue
            label = re.sub(r"\s+", "", joined[:colon]).strip("：:；; ")
            if not 2 <= len(label) <= 260 or "税率" in label or "序号" in label:
                continue
            candidates.setdefault(code, []).append({"label": label, "pdf_page": page_index + 1})
    headings = {}
    duplicates = {}
    for code, values in sorted(candidates.items()):
        labels = {item["label"] for item in values}
        if len(labels) != 1:
            duplicates[code] = values
            continue
        headings[code] = values[0]
    return {"schema": "mof-2026-hs4-search-only-v1", "source_url": SOURCE_URL,
            "source_pdf_sha256": hashlib.sha256(raw).hexdigest(),
            "source_pages": len(reader.pages), "headings": headings,
            "excluded_ambiguous_codes": sorted(duplicates)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"headings": len(result["headings"]),
                      "ambiguous": result["excluded_ambiguous_codes"],
                      "pdf_pages": result["source_pages"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
