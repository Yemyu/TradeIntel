"""Extract and audit the Section 301 List 1 tariff codes from official PDFs."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INITIAL_NOTICE = PROJECT_ROOT / "data/raw/policy/ustr-section301-list1-2018.pdf"
AMENDMENT_NOTICE = (
    PROJECT_ROOT
    / "data/raw/policy/ustr-section301-list1-amendment-2018-08-16.pdf"
)
OUTPUT_CSV = (
    PROJECT_ROOT / "data/processed/policy/section301_list1_products.csv"
)
EVENT_CSV = PROJECT_ROOT / "data/processed/policy/section301_list1_event.csv"
AUDIT_JSON = PROJECT_ROOT / "data/processed/policy/section301_list1_audit.json"

INITIAL_SOURCE_URL = "https://ustr.gov/sites/default/files/2018-13248.pdf"
AMENDMENT_SOURCE_URL = (
    "https://ustr.gov/sites/default/files/enforcement/301Investigations/"
    "2018-17709.pdf"
)
EXPECTED_INITIAL_SHA256 = (
    "3e27dfb420dc308a079e7a71f2715fa29ed00fbbd84dbec4514f2cd66b9cf301"
)
EXPECTED_AMENDMENT_SHA256 = (
    "97a1883d0617b038e4b5bd2f6e36400168fcc27d67fe6562149cc85866c08729"
)

ANNEX_A_PAGES = range(5, 10)  # One-based PDF pages.
IMPLEMENTATION_HEADING = "9903.88.01"
ORIGINAL_INCOMPLETE_CODE = "9033.00"
AMENDED_CODE = "9033.00.90"
CODE_PATTERN = re.compile(r"(?<!\d)(\d{4}\.\d{2}(?:\.\d{2})?)(?!\d)")


@dataclass(frozen=True)
class PolicyProduct:
    policy_id: str
    raw_hts: str
    canonical_hts8: str
    source_annex: str
    source_page: int
    amended: bool
    amendment_source_page: int | None
    source_url: str
    amendment_source_url: str | None
    exclusion_status: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_raw_codes(pdf_path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(pdf_path)
    extracted: list[tuple[int, str]] = []

    for page_number in ANNEX_A_PAGES:
        text = reader.pages[page_number - 1].extract_text() or ""
        page_codes = CODE_PATTERN.findall(text)
        extracted.extend(
            (page_number, code)
            for code in page_codes
            if code != IMPLEMENTATION_HEADING
        )

    return extracted


def amendment_is_verified(pdf_path: Path) -> bool:
    reader = PdfReader(pdf_path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return (
        'deleting "9033.00"' in text
        and 'inserting "9033.00.90"' in text
    )


def build_products(raw_codes: list[tuple[int, str]]) -> list[PolicyProduct]:
    products: list[PolicyProduct] = []

    for page_number, raw_code in raw_codes:
        is_amended = raw_code == ORIGINAL_INCOMPLETE_CODE
        canonical_code = AMENDED_CODE if is_amended else raw_code
        products.append(
            PolicyProduct(
                policy_id="us_301_list1_2018",
                raw_hts=raw_code,
                canonical_hts8=canonical_code,
                source_annex="Annex A",
                source_page=page_number,
                amended=is_amended,
                amendment_source_page=16 if is_amended else None,
                source_url=INITIAL_SOURCE_URL,
                amendment_source_url=AMENDMENT_SOURCE_URL if is_amended else None,
                exclusion_status="not_yet_modelled",
            )
        )

    return products


def validate_products(
    raw_codes: list[tuple[int, str]], products: list[PolicyProduct]
) -> dict[str, object]:
    raw_values = [code for _, code in raw_codes]
    canonical_values = [product.canonical_hts8 for product in products]
    non_eight_digit_raw = [
        code for code in raw_values if len(code.replace(".", "")) != 8
    ]

    checks = {
        "raw_count_is_818": len(raw_values) == 818,
        "raw_codes_are_unique": len(raw_values) == len(set(raw_values)),
        "only_expected_raw_exception": non_eight_digit_raw
        == [ORIGINAL_INCOMPLETE_CODE],
        "canonical_count_is_818": len(canonical_values) == 818,
        "canonical_codes_are_unique": len(canonical_values)
        == len(set(canonical_values)),
        "canonical_codes_are_all_hts8": all(
            len(code.replace(".", "")) == 8 for code in canonical_values
        ),
        "amendment_applied_once": sum(product.amended for product in products)
        == 1,
    }

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"Policy extraction checks failed: {failed}")

    return {
        "checks": checks,
        "raw_count": len(raw_values),
        "canonical_count": len(canonical_values),
        "raw_format_exceptions": non_eight_digit_raw,
        "canonical_correction": {
            "from": ORIGINAL_INCOMPLETE_CODE,
            "to": AMENDED_CODE,
            "source_url": AMENDMENT_SOURCE_URL,
            "source_page": 16,
        },
    }


def write_outputs(
    products: list[PolicyProduct], audit: dict[str, object]
) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(products[0]).keys())

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(product) for product in products)

    event = {
        "policy_id": "us_301_list1_2018",
        "policy_name": "U.S. Section 301 List 1",
        "importer": "United States",
        "target_origin": "China",
        "announcement_date": "2018-06-15",
        "effective_date": "2018-07-06",
        "additional_rate": "0.25",
        "source_url": INITIAL_SOURCE_URL,
    }
    with EVENT_CSV.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(event))
        writer.writeheader()
        writer.writerow(event)

    with AUDIT_JSON.open("w", encoding="utf-8") as file:
        json.dump(audit, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    initial_hash = sha256_file(INITIAL_NOTICE)
    amendment_hash = sha256_file(AMENDMENT_NOTICE)
    if initial_hash != EXPECTED_INITIAL_SHA256:
        raise ValueError("Initial notice checksum does not match the audited source")
    if amendment_hash != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Amendment notice checksum does not match the audited source")
    if not amendment_is_verified(AMENDMENT_NOTICE):
        raise ValueError("Expected 9033.00 correction was not found in the amendment")

    raw_codes = extract_raw_codes(INITIAL_NOTICE)
    products = build_products(raw_codes)
    audit = validate_products(raw_codes, products)
    audit["sources"] = {
        "initial_notice": {
            "url": INITIAL_SOURCE_URL,
            "sha256": initial_hash,
            "pages_used": list(ANNEX_A_PAGES),
        },
        "amendment_notice": {
            "url": AMENDMENT_SOURCE_URL,
            "sha256": amendment_hash,
            "page_used": 16,
        },
    }
    write_outputs(products, audit)

    print(f"Extracted {len(products)} canonical List 1 tariff codes")
    print(f"Applied official correction: {ORIGINAL_INCOMPLETE_CODE} -> {AMENDED_CODE}")
    print(f"Wrote {EVENT_CSV.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {OUTPUT_CSV.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {AUDIT_JSON.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
