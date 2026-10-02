"""Build the public website from checked-in, already exported examples.

This is the portable Pages build, not the original-session evidence check.
It reads no local configuration, data bundle, or private conversation records.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.build_public_showcase import (
    ASSETS, IDS, keys, read_json, scan, validate_case, validate_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA_FIELDS = ("data_version", "note", "rows", "source_sha256")
FILES = set(ASSETS) | {"data.json", "cases/index.json"} | {
    f"cases/{name}.json" for name in IDS
}


def public_html(text: str) -> str:
    start = '<section id="workspace"'
    end = '<section id="report"'
    script = '<script type="module" src="live.js"></script>'
    if (text.count(start) != 1 or text.count(end) != 1
            or text.count(script) != 1
            or text.count('data-runtime="showcase"') != 1
            or text.index(start) >= text.index(end)):
        raise ValueError("Unexpected source page structure")
    return (text[:text.index(start)] + text[text.index(end):]).replace(script, "", 1)


def validate_data(data: dict) -> None:
    keys(data, PUBLIC_DATA_FIELDS)
    scan(data)
    if not isinstance(data["rows"], list) or len(data["rows"]) != 30:
        raise ValueError("Unexpected policy data rows")
    for row in data["rows"]:
        keys(row, {"product", "name", "period", "world", "china"})
        if (type(row["world"]) is not int or type(row["china"]) is not int
                or not 0 <= row["china"] <= row["world"]):
            raise ValueError("Invalid policy amount")


def verify(site: Path) -> dict:
    if site.is_symlink() or any(p.is_symlink() for p in site.rglob("*")):
        raise ValueError("Symlinks are not public assets")
    actual = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    if actual != FILES:
        raise ValueError("Public asset allowlist mismatch")
    html = (site / "index.html").read_text(encoding="utf-8")
    if (html.count('data-runtime="showcase"') != 1
            or any(s in html for s in ('src="live.js"', 'id="workspace"',
                                      'id="question-form"', 'id="open-model-settings"'))):
        raise ValueError("Local interface leaked into public page")
    index = read_json(site / "cases/index.json")
    validate_catalog(index)
    for name in IDS:
        case = read_json(site / f"cases/{name}.json")
        if case["id"] != name:
            raise ValueError("Case filename and identity differ")
        validate_case(case)
    validate_data(read_json(site / "data.json"))
    return {"status": "verified", "case_count": len(IDS), "asset_count": len(actual)}


def build(source: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("Output exists; choose a new directory")
    if source.is_symlink():
        raise ValueError("Unsafe source directory")
    payloads = {}
    for name in FILES:
        path = source / name
        relative = Path(name)
        if any(source.joinpath(*relative.parts[:i]).is_symlink()
               for i in range(1, len(relative.parts) + 1)):
            raise ValueError("Unsafe source asset")
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing or empty public asset: {name}")
        content = path.read_bytes()
        if name == "index.html":
            content = public_html(content.decode("utf-8")).encode("utf-8")
        elif name == "data.json":
            data = read_json(path)
            public = {field: data[field] for field in PUBLIC_DATA_FIELDS}
            validate_data(public)
            content = (json.dumps(public, ensure_ascii=False, indent=2,
                                  sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        elif name.startswith("cases/"):
            data = read_json(path)
            if name == "cases/index.json":
                validate_catalog(data)
            else:
                if data["id"] != Path(name).stem:
                    raise ValueError("Case filename and identity differ")
                validate_case(data)
            content = (json.dumps(data, ensure_ascii=False, indent=2,
                                  sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        payloads[name] = content
    # Validate every input before creating an output; interrupted builds fail verify.
    output.mkdir(parents=True)
    for name, content in payloads.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return verify(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "web/design-preview")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = verify(args.verify) if args.verify else build(args.source, args.output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
