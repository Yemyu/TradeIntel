"""Build a conservative HTS10-to-HS6_2017 history table.

The Census historical workbook provides validity intervals, while the annual
import concordances provide the official code universe and NAICS metadata. The
WCO Table II is used only for HS 2012 -> HS 2017 six-digit changes. Any
one-to-many or ``ex`` (partial-scope) relationship is retained as ambiguous
and is not forced into a single causal key.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree

import xlrd
from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_POLICY_DIR = PROJECT_ROOT / "data/raw/policy"
CAUSAL_DIR = PROJECT_ROOT / "data/processed/causal"
HISTORY_XLSX = RAW_POLICY_DIR / "census-import-historical-hs-numbers.xlsx"
WCO_TABLE_II = RAW_POLICY_DIR / "wco-hs2012-to-2017-table-ii.pdf"
MAPPING_CSV = CAUSAL_DIR / "hts_history_mapping.csv"
MAPPING_REPORT_JSON = CAUSAL_DIR / "mapping_report.json"
MAPPING_REPORT_MD = CAUSAL_DIR / "mapping_report.md"
MAPPING_SOURCE_MANIFEST = CAUSAL_DIR / "mapping_source_manifest.json"

WCO_URL = "https://www.wcoomd.org/-/media/wco/public/global/pdf/topics/nomenclature/instruments-and-tools/hs-nomenclature-2017/2016/table_ii_trp1217_en_rev1.pdf?db=web"
HISTORY_URL = "https://www.census.gov/foreign-trade/reference/codes/Import_Historical_HS_Numbers.xlsx"
CONCORDANCE_URL = "https://www.census.gov/foreign-trade/reference/codes/concordance/impconcord{yy:02d}.xls"

WCO_TOKEN_PATTERN = re.compile(r"(?i)(?:ex)?\d{4}\.\d{2}")
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

MAPPING_FIELDS = [
    "source_year",
    "source_hts10",
    "source_hs6",
    "hs6_2017",
    "mapping_status",
    "wco_candidate_hs6",
    "wco_partial_or_ex",
    "historical_validity_status",
    "historical_intervals",
    "naics6",
    "source_url",
    "source_sha256",
    "mapping_source_url",
    "mapping_source_sha256",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _shared_strings(zf: ZipFile) -> list[str]:
    root = ElementTree.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.iter(f"{{{MAIN_NS}}}t"))
        for item in root.findall(f"{{{MAIN_NS}}}si")
    ]


def read_historical_validity(path: Path = HISTORY_XLSX) -> dict[str, list[dict[str, str]]]:
    """Read Census's malformed-but-usable xlsx without rewriting its metadata."""

    with ZipFile(path) as zf:
        strings = _shared_strings(zf)
        root = ElementTree.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    intervals: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
        if row.attrib.get("r") == "1":
            continue
        values: dict[str, str] = {}
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            value = cell.find(f"{{{MAIN_NS}}}v")
            if value is None or value.text is None:
                text = ""
            elif cell.attrib.get("t") == "s":
                text = strings[int(value.text)]
            else:
                text = value.text
            values[cell.attrib["r"][0]] = text.strip()
        code = values.get("A", "")
        if len(code) != 10 or not code.isdigit():
            continue
        intervals[code].append(
            {"begin": values.get("D", ""), "end": values.get("E", "")}
        )
    return dict(intervals)


def read_annual_concordance(year: int) -> dict[str, dict[str, str]]:
    path = RAW_POLICY_DIR / f"census-import-concordance-{year}.xls"
    workbook = xlrd.open_workbook(path, on_demand=True)
    sheet = workbook.sheet_by_index(0)
    rows: dict[str, dict[str, str]] = {}
    for index in range(1, sheet.nrows):
        code = str(sheet.cell_value(index, 0)).strip()
        if len(code) != 10 or not code.isdigit():
            continue
        rows[code] = {
            "naics6": str(sheet.cell_value(index, 7)).strip(),
        }
    if not rows:
        raise ValueError(f"No import codes found in {path}")
    return rows


def read_wco_correlations(path: Path = WCO_TABLE_II) -> dict[str, list[dict[str, object]]]:
    """Parse the WCO two-column table while retaining partial markers."""

    correlations: dict[str, list[dict[str, object]]] = defaultdict(list)
    current_source: str | None = None
    reader = PdfReader(path)
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for line in text.splitlines():
            tokens = WCO_TOKEN_PATTERN.findall(line)
            if len(tokens) >= 2:
                source_token, target_token = tokens[0].lower(), tokens[1].lower()
                current_source = source_token.removeprefix("ex").replace(".", "")
                target = target_token.removeprefix("ex").replace(".", "")
                correlations[current_source].append(
                    {
                        "target": target,
                        "partial": target_token.startswith("ex"),
                        "page": page_number,
                    }
                )
            elif len(tokens) == 1 and current_source:
                target_token = tokens[0].lower()
                target = target_token.removeprefix("ex").replace(".", "")
                correlations[current_source].append(
                    {
                        "target": target,
                        "partial": target_token.startswith("ex"),
                        "page": page_number,
                    }
                )
    if len(correlations) != 291:
        raise ValueError(f"Unexpected WCO correlation source count: {len(correlations)}")
    return {source: values for source, values in correlations.items()}


def _period_value(value: str, *, begin: bool) -> tuple[int, int]:
    if value.lower().startswith("prior"):
        return (-10_000, 1)
    if value.lower() == "current":
        return (10_000, 12)
    match = re.fullmatch(r"(\d{2})/(\d{4})", value)
    if not match:
        return ((-10_000, 1) if begin else (10_000, 12))
    return int(match.group(2)), int(match.group(1))


def validity_for_year(intervals: list[dict[str, str]], year: int) -> tuple[str, str]:
    valid: list[str] = []
    for interval in intervals:
        begin = _period_value(interval["begin"], begin=True)
        end = _period_value(interval["end"], begin=False)
        if begin <= (year, 12) and end >= (year, 1):
            valid.append(f"{interval['begin']}→{interval['end']}")
    if valid:
        return "valid", "|".join(valid)
    if intervals:
        return "not_valid_in_year", "|".join(
            f"{item['begin']}→{item['end']}" for item in intervals
        )
    return "not_in_historical_file", ""


def _target_universe(concordance_2017: dict[str, dict[str, str]], wco: dict[str, list[dict[str, object]]]) -> set[str]:
    return {code[:6] for code in concordance_2017} | {
        str(item["target"]) for values in wco.values() for item in values
    }


def resolve_mapping(
    *,
    source_year: int,
    source_hs6: str,
    target_universe: set[str],
    wco: dict[str, list[dict[str, object]]],
) -> tuple[str, str, str, str]:
    candidates = wco.get(source_hs6, []) if source_year == 2016 else []
    if candidates:
        targets = sorted({str(item["target"]) for item in candidates})
        partial = any(bool(item["partial"]) for item in candidates)
        candidate_text = "|".join(targets)
        if len(targets) == 1 and not partial and targets[0] in target_universe:
            return targets[0], "wco_exact_single", candidate_text, "0"
        return "", "wco_partial_or_ambiguous", candidate_text, "1" if partial else "0"
    if source_hs6 in target_universe:
        return source_hs6, "same_hs6_prefix", "", "0"
    return "", "no_target_hs6", "", "0"


def build_mapping_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    if not HISTORY_XLSX.exists() or not WCO_TABLE_II.exists():
        raise FileNotFoundError("Official historical HS or WCO correlation source is missing")
    validity = read_historical_validity()
    concordances = {year: read_annual_concordance(year) for year in (2016, 2017, 2018, 2019)}
    wco = read_wco_correlations()
    target_universe = _target_universe(concordances[2017], wco)
    rows: list[dict[str, object]] = []
    status_counts: dict[str, int] = defaultdict(int)
    validity_counts: dict[str, int] = defaultdict(int)
    source_hashes = {
        "historical_xlsx": sha256_file(HISTORY_XLSX),
        "wco_table_ii": sha256_file(WCO_TABLE_II),
        **{
            f"concordance_{year}": sha256_file(
                RAW_POLICY_DIR / f"census-import-concordance-{year}.xls"
            )
            for year in (2016, 2017, 2018, 2019)
        },
    }
    for year, codes in concordances.items():
        for code, metadata in sorted(codes.items()):
            source_hs6 = code[:6]
            target, status, candidates, partial = resolve_mapping(
                source_year=year,
                source_hs6=source_hs6,
                target_universe=target_universe,
                wco=wco,
            )
            validity_status, intervals = validity_for_year(validity.get(code, []), year)
            status_counts[status] += 1
            validity_counts[validity_status] += 1
            rows.append(
                {
                    "source_year": year,
                    "source_hts10": code,
                    "source_hs6": source_hs6,
                    "hs6_2017": target,
                    "mapping_status": status,
                    "wco_candidate_hs6": candidates,
                    "wco_partial_or_ex": partial,
                    "historical_validity_status": validity_status,
                    "historical_intervals": intervals,
                    "naics6": metadata["naics6"],
                    "source_url": CONCORDANCE_URL.format(yy=year % 100),
                    "source_sha256": source_hashes[f"concordance_{year}"],
                    "mapping_source_url": WCO_URL if year == 2016 and source_hs6 in wco else HISTORY_URL,
                    "mapping_source_sha256": source_hashes["wco_table_ii"] if year == 2016 and source_hs6 in wco else source_hashes["historical_xlsx"],
                }
            )
    if len(rows) != len({(row["source_year"], row["source_hts10"]) for row in rows}):
        raise ValueError("HTS history mapping contains duplicate source keys")
    report = {
        "status": "mapping_built_with_conservative_ambiguity_flags",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "row_count": len(rows),
        "target_hs6_universe_count": len(target_universe),
        "mapping_status_counts": dict(sorted(status_counts.items())),
        "historical_validity_counts": dict(sorted(validity_counts.items())),
        "wco_correlation_source_count": len(wco),
        "rules": {
            "2016_to_2017": "Use WCO Table II only for changed HS6; any ex/one-to-many mapping remains blank and flagged.",
            "2017_to_2019": "Use the 2017 HS6 prefix as the canonical key; annual Census concordances validate code presence and NAICS.",
            "no_fuzzy_names": True,
            "policy_post_results_used": False,
        },
        "source_hashes": source_hashes,
    }
    return rows, report


def write_outputs(rows: list[dict[str, object]], report: dict[str, object]) -> None:
    CAUSAL_DIR.mkdir(parents=True, exist_ok=True)
    temporary = MAPPING_CSV.with_suffix(".csv.part")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MAPPING_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(MAPPING_CSV)
    with MAPPING_REPORT_JSON.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    MAPPING_REPORT_MD.write_text(
        f"""# HTS10 → HS6_2017 映射报告

状态：`{report['status']}`

本次生成 {report['row_count']:,} 条年度 HTS10 映射记录。2016 年跨 HS 版本变化使用 WCO Table II；WCO 标有 `ex` 或一对多关系的记录保留候选代码但不强行填入单个 `HS6_2017`。2017–2019 年使用 2017 HS6 前缀，并由 Census 年度 concordance 验证代码和 NAICS。

映射状态计数：

```text
{json.dumps(report['mapping_status_counts'], ensure_ascii=False, indent=2)}
```

历史有效性计数：

```text
{json.dumps(report['historical_validity_counts'], ensure_ascii=False, indent=2)}
```

这张表只是商品代码层输入，不代表控制组已经通过金额覆盖、匹配平衡和政策前趋势门槛。完整候选面板仍需读取所有原始月份贸易数据，并在 Sol 审查后才可生成。
""",
        encoding="utf-8",
    )
    with MAPPING_SOURCE_MANIFEST.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "generated_at_utc": report["generated_at_utc"],
                "status": report["status"],
                "sources": [
                    {"name": "Census historical HS numbers", "url": HISTORY_URL, "sha256": report["source_hashes"]["historical_xlsx"], "local_path": str(HISTORY_XLSX.relative_to(PROJECT_ROOT))},
                    {"name": "WCO HS 2012 to HS 2017 Table II", "url": WCO_URL, "sha256": report["source_hashes"]["wco_table_ii"], "local_path": str(WCO_TABLE_II.relative_to(PROJECT_ROOT))},
                    *[
                        {"name": f"Census {year} import concordance", "url": CONCORDANCE_URL.format(yy=year % 100), "sha256": report["source_hashes"][f"concordance_{year}"], "local_path": str((RAW_POLICY_DIR / f"census-import-concordance-{year}.xls").relative_to(PROJECT_ROOT))}
                        for year in (2016, 2017, 2018, 2019)
                    ],
                ],
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")


def main() -> None:
    rows, report = build_mapping_rows()
    write_outputs(rows, report)
    print(f"Built {report['row_count']:,} HTS10 history mapping rows")
    print(json.dumps(report["mapping_status_counts"], ensure_ascii=False))
    print(f"Wrote {MAPPING_CSV.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {MAPPING_REPORT_JSON.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {MAPPING_REPORT_MD.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
