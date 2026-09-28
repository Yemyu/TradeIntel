"""Prepare pinned offline field-suggestion packages without an API call.

Each output directory is new; manifest.json is written last. A missing manifest
means preparation did not complete and must never be used as an eval input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from scripts.run_r2_migration import SOURCE_SHA256 as R2_SHA256
from scripts.run_r2_migration import SOURCE_URL as R2_URL
from scripts.run_r2_migration import extract_text as extract_r2_text
from tradeintel_ai.announcement_extraction_pilot import (
    D2_SOURCE_SHA256, D2_SOURCE_URL, _BulletinText, extract_d2_text, make_disabled_store,
    prepare_request,
)
from tradeintel_ai.announcement_parser import parse_announcement_text

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = ("original.html", "source.txt", "document-store.json", "request.json",
                 "baseline.json", "source-metadata.json")
CODE_FILES = (
    "src/tradeintel_ai/announcement_extraction_pilot.py",
    "src/tradeintel_ai/policy_candidates.py",
    "src/tradeintel_ai/policy_documents.py",
    "src/tradeintel_ai/announcement_parser.py",
    "scripts/prepare_policy_extraction_pilot.py",
)
SOURCES = {
    "r2": ROOT / "evals/policy_extraction_v1/sources/fr-2025-23912.html",
    "d2": ROOT / "evals/policy_extraction_v1/sources/csms-65794272.html",
    "h1": ROOT / "evals/policy_extraction_v1/selection-20260926/csms-66492057.html",
    "h2": ROOT / "evals/policy_extraction_v1/selection-20260926/csms-66814923.html",
}
SELECTION = ROOT / "evals/policy_extraction_v1/selection-20260926/selection.json"
REFERENCE = ROOT / "docs/handoff/POLICY_ACCEPTANCE_DESIGN_20260926.zh-CN.md"
REFERENCE_SHA256 = "b2f76d4009a19efa4af53e2ac2dea22e67b9f525f818cfb4218d9e0d908b3df7"
ACCEPTANCE = {
    "h1": {"bulletin": "66492057", "date": "10/10/2025",
           "url": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3f69699",
           "raw_sha256": "042607081d74682be7795a6d50b3184f881916d9f6478bb8361e83cf8998589b",
           "text_sha256": "3ca11fd0385f9912353e13168309b7f0698cfb60c191971d77041624808ea52f",
           "policy_id": "h1_timber_furniture_2025", "source_id": "csms66492057",
           "critical_facts": 46, "ordinary_facts": 5},
    "h2": {"bulletin": "66814923", "date": "11/14/2025",
           "url": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3fb83cb",
           "raw_sha256": "2ef6158c52a8adfbc4715732eb9f3e9ac3a7898b617796b66caf5873c25fde58",
           "text_sha256": "0ad19b95364445b7e4227cc040e61208f2d1723b7f6564e9adb3b0a8f7959cb0",
           "policy_id": "h2_agricultural_exemptions_2025", "source_id": "csms66814923",
           "critical_facts": 25, "ordinary_facts": 4},
}
# Indexes are visible-bulletin blocks, not generated document section IDs.
# Negative indexes denote the title (-2) and dateline (-1). None records an
# absence claim and is explicitly tied to the complete source digest.
FACT_BLOCKS = {
    "h1": {
        "TITLE": (-2,), "PUB": (-1,), "EFFECT": (5,), "CLOCK": (5,),
        "ENTRY": (5,), "ORIGIN": (7, 25, 32, 38, 44, 53, 62),
        "R01": (7, 23), "R02": (25, 30), "R03": (32, 36),
        "R04": (38, 42), "R20": (44, 52), "R21": (53, 61),
        "R22": (62, 70), "MEANING": (23, 30, 36, 42, 52, 61, 70),
        "AUTO": (72,), "IEEPA": (74,), "CA": (74, 75), "MX": (74, 76),
        "RECIP": (74, 77), "BR": (74, 78), "IN": (74, 79),
        "FILE-CA-MX": (80,), "FILE-RECIP": (82,), "FILE-BR": (83,),
        "FILE-IN": (84,), "158": (86, 87), "DRAWBACK": (89,),
        "FTZ": (91,), "LATER": None,
    },
    "h2": {
        "TITLE": (-2,), "PUB": (-1,), "EFFECT": (1,), "CLOCK": (1,),
        "ENTRY": (1,), "ORIGIN": None, "SCOPE": (1,), "MISSING": (1,),
        "EXEMPT": (1,), "RATE": (1,), "FILE-237": (1,), "FILE-11": (2,),
        "USE": (14,), "CORRECT": (15,), "TEN": (15,), "PSC": (15,),
        "PROTEST": (15,), "REVISION": (0, 16),
    },
}
H1_CODES = (
    "44031100 44032301 44032601 44069100 44071300 44032101 44032401 "
    "44039901 44071100 44071400 44032201 44032501 44061100 44071200 "
    "44071900 9401614011 9401614031 9401616011 9401616031 9403409060 "
    "9403608093 9403910080"
).split()
H2_CODES = (
    "08059001 08119080 14049090 19059010 19059090 20089921 20093160 "
    "20098970 20099040 21069099 33012951"
).split()


def _acceptance_selection(case: str) -> dict:
    """Keep the design-seen case identity and reference immutable at packaging time."""
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != REFERENCE_SHA256 \
            or selection.get("reference_sha256") != REFERENCE_SHA256 \
            or selection.get("role") != "acceptance_design_seen":
        raise ValueError("acceptance reference or selection identity changed")
    chosen = next((item for item in selection.get("cases", []) if item.get("id") == case.upper()), None)
    expected = ACCEPTANCE[case]
    if chosen is None or any(chosen.get(key) != expected[match] for key, match in (
            ("bulletin", "bulletin"), ("url", "url"), ("source_sha256", "raw_sha256"),
            ("text_sha256", "text_sha256"), ("critical_facts", "critical_facts"),
            ("ordinary_facts", "ordinary_facts"))):
        raise ValueError("acceptance selection does not match pinned case")
    return chosen


def _extract(case: str, raw: bytes, source: Path) -> tuple[str, list[dict[str, str]], str, str, str]:
    if case == "r2":
        return extract_r2_text(source), [], "r2_semiconductor_2025", "fr202523912", R2_URL
    if case == "d2":
        text, attachments = extract_d2_text(raw)
        return text, attachments, "d2_copper_2025", "csms65794272", D2_SOURCE_URL
    spec = ACCEPTANCE[case]
    _acceptance_selection(case)
    parser = _BulletinText()
    parser.feed(raw.decode("utf-8"))
    text = "\n".join((parser.title, parser.dateline, *parser.blocks))
    if not parser.title.startswith(f"CSMS # {spec['bulletin']} - ") \
            or spec["date"] not in parser.dateline \
            or hashlib.sha256(text.encode("utf-8")).hexdigest() != spec["text_sha256"]:
        raise ValueError("acceptance title, date or full extracted text changed; stop and review")
    return text, parser.attachments, spec["policy_id"], spec["source_id"], spec["url"]


def _scorecard(case: str, text: str, store: dict) -> dict:
    """Transcribe the frozen checklist with independently located source lines."""
    reference = REFERENCE.read_text(encoding="utf-8")
    if hashlib.sha256(reference.encode("utf-8")).hexdigest() != REFERENCE_SHA256:
        raise ValueError("acceptance reference changed")
    prefix = case.upper()
    rows = {}
    for line in reference.splitlines():
        if line.startswith(f"| {prefix}-"):
            cells = [part.strip() for part in line.strip().strip("|").split("|")]
            if len(cells) == 4 and cells[0].startswith(f"{prefix}-"):
                rows[cells[0]] = {"expected": cells[1],
                                  "importance": "critical" if cells[3] == "关键" else "ordinary"}
    expected_ids = {f"{prefix}-{name}" for name in FACT_BLOCKS[case]}
    if set(rows) != expected_ids:
        raise ValueError("acceptance reference table IDs differ from fixed fact map")
    blocks = text.split("\n")
    if len(blocks) < 3:
        raise ValueError("acceptance source has no visible blocks")
    doc = store["documents"][0]
    saved_text = "".join(section["text"] for section in doc["sections"])
    if saved_text != text:
        raise ValueError("scorecard source differs from saved document")

    def evidence(index: int) -> dict:
        position = index + 2 if index >= 0 else index + 2
        quote = blocks[position]
        start = sum(len(part) + 1 for part in blocks[:position])
        end = start + len(quote)
        if not quote or text[start:end] != quote:
            raise ValueError("scorecard quote absent from source")
        sections = [section["id"] for section in doc["sections"]
                    if max(start, section["start"]) < min(end, section["end"])]
        if not sections:
            raise ValueError("scorecard quote has no saved section")
        return {"quote": quote, "start": start, "end": end,
                "section_ids": sections, "visible_block": index}

    facts = []
    for fact_id, row in rows.items():
        name = fact_id[len(prefix) + 1:]
        indexes = FACT_BLOCKS[case][name]
        facts.append({"id": fact_id, **row,
                      "evidence": [evidence(index) for index in indexes] if indexes else [],
                      "absence_check": ("entire pinned source; no affirmative quote"
                                        if indexes is None else None),
                      "model_score": None, "coverage": None, "review_note": None})
    codes = H1_CODES if case == "h1" else H2_CODES
    code_positions = list(range(8, 23)) + [26, 27, 28, 29, 33, 34, 35] if case == "h1" \
        else list(range(3, 14))
    if len(codes) != len(code_positions):
        raise ValueError("code count differs from bulletin map")
    h2_code_limits = {}
    if case == "h2":
        for line in reference.splitlines():
            match = re.fullmatch(r"\| (\d{8}) \| (.+) \|", line)
            if match:
                h2_code_limits[match.group(1)] = match.group(2)
        if set(h2_code_limits) != set(codes):
            raise ValueError("H2 code descriptions differ from fixed reference")
    for n, (code, position) in enumerate(zip(codes, code_positions), 1):
        cite = evidence(position)
        if code not in cite["quote"].replace(".", ""):
            raise ValueError(f"{prefix} merchandise code quote missing: {code}")
        precision = ("whole_hts8" if n <= 15 else "hts10_partial") if case == "h1" \
            else "text_limited"
        limit = h2_code_limits.get(code, "retain the bulletin's product and branch limits")
        facts.append({"id": f"{prefix}-CODE-{n:02d}", "importance": "critical",
                      "expected": f"{code}; precision={precision}; {limit}",
                      "evidence": [cite], "absence_check": None,
                      "model_score": None, "coverage": None, "review_note": None})
    critical = sum(f["importance"] == "critical" for f in facts)
    ordinary = sum(f["importance"] == "ordinary" for f in facts)
    if (critical, ordinary) != (ACCEPTANCE[case]["critical_facts"],
                                ACCEPTANCE[case]["ordinary_facts"]):
        raise ValueError("scorecard fact totals differ from frozen selection")
    return {"schema_version": "policy-extraction-scorecard-v1", "case": case,
            "role": "acceptance_design_seen", "doc_version": doc["doc_version"],
            "reference_sha256": REFERENCE_SHA256,
            "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "critical_facts": critical, "ordinary_facts": ordinary,
            "warning": "参考只供人工逐项审阅；不是独立金标，不进入模型请求。",
            "facts": facts}


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def prepare(case: str, output: Path, *, source: Path | None = None) -> dict:
    if case not in SOURCES:
        raise ValueError("case must be r2, d2, h1 or h2")
    source = source or SOURCES[case]
    raw = source.read_bytes()
    expected = {"r2": R2_SHA256, "d2": D2_SOURCE_SHA256,
                **{name: spec["raw_sha256"] for name, spec in ACCEPTANCE.items()}}[case]
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"{case} source hash mismatch; do not use a changed notice as the same case")
    text, attachments, policy_id, source_id, url = _extract(case, raw, source)
    store = make_disabled_store(policy_id, source_id, text, url=url, source_sha256=actual)
    document = store["documents"][0]
    request = prepare_request(store, document["doc_version"])
    scorecard = _scorecard(case, text, store) if case in ACCEPTANCE else None

    # Keep the old baseline exactly as it behaves, including any wrong known
    # fields. The safety gate for future adoption is in policy_candidates.
    baseline = parse_announcement_text(policy_id, source_id, text, url=url)
    fields = {item["field"]: item for item in baseline["fields"]}
    baseline_summary = {
        "schema_version": "policy-extraction-baseline-v1",
        "case": case,
        "fields": baseline["fields"],
        "warning": "旧规则解析器输出供开发对照；known 也未经过语义核对。",
        "reporting_headings_as_merchandise": [entry["code"] for entry in
            (fields["hts_codes"].get("value") or []) if entry["code"].startswith(("98", "99"))]
            if fields["hts_codes"]["status"] == "known" else [],
    }
    # The output directory must not pre-exist; an interrupted directory lacks
    # manifest.json and cannot accidentally be treated as a completed package.
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(source, output / "original.html")
    (output / "source.txt").write_text(text, encoding="utf-8")
    _write_json(output / "document-store.json", store)
    _write_json(output / "request.json", request)
    _write_json(output / "baseline.json", baseline_summary)
    if scorecard is not None:
        _write_json(output / "scorecard.json", scorecard)
    _write_json(output / "source-metadata.json", {
        "case": case, "role": "acceptance_design_seen" if case in ACCEPTANCE else "development_seen",
        "source_url": url,
        "source_sha256": actual, "doc_version": document["doc_version"],
        "extracted_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "reference_sha256": REFERENCE_SHA256 if case in ACCEPTANCE else None,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attachments_not_supplied_to_model": attachments,
        "boundary": "原文快照为设计已见案例；评分表与附件不在模型输入中。"
                    if case in ACCEPTANCE else "原文快照用于开发；正文以外的附件不在模型输入中。",
    })
    package_files = PACKAGE_FILES + (("scorecard.json",) if scorecard is not None else ())
    manifest = {"schema_version": "policy-extraction-package-v1", "case": case,
                "request_bytes": request["request_bytes"],
                "request_sha256": request["request_sha256"],
                "git_head": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                for name in CODE_FILES},
                "files_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                                 for name in package_files}}
    _write_json(output / "manifest.json", manifest)
    return {"case": case, "doc_version": document["doc_version"],
            "request_bytes": request["request_bytes"],
            "source_sha256": actual, "baseline_reporting_headings":
                baseline_summary["reporting_headings_as_merchandise"],
            "output": str(output)}


def verify_package(package: Path) -> dict:
    """Read back a complete package and recheck the original, prompt and code."""
    manifest_path = package / "manifest.json"
    if not manifest_path.is_file() or not manifest_path.stat().st_size:
        raise ValueError("package is incomplete: manifest missing or empty")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        case = manifest.get("case")
        package_files = PACKAGE_FILES + (("scorecard.json",) if case in ACCEPTANCE else ())
        if manifest.get("schema_version") != "policy-extraction-package-v1" \
                or case not in SOURCES \
                or set(manifest.get("files_sha256", {})) != set(package_files) \
                or set(manifest.get("code_sha256", {})) != set(CODE_FILES):
            raise ValueError("package manifest has missing or unexpected hashes")
        for name, expected in manifest["files_sha256"].items():
            path = package / name
            if not isinstance(expected, str) or len(expected) != 64 or not path.is_file() \
                    or not path.stat().st_size or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"package file missing, empty or changed: {name}")
        for name, expected in manifest["code_sha256"].items():
            if not isinstance(expected, str) or len(expected) != 64 \
                    or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"package code changed: {name}")
        raw = (package / "original.html").read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        expected_hash = {"r2": R2_SHA256, "d2": D2_SOURCE_SHA256,
                         **{name: spec["raw_sha256"] for name, spec in ACCEPTANCE.items()}}[case]
        if source_hash != expected_hash:
            raise ValueError("official source bytes do not match the pinned notice")
        text, _, policy_id, source_id, url = _extract(case, raw, package / "original.html")
        if (package / "source.txt").read_text(encoding="utf-8") != text:
            raise ValueError("extracted source text differs from official source")
        store = json.loads((package / "document-store.json").read_text(encoding="utf-8"))
        expected_store = make_disabled_store(policy_id, source_id, text,
                                             url=url, source_sha256=source_hash)
        if store != expected_store:
            raise ValueError("document store differs from the extracted official source")
        if case in ACCEPTANCE:
            expected_scorecard = _scorecard(case, text, expected_store)
            if json.loads((package / "scorecard.json").read_text(encoding="utf-8")) != expected_scorecard:
                raise ValueError("scorecard differs from fixed reference and source")
        version = expected_store["documents"][0]["doc_version"]
        request = json.loads((package / "request.json").read_text(encoding="utf-8"))
        expected_request = prepare_request(expected_store, version)
        encoded = json.dumps(request.get("messages"), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        if request != expected_request or request.get("request_bytes") != len(encoded) \
                or request.get("request_sha256") != hashlib.sha256(encoded).hexdigest() \
                or manifest.get("request_bytes") != len(encoded) \
                or manifest.get("request_sha256") != hashlib.sha256(encoded).hexdigest():
            raise ValueError("saved request differs from the source, prompt or byte/hash count")
        metadata = json.loads((package / "source-metadata.json").read_text(encoding="utf-8"))
        if any((metadata.get("case") != case, metadata.get("source_url") != url,
                metadata.get("source_sha256") != source_hash,
                metadata.get("doc_version") != version,
                metadata.get("extracted_text_sha256") != hashlib.sha256(text.encode()).hexdigest())):
            raise ValueError("source metadata does not match the saved source")
        if metadata.get("role") != ("acceptance_design_seen" if case in ACCEPTANCE else "development_seen") \
                or metadata.get("reference_sha256") != (REFERENCE_SHA256 if case in ACCEPTANCE else None):
            raise ValueError("source metadata role or reference changed")
    except (OSError, json.JSONDecodeError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("package is incomplete or malformed") from exc
    return {"status": "verified", "case": case, "doc_version": version,
            "request_bytes": len(encoded), "request_sha256": request["request_sha256"],
            "package": str(package)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--case", choices=tuple(SOURCES))
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify:
        if args.output:
            parser.error("--output is only used with --case")
        result = verify_package(args.verify)
    else:
        if args.output is None:
            parser.error("--case requires --output")
        result = prepare(args.case, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
