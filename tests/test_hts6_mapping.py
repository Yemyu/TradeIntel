"""Acceptance checks for the conservative official HTS history mapping."""

import csv
import json
import unittest
from collections import Counter

from scripts.build_hts6_mapping import (
    MAPPING_CSV,
    MAPPING_REPORT_JSON,
    MAPPING_SOURCE_MANIFEST,
)


@unittest.skipUnless(MAPPING_CSV.exists(), "HTS history mapping output is not present")
class Hts6MappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with MAPPING_CSV.open(encoding="utf-8", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))

    def test_year_counts_and_unique_source_keys(self) -> None:
        counts = Counter(int(row["source_year"]) for row in self.rows)
        self.assertEqual(
            counts,
            {2016: 19193, 2017: 18982, 2018: 19011, 2019: 19118},
        )
        keys = {(row["source_year"], row["source_hts10"]) for row in self.rows}
        self.assertEqual(len(keys), len(self.rows))

    def test_wco_partial_mapping_is_not_forced(self) -> None:
        row = next(
            item
            for item in self.rows
            if item["source_year"] == "2016"
            and item["source_hts10"] == "0302895064"
        )
        self.assertEqual(row["mapping_status"], "wco_partial_or_ambiguous")
        self.assertEqual(row["hs6_2017"], "")
        self.assertEqual(row["wco_partial_or_ex"], "1")
        self.assertEqual(
            row["wco_candidate_hs6"], "030249|030273|030289|030299"
        )

    def test_wco_exact_mapping_is_explicit(self) -> None:
        row = next(
            item
            for item in self.rows
            if item["source_year"] == "2016"
            and item["source_hts10"] == "0302902000"
        )
        self.assertEqual(row["mapping_status"], "wco_exact_single")
        self.assertEqual(row["hs6_2017"], "030291")
        self.assertEqual(row["wco_partial_or_ex"], "0")

    def test_unchanged_year_uses_hs6_prefix(self) -> None:
        row = next(
            item
            for item in self.rows
            if item["source_year"] == "2017"
            and item["source_hts10"] == "8401400000"
        )
        self.assertEqual(row["mapping_status"], "same_hs6_prefix")
        self.assertEqual(row["source_hs6"], "840140")
        self.assertEqual(row["hs6_2017"], "840140")

    def test_report_and_manifest_record_official_sources(self) -> None:
        with MAPPING_REPORT_JSON.open(encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["status"], "mapping_built_with_conservative_ambiguity_flags")
        self.assertEqual(report["row_count"], len(self.rows))
        self.assertEqual(report["wco_correlation_source_count"], 291)
        self.assertTrue(report["rules"]["no_fuzzy_names"])

        with MAPPING_SOURCE_MANIFEST.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(len(manifest["sources"]), 6)
        self.assertTrue(all(item["url"].startswith("https://") for item in manifest["sources"]))
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["sources"]))


if __name__ == "__main__":
    unittest.main()
