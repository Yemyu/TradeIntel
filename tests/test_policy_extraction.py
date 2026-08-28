"""Acceptance checks for the official Section 301 List 1 extraction."""

import csv
import unittest

from src.policy.extract_ustr_list1 import (
    AMENDED_CODE,
    AMENDMENT_NOTICE,
    EVENT_CSV,
    INITIAL_NOTICE,
    ORIGINAL_INCOMPLETE_CODE,
    OUTPUT_CSV,
    amendment_is_verified,
    build_products,
    extract_raw_codes,
    validate_products,
)


class Section301List1ExtractionTests(unittest.TestCase):
    @unittest.skipUnless(
        INITIAL_NOTICE.exists() and AMENDMENT_NOTICE.exists(),
        "Run scripts/download_policy_sources.py for the PDF integration test",
    )
    def test_official_pdf_extraction_and_amendment(self) -> None:
        raw_codes = extract_raw_codes(INITIAL_NOTICE)
        products = build_products(raw_codes)
        audit = validate_products(raw_codes, products)

        self.assertEqual(audit["raw_count"], 818)
        self.assertEqual(audit["canonical_count"], 818)
        self.assertEqual(
            audit["raw_format_exceptions"], [ORIGINAL_INCOMPLETE_CODE]
        )
        self.assertTrue(amendment_is_verified(AMENDMENT_NOTICE))

    def test_processed_output_contains_official_correction(self) -> None:
        with OUTPUT_CSV.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))

        corrected = [row for row in rows if row["amended"] == "True"]
        self.assertEqual(len(rows), 818)
        self.assertEqual(len(corrected), 1)
        self.assertEqual(corrected[0]["raw_hts"], ORIGINAL_INCOMPLETE_CODE)
        self.assertEqual(corrected[0]["canonical_hts8"], AMENDED_CODE)
        self.assertEqual(corrected[0]["source_annex"], "Annex A")
        self.assertEqual(corrected[0]["exclusion_status"], "not_yet_modelled")

    def test_policy_event_has_official_effective_date_and_rate(self) -> None:
        with EVENT_CSV.open(encoding="utf-8", newline="") as file:
            events = list(csv.DictReader(file))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["effective_date"], "2018-07-06")
        self.assertEqual(events[0]["additional_rate"], "0.25")


if __name__ == "__main__":
    unittest.main()
