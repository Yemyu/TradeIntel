"""Build official policy-exposure evidence and record causal-panel status.

Policy notices and cross-year HTS10 -> HS6 mapping are built by separate
programs, but this script keeps their shared status report consistent.  A
completed mapping is still not a completed causal panel: the full all-origin
monthly trade panel, contamination gates, matching, and pre-trend checks must
come afterwards.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_POLICY_DIR = PROJECT_ROOT / "data/raw/policy"
CAUSAL_DIR = PROJECT_ROOT / "data/processed/causal"
LIST1_PRODUCTS = PROJECT_ROOT / "data/processed/policy/section301_list1_products.csv"
LIST2_NOTICE = RAW_POLICY_DIR / "ustr-section301-list1-amendment-2018-08-16.pdf"
LIST3_NOTICE = RAW_POLICY_DIR / "ustr-section301-list3-2018-09-21.pdf"
EXPOSURE_CSV = CAUSAL_DIR / "trade_action_exposure.csv"
EXCLUSION_CSV = CAUSAL_DIR / "list1_exclusion_timeline.csv"
SOURCE_MANIFEST = CAUSAL_DIR / "source_manifest.json"
SOURCE_REPORT = CAUSAL_DIR / "source_access_report.md"
CONTROL_REPORT_JSON = CAUSAL_DIR / "control_build_report.json"
CONTROL_REPORT_MD = CAUSAL_DIR / "control_build_report.md"
MAPPING_CSV = CAUSAL_DIR / "hts_history_mapping.csv"
MAPPING_REPORT_JSON = CAUSAL_DIR / "mapping_report.json"
PANEL_REPORT_JSON = CAUSAL_DIR / "causal_trade_panel_report.json"
PANEL_MANIFEST_JSON = CAUSAL_DIR / "causal_trade_panel_manifest.json"

CODE8_PATTERN = re.compile(r"(?<!\d)(\d{4}\.\d{2}\.\s*\d{2})(?!\d)")
CODE10_PATTERN = re.compile(r"(?<!\d)(\d{4}\.\d{2}\.\d{4})(?!\d)")
EXCLUDED_HEADINGS = {"9802", "9903"}

DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_TIMEOUT_SECONDS = 60
USER_AGENT = "TradeShockAI/0.1 (policy evidence build)"


POLICY_SOURCE_SPECS: tuple[dict[str, str], ...] = (
    {
        "source_id": "list1_initial",
        "url": "https://ustr.gov/sites/default/files/2018-13248.pdf",
        "filename": "ustr-section301-list1-2018.pdf",
        "expected_sha256": "3e27dfb420dc308a079e7a71f2715fa29ed00fbbd84dbec4514f2cd66b9cf301",
    },
    {
        "source_id": "list2_notice",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/2018-17709.pdf",
        "filename": "ustr-section301-list1-amendment-2018-08-16.pdf",
        "expected_sha256": "97a1883d0617b038e4b5bd2f6e36400168fcc27d67fe6562149cc85866c08729",
    },
    {
        "source_id": "list3_notice",
        "url": "https://www.govinfo.gov/content/pkg/FR-2018-09-21/pdf/FR-2018-09-21.pdf",
        "filename": "ustr-section301-list3-2018-09-21.pdf",
        "fallback": "tmp/FR-2018-09-21.pdf",
    },
    {
        "source_id": "section232_aluminum_proclamation",
        "url": "https://www.govinfo.gov/content/pkg/FR-2018-03-15/pdf/2018-05477.pdf",
        "filename": "section232-aluminum-proclamation-9704.pdf",
        "fallback": "tmp/FR-2018-03-15-9704.pdf",
    },
    {
        "source_id": "section232_steel_proclamation",
        "url": "https://www.govinfo.gov/content/pkg/FR-2018-03-15/pdf/2018-05478.pdf",
        "filename": "section232-steel-proclamation-9705.pdf",
        "fallback": "tmp/FR-2018-03-15-9705.pdf",
    },
    {
        "source_id": "section201_solar_proclamation",
        "url": "https://www.govinfo.gov/content/pkg/DCPD-201800044/pdf/DCPD-201800044.pdf",
        "filename": "section201-solar-proclamation-9693.pdf",
        "fallback": "tmp/DCPD-201800044.pdf",
    },
    {
        "source_id": "section201_washers_proclamation",
        "url": "https://www.govinfo.gov/content/pkg/DCPD-201800045/pdf/DCPD-201800045.pdf",
        "filename": "section201-washers-proclamation-9694.pdf",
        "fallback": "tmp/DCPD-201800045.pdf",
    },
    {
        "source_id": "section232_steel_dcpd",
        "url": "https://www.govinfo.gov/content/pkg/DCPD-201800148/pdf/DCPD-201800148.pdf",
        "filename": "section232-steel-dcpd-9705.pdf",
        "fallback": "tmp/DCPD-201800148.pdf",
    },
)


EXCLUSION_SPECS: tuple[dict[str, str], ...] = (
    {
        "batch_id": "list1_exclusion_2018_12_28",
        "notice_date": "2018-12-28",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/2018-28277.pdf",
        "filename": "ustr-list1-exclusions-2018-12-28.pdf",
    },
    {
        "batch_id": "list1_exclusion_2019_03_25",
        "notice_date": "2019-03-25",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/84_FR_11152.pdf",
        "filename": "ustr-list1-exclusions-2019-03-25.pdf",
    },
    {
        "batch_id": "list1_exclusion_2019_04_18",
        "notice_date": "2019-04-18",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/84_FR_16310.pdf",
        "filename": "ustr-list1-exclusions-2019-04-18.pdf",
    },
    {
        "batch_id": "list1_exclusion_2019_05_14",
        "notice_date": "2019-05-14",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/84_FR_21389.pdf",
        "filename": "ustr-list1-exclusions-2019-05-14.pdf",
    },
    {
        "batch_id": "list1_exclusion_2019_06_04",
        "notice_date": "2019-06-04",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/84_FR_25895.pdf",
        "filename": "ustr-list1-exclusions-2019-06-04.pdf",
    },
    {
        "batch_id": "list1_exclusion_2019_07_09",
        "notice_date": "2019-07-09",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/Notice_of_Product_Exclusions.pdf",
        "filename": "ustr-list1-exclusions-2019-07-09.pdf",
    },
    {
        "batch_id": "list1_exclusion_2019_09_20",
        "notice_date": "2019-09-20",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/%2434_Billion_Exclusions_Granted_September.pdf",
        "filename": "ustr-list1-exclusions-2019-09-20.pdf",
    },
    {
        "batch_id": "list1_exclusion_2019_10_02",
        "notice_date": "2019-10-02",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/%2434_Billion_Exclusions_Granted_October_2019.pdf",
        "filename": "ustr-list1-exclusions-2019-10-02.pdf",
    },
    {
        "batch_id": "list1_exclusion_2019_12_17",
        "notice_date": "2019-12-17",
        "url": "https://ustr.gov/sites/default/files/enforcement/301Investigations/%2434_Billion_Notice_of_Product_Exclusion_and_Amendments.pdf",
        "filename": "ustr-list1-exclusions-2019-12-17.pdf",
    },
)


EXPOSURE_FIELDS = [
    "exposure_id",
    "policy_id",
    "policy_name",
    "target_origin",
    "coverage_level",
    "hts_code",
    "effective_date",
    "announcement_date",
    "additional_rate",
    "source_url",
    "source_page",
    "scope_status",
    "notes",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_code(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def download_source(spec: dict[str, str], *, raw_dir: Path = RAW_POLICY_DIR) -> dict[str, object]:
    """Download an official source, using a local temporary fallback if needed."""

    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / spec["filename"]
    expected = spec.get("expected_sha256")
    if destination.exists():
        actual = sha256_file(destination)
        if expected and actual != expected:
            raise ValueError(
                f"Existing checksum mismatch for {spec['source_id']}: {actual}"
            )
        return {
            **spec,
            "local_path": str(destination.relative_to(PROJECT_ROOT)),
            "sha256": actual,
            "bytes": destination.stat().st_size,
            "status": "already_present_verified",
        }

    temporary = destination.with_suffix(destination.suffix + ".part")
    errors: list[str] = []
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        temporary.unlink(missing_ok=True)
        try:
            request = Request(spec["url"], headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, temporary.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
            if temporary.stat().st_size == 0:
                raise OSError("empty response")
            temporary.replace(destination)
            actual = sha256_file(destination)
            if expected and actual != expected:
                destination.unlink(missing_ok=True)
                raise ValueError(f"checksum mismatch: {actual}")
            return {
                **spec,
                "local_path": str(destination.relative_to(PROJECT_ROOT)),
                "sha256": actual,
                "bytes": destination.stat().st_size,
                "status": "downloaded_and_verified",
                "attempts": attempt,
            }
        except (HTTPError, URLError, OSError, ValueError) as exc:
            errors.append(f"attempt {attempt}: {exc}")
            temporary.unlink(missing_ok=True)
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(1)

    fallback = spec.get("fallback")
    fallback_path = PROJECT_ROOT / fallback if fallback else None
    if fallback_path and fallback_path.exists():
        shutil.copyfile(fallback_path, destination)
        actual = sha256_file(destination)
        if expected and actual != expected:
            destination.unlink(missing_ok=True)
            raise ValueError(
                f"Fallback checksum mismatch for {spec['source_id']}: {actual}"
            )
        return {
            **spec,
            "local_path": str(destination.relative_to(PROJECT_ROOT)),
            "sha256": actual,
            "bytes": destination.stat().st_size,
            "status": "local_fallback_from_tmp",
            "download_errors": errors,
        }

    return {
        **spec,
        "local_path": "",
        "sha256": "",
        "bytes": 0,
        "status": "unavailable",
        "download_errors": errors,
    }


def extract_code_rows(
    pdf_path: Path,
    *,
    pages: list[int] | None = None,
    pattern: re.Pattern[str] = CODE8_PATTERN,
) -> dict[str, list[int]]:
    """Return normalized code -> one-based PDF pages, excluding tariff headings."""

    reader = PdfReader(pdf_path)
    page_numbers = pages or list(range(1, len(reader.pages) + 1))
    code_pages: dict[str, set[int]] = {}
    for page_number in page_numbers:
        text = reader.pages[page_number - 1].extract_text() or ""
        for match in pattern.finditer(text):
            code = normalize_code(match.group(1))
            if code[:4] in EXCLUDED_HEADINGS:
                continue
            code_pages.setdefault(code, set()).add(page_number)
    return {code: sorted(pages) for code, pages in sorted(code_pages.items())}


def extract_list2_codes(pdf_path: Path = LIST2_NOTICE) -> dict[str, list[int]]:
    codes = extract_code_rows(pdf_path, pages=[4, 5])
    if len(codes) != 279:
        raise ValueError(f"List 2 expected 279 codes, found {len(codes)}")
    return codes


def _page_offsets(texts: list[str]) -> list[tuple[int, int, int]]:
    offsets: list[tuple[int, int, int]] = []
    cursor = 0
    for page_number, text in enumerate(texts, start=1):
        end = cursor + len(text)
        offsets.append((cursor, end, page_number))
        cursor = end + 1
    return offsets


def _pages_for_span(offsets: list[tuple[int, int, int]], start: int, end: int) -> list[int]:
    return [page for left, right, page in offsets if start < right and end > left]


def extract_list3_codes(pdf_path: Path = LIST3_NOTICE) -> dict[str, list[int]]:
    """Extract both List 3 Annex A's 5,734 codes and the 11 special codes."""

    reader = PdfReader(pdf_path)
    texts = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(texts)
    offsets = _page_offsets(texts)
    first_start = text.find("following 8-digit")
    first_end = text.find("4. by inserting", first_start)
    second_start = text.find("following products of China", first_end)
    second_end = text.find("ANNEX B", second_start)
    if min(first_start, first_end, second_start, second_end) < 0:
        raise ValueError("List 3 code-block markers were not found")

    blocks = ((first_start, first_end), (second_start, second_end))
    code_pages: dict[str, set[int]] = {}
    block_counts: list[int] = []
    for start, end in blocks:
        found: set[str] = set()
        for match in CODE8_PATTERN.finditer(text, start, end):
            code = normalize_code(match.group(1))
            if code[:4] in EXCLUDED_HEADINGS:
                continue
            found.add(code)
            code_pages.setdefault(code, set()).update(
                _pages_for_span(offsets, match.start(), match.end())
            )
        block_counts.append(len(found))

    if block_counts != [5734, 11] or len(code_pages) != 5745:
        raise ValueError(
            f"List 3 expected blocks [5734, 11] and union 5745, found {block_counts} and {len(code_pages)}"
        )
    return {code: sorted(pages) for code, pages in sorted(code_pages.items())}


def _list1_codes() -> dict[str, list[int]]:
    with LIST1_PRODUCTS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    codes: dict[str, list[int]] = {}
    for row in rows:
        code = normalize_code(row["canonical_hts8"])
        codes.setdefault(code, []).append(int(row["source_page"]))
    if len(codes) != 818:
        raise ValueError(f"List 1 expected 818 codes, found {len(codes)}")
    return {code: sorted(set(pages)) for code, pages in sorted(codes.items())}


def _exposure_row(
    *,
    exposure_id: str,
    policy_id: str,
    policy_name: str,
    code: str,
    effective_date: str,
    announcement_date: str,
    additional_rate: str,
    source_url: str,
    source_page: str | int,
    scope_status: str = "official_code",
    notes: str = "",
    target_origin: str = "China",
    coverage_level: str = "HTS8",
) -> dict[str, object]:
    return {
        "exposure_id": exposure_id,
        "policy_id": policy_id,
        "policy_name": policy_name,
        "target_origin": target_origin,
        "coverage_level": coverage_level,
        "hts_code": code,
        "effective_date": effective_date,
        "announcement_date": announcement_date,
        "additional_rate": additional_rate,
        "source_url": source_url,
        "source_page": source_page,
        "scope_status": scope_status,
        "notes": notes,
    }


def build_exposure_rows(
    *,
    list1_codes: dict[str, list[int]],
    list2_codes: dict[str, list[int]],
    list3_codes: dict[str, list[int]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for code, pages in list1_codes.items():
        rows.append(
            _exposure_row(
                exposure_id=f"us_301_list1_2018:{code}",
                policy_id="us_301_list1_2018",
                policy_name="Section 301 List 1",
                code=code,
                effective_date="2018-07-06",
                announcement_date="2018-06-15",
                additional_rate="0.25",
                source_url="https://ustr.gov/sites/default/files/2018-13248.pdf",
                source_page="|".join(str(page) for page in pages),
            )
        )
    for code, pages in list2_codes.items():
        rows.append(
            _exposure_row(
                exposure_id=f"us_301_list2_2018:{code}",
                policy_id="us_301_list2_2018",
                policy_name="Section 301 List 2",
                code=code,
                effective_date="2018-08-23",
                announcement_date="2018-08-16",
                additional_rate="0.25",
                source_url="https://ustr.gov/sites/default/files/enforcement/301Investigations/2018-17709.pdf",
                source_page="|".join(str(page) for page in pages),
            )
        )
    for code, pages in list3_codes.items():
        rows.append(
            _exposure_row(
                exposure_id=f"us_301_list3_2018:{code}",
                policy_id="us_301_list3_2018",
                policy_name="Section 301 List 3",
                code=code,
                effective_date="2018-09-24",
                announcement_date="2018-09-21",
                additional_rate="0.10",
                source_url="https://www.govinfo.gov/content/pkg/FR-2018-09-21/pdf/FR-2018-09-21.pdf",
                source_page="|".join(str(page) for page in pages),
                notes="Annex B raises the rate to 0.25 on 2019-01-01; this row records initial List 3 exposure.",
            )
        )

    # These are official scope rules, not a claim that they have already been
    # expanded to every 2018 HTS10 or 2017 HS6 code.
    rule_rows = [
        ("us_232_steel_2018", "Section 232 steel", "7206.10–7216.50", "heading_range", "2018-03-23", "2018-03-08", "0.25", "https://www.govinfo.gov/content/pkg/FR-2018-03-15/pdf/2018-05478.pdf", "Official proclamation scope: 7206.10 through 7216.50; 7216.99 through 7301.10; 7302.10; 7302.40 through 7302.90; 7304.10 through 7306.90.") ,
        ("us_232_steel_2018", "Section 232 steel", "7216.99–7301.10", "heading_range", "2018-03-23", "2018-03-08", "0.25", "https://www.govinfo.gov/content/pkg/FR-2018-03-15/pdf/2018-05478.pdf", "Official proclamation scope; expand only after validating the 2018 HTS history.") ,
        ("us_232_steel_2018", "Section 232 steel", "7302.10", "HTS6_heading", "2018-03-23", "2018-03-08", "0.25", "https://www.govinfo.gov/content/pkg/FR-2018-03-15/pdf/2018-05478.pdf", "Official proclamation scope; exact statistical subheadings require history validation.") ,
        ("us_232_steel_2018", "Section 232 steel", "7302.40–7302.90", "heading_range", "2018-03-23", "2018-03-08", "0.25", "https://www.govinfo.gov/content/pkg/FR-2018-03-15/pdf/2018-05478.pdf", "Official proclamation scope; expand only after validating the 2018 HTS history.") ,
        ("us_232_steel_2018", "Section 232 steel", "7304.10–7306.90", "heading_range", "2018-03-23", "2018-03-08", "0.25", "https://www.govinfo.gov/content/pkg/FR-2018-03-15/pdf/2018-05478.pdf", "Official proclamation scope; expand only after validating the 2018 HTS history.") ,
        ("us_232_aluminum_2018", "Section 232 aluminum", "7601;7604;7605;7606;7607;7608;7609;7616.99.51.60;7616.99.51.70", "official_scope_rule", "2018-03-23", "2018-03-08", "0.10", "https://www.govinfo.gov/content/pkg/FR-2018-03-15/pdf/2018-05477.pdf", "Official proclamation categories; not yet expanded to a complete HTS10/HS6 list.") ,
        ("us_201_solar_2018", "Section 201 solar", "8541.40.60;8501.31.80;8501.61.00;8507.20.80", "HTS8_set", "2018-02-07", "2018-01-23", "0.30", "https://www.govinfo.gov/content/pkg/DCPD-201800044/pdf/DCPD-201800044.pdf", "Official proclamation code references; scope and exclusions require HTS history review.") ,
        ("us_201_washers_2018", "Section 201 washers", "8450.11.00;8450.20.00;8450.90.20;8450.90.60", "HTS8_set", "2018-02-07", "2018-01-23", "0.20", "https://www.govinfo.gov/content/pkg/DCPD-201800045/pdf/DCPD-201800045.pdf", "Official proclamation code references; scope and exclusions require HTS history review.") ,
    ]
    for index, (policy_id, name, code, level, effective, announced, rate, url, note) in enumerate(rule_rows, start=1):
        rows.append(
            _exposure_row(
                exposure_id=f"{policy_id}:rule:{index:03d}",
                policy_id=policy_id,
                policy_name=name,
                code=code,
                coverage_level=level,
                effective_date=effective,
                announcement_date=announced,
                additional_rate=rate,
                source_url=url,
                source_page="",
                scope_status="official_scope_rule_requires_hts_history_expansion",
                notes=note,
            )
        )
    return rows


def extract_exclusion_record(spec: dict[str, str], source_record: dict[str, object]) -> dict[str, object]:
    path_text = source_record.get("local_path", "")
    path = PROJECT_ROOT / str(path_text) if path_text else None
    explicit_codes: list[str] = []
    descriptions_count: int | str = "unknown"
    notes = "Product descriptions are retained in the official notice but not automatically converted into HTS10 scope."
    if path and path.exists():
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        explicit_codes = sorted(set(CODE10_PATTERN.findall(text)))
        count_match = re.search(r"(\d+)\s+(?:10-digit|ten-digit).*?(?:and|,)\s*(\d+)\s+(?:specially prepared|product) descriptions", text, re.I | re.S)
        if count_match:
            descriptions_count = int(count_match.group(2))
        elif "product descriptions" in text.lower() or "descriptions of products" in text.lower():
            descriptions_count = "present_unparsed"
        if explicit_codes:
            notes = "Explicit 10-digit codes are listed; any narrative product descriptions remain unparsed for conservative matching."
    return {
        "batch_id": spec["batch_id"],
        "notice_date": spec["notice_date"],
        "effective_date": "2018-07-06",
        "source_url": spec["url"],
        "local_path": path_text,
        "source_sha256": source_record.get("sha256", ""),
        "explicit_hts10_count": len(explicit_codes),
        "explicit_hts10_codes": "|".join(explicit_codes),
        "descriptive_scope_count": descriptions_count,
        "scope_status": "explicit_codes_plus_descriptions_unparsed" if descriptions_count != "unknown" else "explicit_codes_or_scope_needs_review",
        "notes": notes,
        "download_status": source_record.get("status", "unavailable"),
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _load_mapping_report() -> dict[str, object] | None:
    """Return the verified mapping summary when the mapping stage exists."""

    if not MAPPING_CSV.exists() or not MAPPING_REPORT_JSON.exists():
        return None
    try:
        with MAPPING_REPORT_JSON.open(encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if report.get("status") != "mapping_built_with_conservative_ambiguity_flags":
        return None
    return report


def _load_trade_panel_report() -> dict[str, object] | None:
    """Return the all-origin panel summary only when its full frozen scope exists."""

    if not PANEL_REPORT_JSON.exists() or not PANEL_MANIFEST_JSON.exists():
        return None
    try:
        with PANEL_REPORT_JSON.open(encoding="utf-8") as handle:
            report = json.load(handle)
        with PANEL_MANIFEST_JSON.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None

    scope = report.get("source_scope", {})
    outputs = report.get("outputs", {})
    months = manifest.get("months", [])
    if (
        report.get("status") != "all_origin_hs6_panel_built"
        or manifest.get("status") != "all_origin_hs6_panel_built"
        or scope.get("start") != "2016-01"
        or scope.get("end") != "2019-12"
        or scope.get("month_count") != 48
        or scope.get("all_origins_read") is not True
        or len(months) != 48
        or not isinstance(outputs.get("combined_rows"), int)
        or outputs["combined_rows"] <= 0
    ):
        return None
    return report


def write_source_report(
    manifest: dict[str, object],
    mapping_report: dict[str, object] | None = None,
    panel_report: dict[str, object] | None = None,
) -> None:
    available = sum(1 for row in manifest["policy_sources"] + manifest["exclusion_sources"] if row["status"] != "unavailable")
    total = len(manifest["policy_sources"]) + len(manifest["exclusion_sources"])
    panel_summary = "本次运行未发现完整的 all-origin 贸易面板，因此控制组仍缺少未处理候选。"
    next_stage = "下一阶段先重建 all-origin 贸易面板，再由 Sol 高审查控制组资格和事件研究门槛。"
    if panel_report is not None:
        scope = panel_report["source_scope"]
        coverage = panel_report["coverage"]
        rows = panel_report["outputs"]["combined_rows"]
        panel_summary = (
            "已完成所有原产国的官方月度贸易面板："
            f"{scope['start']} 至 {scope['end']}，共 {scope['month_count']} 个月、"
            f"{rows:,} 条 HS6×月份记录。全来源金额映射覆盖率为 "
            f"{coverage['all_origin_mapping_coverage']:.2%}，中国金额映射覆盖率为 "
            f"{coverage['china_mapping_coverage']:.2%}。这些是全样本的来源/映射覆盖率，"
            "不是处理组政策前覆盖率门槛的通过结论。"
        )
        next_stage = (
            "下一阶段由 Sol 高审查处理组政策前金额覆盖、污染排除、匹配平衡和前趋势；"
            "这些门槛通过前仍不运行事件研究。"
        )

    content = f"""# 官方政策来源取得报告

生成时间（UTC）：{manifest['generated_at_utc']}

## 已取得的来源

本阶段取得或核验了 {available}/{total} 个 USTR/GovInfo 官方政策文件。每份文件的 URL、SHA-256、取得状态和本地临时路径都记录在 `source_manifest.json`；`data/raw/policy/` 按仓库规则被 Git 忽略，不把大 PDF 提交到仓库。

解析结果：

- Section 301 List 1：818 个已核验 HTS8（复用上一阶段的官方修正结果）；
- Section 301 List 2：279 个 HTS8；生效日 2018-08-23；
- Section 301 List 3：5,745 个 HTS8（5,734 个主代码 + 11 个特殊代码）；生效日 2018-09-24；
- Section 232/201：保留官方范围规则或官方代码集合，但标记为需要 HTS 历史展开，不能直接当作完整 HS6 暴露表；
- List 1 排除：保存 2018-12 至 2019-12 的官方批次时间线；排除追溯生效日记录为 2018-07-06，文字描述没有擅自转换成“整条 HTS8 未处理”。

## 已完成的跨年代码映射

{("Census 历史 HS 文件、2016–2019 年度 concordance 和 WCO HS 2012→2017 Table II 已通过官方参考页取得并核验。映射表包含 " + f"{mapping_report['row_count']:,}" + " 条年度 HTS10 记录；其中歧义或 `ex` 部分映射保留候选代码但不强行填入统一 HS6。详细来源和哈希见 `mapping_source_manifest.json` 与 `mapping_report.json`。" if mapping_report else "本次运行未发现已核验的跨年映射，因此仍需先取得 Census 官方历史文件。")}

## 尚未完成的边界

{panel_summary}

{(next_stage if mapping_report else "下一阶段需要在 Sol 高模型审查下选择可复核的 Census 官方支持入口，完成跨年映射后再进入候选控制组。")}
"""
    SOURCE_REPORT.write_text(content, encoding="utf-8")


def write_control_report(
    manifest: dict[str, object],
    mapping_report: dict[str, object] | None = None,
    panel_report: dict[str, object] | None = None,
) -> None:
    """Record the next hard gate rather than creating a partial causal panel."""

    mapping_ready = mapping_report is not None
    counts = dict(manifest["counts"])
    blocked_outputs = [
        "control_candidate_features.csv",
        "matched_control_pairs.csv",
        "causal_candidate_panel.csv",
    ]
    completed_outputs = [
        "trade_action_exposure.csv",
        "list1_exclusion_timeline.csv",
        "source_manifest.json",
        "source_access_report.md",
    ]
    if mapping_ready and panel_report is not None:
        scope = panel_report["source_scope"]
        coverage = panel_report["coverage"]
        outputs = panel_report["outputs"]
        counts.update(
            {
                "mapping_rows": mapping_report["row_count"],
                "mapping_ambiguous_rows": mapping_report["mapping_status_counts"].get(
                    "wco_partial_or_ambiguous", 0
                ),
                "all_origin_trade_months": scope["month_count"],
                "all_origin_hs6_month_rows": outputs["combined_rows"],
                "all_origin_mapping_coverage": coverage["all_origin_mapping_coverage"],
                "china_mapping_coverage": coverage["china_mapping_coverage"],
            }
        )
        completed_outputs.extend(
            [
                "hts_history_mapping.csv",
                "mapping_report.json",
                "mapping_source_manifest.json",
                "causal_trade_panel_manifest.json",
                "causal_trade_panel_report.json",
            ]
        )
        report = {
            "status": "all_origin_panel_built_controls_pending",
            "stage": "phase_06_all_origin_panel_execution",
            "policy_exposure_status": "complete_for_official_notice_scope",
            "mapping_status": mapping_report["status"],
            "trade_panel_status": panel_report["status"],
            "blocked_outputs": blocked_outputs,
            "completed_outputs": completed_outputs,
            "counts": counts,
            "reason": "The full all-origin HS6 panel is built and source-hashed, but it is not a matched control group. Treated pre-policy coverage, contamination exclusions, pre-policy matching, balance, and pre-trend gates remain unevaluated.",
            "adoption_rule": "Do not run or publish the causal event study until contamination, matching, and pre-trend gates pass.",
        }
        markdown = f"""# 控制组构建报告：贸易面板已完成，等待资格审查

> 状态：`all_origin_panel_built_controls_pending`

官方政策暴露表、List 1 排除时间线、跨年 HTS10 → `HS6_2017` 映射，以及 all-origin 贸易面板已经完成。面板覆盖 {scope['start']} 至 {scope['end']} 的 {scope['month_count']} 个月，共 {outputs['combined_rows']:,} 条 HS6×月份记录；全来源金额映射覆盖率为 {coverage['all_origin_mapping_coverage']:.2%}，中国金额映射覆盖率为 {coverage['china_mapping_coverage']:.2%}。

这不等于“已经有了控制组”，更不等于“已经得到关税效应”。覆盖率是全样本汇总值；冻结协议要求对 **处理组、政策前期间** 单独核验金额覆盖和 HTS10 覆盖。随后还必须排除 List 2/3、Section 232/201 等污染商品，只用政策前特征匹配，检查平衡和前趋势。

因此暂不生成 `control_candidate_features.csv`、`matched_control_pairs.csv` 或 `causal_candidate_panel.csv`，也不运行事件研究。

机器可读详情见 `control_build_report.json`；面板来源和逐月哈希见 `causal_trade_panel_manifest.json`。
"""
    elif mapping_ready:
        counts.update(
            {
                "mapping_rows": mapping_report["row_count"],
                "mapping_ambiguous_rows": mapping_report["mapping_status_counts"].get(
                    "wco_partial_or_ambiguous", 0
                ),
            }
        )
        completed_outputs.extend(
            ["hts_history_mapping.csv", "mapping_report.json", "mapping_source_manifest.json"]
        )
        report = {
            "status": "mapping_built_trade_panel_pending",
            "stage": "phase_06_hs_mapping_execution",
            "policy_exposure_status": "complete_for_official_notice_scope",
            "mapping_status": mapping_report["status"],
            "blocked_outputs": blocked_outputs,
            "completed_outputs": completed_outputs,
            "counts": counts,
            "reason": "Official Census history/concordance and WCO crosswalk are mapped conservatively. The remaining source boundary is the full all-origin 48-month trade panel; the existing List 1-only panel cannot be used as the control group.",
            "adoption_rule": "Do not run or publish the causal event study until contamination, matching, and pre-trend gates pass.",
        }
        markdown = """# 控制组构建报告：等待完整贸易面板

> 状态：`mapping_built_trade_panel_pending`

官方政策暴露表、List 1 排除时间线和跨年 HTS10 → `HS6_2017` 映射已经完成。映射对 WCO `ex`、一对多和歧义关系保留标记，不强行猜测。

下一道硬门槛是重建所有原产国的 48 个月贸易面板。当前面板是 List 1-only，只能支撑已完成的描述性分析，不能直接充当控制组。面板完成后还必须通过金额覆盖、污染排除、匹配平衡和政策前趋势检查，才允许运行事件研究。

机器可读详情见 `control_build_report.json`；映射来源见 `mapping_source_manifest.json`。
"""
    else:
        report = {
            "status": "blocked_source_access",
            "stage": "phase_06_policy_contamination_execution",
            "policy_exposure_status": "complete_for_official_notice_scope",
            "mapping_status": "blocked_source_access",
            "blocked_outputs": ["hts_history_mapping.csv", *blocked_outputs],
            "completed_outputs": completed_outputs,
            "counts": counts,
            "reason": "Census historical HS/concordance official static endpoints returned HTTP 403; a third-party mirror was not substituted.",
            "adoption_rule": "Do not run or publish the causal event study until the frozen mapping, contamination, matching, and pre-trend gates pass.",
        }
        markdown = """# 控制组构建报告：当前阻断

> 状态：`blocked_source_access`

政策清单和排除时间线已经从官方 USTR/GovInfo 文件取得并通过代码数量核验。跨年 HTS10 → `HS6_2017` 映射仍被 Census 官方静态入口的 HTTP 403 阻断，因此没有生成空的或猜测出来的控制组。

暂时不能进入事件研究。必须先取得可复核的官方历史 HS/concordance，完成覆盖率、歧义率、纯处理/纯对照数量、匹配平衡和政策前趋势检查。

机器可读详情见 `control_build_report.json`；来源详情见 `source_manifest.json` 和 `source_access_report.md`。
"""
    with CONTROL_REPORT_JSON.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    CONTROL_REPORT_MD.write_text(markdown, encoding="utf-8")


def build_outputs() -> dict[str, object]:
    CAUSAL_DIR.mkdir(parents=True, exist_ok=True)
    policy_records = [download_source(spec) for spec in POLICY_SOURCE_SPECS]
    exclusion_records = [download_source(spec) for spec in EXCLUSION_SPECS]
    list1_codes = _list1_codes()
    list2_codes = extract_list2_codes()
    if not LIST3_NOTICE.exists():
        raise FileNotFoundError(f"Missing List 3 source: {LIST3_NOTICE}")
    list3_codes = extract_list3_codes()

    exposure_rows = build_exposure_rows(
        list1_codes=list1_codes,
        list2_codes=list2_codes,
        list3_codes=list3_codes,
    )
    write_csv(EXPOSURE_CSV, EXPOSURE_FIELDS, exposure_rows)

    exclusion_rows = [
        extract_exclusion_record(spec, record)
        for spec, record in zip(EXCLUSION_SPECS, exclusion_records)
    ]
    write_csv(EXCLUSION_CSV, list(exclusion_rows[0]), exclusion_rows)

    mapping_report = _load_mapping_report()
    panel_report = _load_trade_panel_report()
    census_mapping = {
        "status": "blocked_source_access",
        "probe_date": "2026-08-31",
        "official_reference_url": "https://www.census.gov/foreign-trade/reference/index.html",
        "concordance_reference_url": "https://www.census.gov/foreign-trade/data/dataproducts/concordance",
        "observed_issue": "Official static historical files returned HTTP 403 to controlled requests; no third-party mirror used.",
    }
    manifest_status = "policy_exposure_built_mapping_blocked_source_access"
    if mapping_report is not None:
        manifest_status = "policy_exposure_and_hs_mapping_built_trade_panel_pending"
        census_mapping = {
            "status": "official_history_and_concordance_retrieved",
            "probe_date": "2026-08-31",
            "official_reference_url": "https://www.census.gov/foreign-trade/reference/index.html",
            "concordance_reference_url": "https://www.census.gov/foreign-trade/data/dataproducts/concordance",
            "observed_issue": "Direct command-line static requests returned HTTP 403; the official Census reference page and browser download path provided the same files, with SHA-256 recorded in mapping_source_manifest.json.",
            "mapping_report": {
                "status": mapping_report["status"],
                "row_count": mapping_report["row_count"],
                "mapping_status_counts": mapping_report["mapping_status_counts"],
            },
        }
        if panel_report is not None:
            manifest_status = "policy_exposure_mapping_all_origin_panel_built_controls_pending"
            census_mapping["trade_panel"] = {
                "status": panel_report["status"],
                "source_scope": panel_report["source_scope"],
                "coverage": panel_report["coverage"],
                "combined_rows": panel_report["outputs"]["combined_rows"],
            }

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": manifest_status,
        "policy_sources": policy_records,
        "exclusion_sources": exclusion_records,
        "counts": {
            "list1_hts8": len(list1_codes),
            "list2_hts8": len(list2_codes),
            "list3_hts8": len(list3_codes),
            "exposure_rows": len(exposure_rows),
            "exclusion_batches": len(exclusion_rows),
        },
        "census_mapping": census_mapping,
    }
    with SOURCE_MANIFEST.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    write_source_report(manifest, mapping_report, panel_report)
    write_control_report(manifest, mapping_report, panel_report)
    return manifest


def main() -> None:
    manifest = build_outputs()
    print(
        "Built policy exposures: "
        f"List1={manifest['counts']['list1_hts8']}, "
        f"List2={manifest['counts']['list2_hts8']}, "
        f"List3={manifest['counts']['list3_hts8']}"
    )
    print(f"Wrote {EXPOSURE_CSV.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {EXCLUSION_CSV.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {SOURCE_MANIFEST.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {SOURCE_REPORT.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {CONTROL_REPORT_JSON.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {CONTROL_REPORT_MD.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
