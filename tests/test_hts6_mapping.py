"""Acceptance checks for the conservative official HTS history mapping."""

import csv
import json
import unittest
from collections import Counter

from scripts.build_hts6_mapping import (
    MAPPING_CSV,
    MAPPING_REPORT_JSON,
    MAPPING_SOURCE_MANIFEST,
    exact_hts10_continuity_target,
)


class ExactContinuityRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.code = "8529909900"
        self.metadata = {
            "description": "Parts of headings 8525 to 8528, NESOI",
            "unit_qy1": "X",
            "unit_qy2": "",
        }
        self.anchor = {self.code: dict(self.metadata)}
        self.wco = {
            "852990": [
                {"target": "852990", "partial": False},
                {"target": "962000", "partial": True},
            ]
        }
        self.validity = {
            self.code: [{"begin": "01/2012", "end": "Current"}]
        }

    def test_exact_official_code_description_units_and_validity_are_accepted(self):
        target = exact_hts10_continuity_target(
            source_year=2016,
            source_hts10=self.code,
            source_metadata=self.metadata,
            anchor_2017=self.anchor,
            wco=self.wco,
            validity=self.validity,
        )
        self.assertEqual(target, "852990")

    def test_changed_official_description_is_not_accepted(self):
        self.anchor[self.code]["description"] = "A different statistical scope"
        target = exact_hts10_continuity_target(
            source_year=2016,
            source_hts10=self.code,
            source_metadata=self.metadata,
            anchor_2017=self.anchor,
            wco=self.wco,
            validity=self.validity,
        )
        self.assertEqual(target, "")


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
            {2016: 19193, 2017: 19050, 2018: 19277, 2019: 19171},
        )
        keys = {(row["source_year"], row["source_hts10"]) for row in self.rows}
        self.assertEqual(len(keys), len(self.rows))

    def test_wco_partial_mapping_is_not_forced(self) -> None:
        row = next(
            item
            for item in self.rows
            if item["source_year"] == "2016"
            and item["source_hts10"] == "0302895076"
        )
        self.assertEqual(row["mapping_status"], "wco_partial_or_ambiguous")
        self.assertEqual(row["hs6_2017"], "")
        self.assertEqual(row["wco_partial_or_ex"], "1")
        self.assertEqual(
            row["wco_candidate_hs6"], "030249|030273|030289|030299"
        )

    def test_exact_census_hts10_continuity_is_explicit(self) -> None:
        row = next(
            item
            for item in self.rows
            if item["source_year"] == "2016"
            and item["source_hts10"] == "8529909900"
        )
        self.assertEqual(row["mapping_status"], "census_exact_hts10_continuity")
        self.assertEqual(row["hs6_2017"], "852990")
        self.assertEqual(
            row["mapping_source_url"],
            "https://www.census.gov/foreign-trade/reference/codes/concordance/impconcord17.xls",
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

    def test_valid_historical_only_code_uses_existing_anchor_prefix(self) -> None:
        row = next(
            item
            for item in self.rows
            if item["source_year"] == "2018"
            and item["source_hts10"] == "8517620090"
        )
        self.assertEqual(row["mapping_status"], "history_only_same_hs6_prefix")
        self.assertEqual(row["hs6_2017"], "851762")
        self.assertEqual(row["annual_concordance_present"], "0")
        self.assertEqual(row["historical_validity_status"], "valid")

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
