"""Audit frozen treatment/control eligibility before any matching or estimation.

This stage uses only the frozen clean pre-policy window for sample selection.
It expands official 2018 trade-action scope against the audited 2018 HTS10
universe, measures List 1 mapping coverage, and classifies canonical HS6
families as treated candidates, clean control candidates, or excluded.  It
does not read post-policy outcomes for selection, match controls, or estimate
a causal effect.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAUSAL_DIR = PROJECT_ROOT / "data/processed/causal"
DEFAULT_DESIGN = PROJECT_ROOT / "config/causal_control_design.json"
DEFAULT_MAPPING = CAUSAL_DIR / "hts_history_mapping.csv"
DEFAULT_LIST1_TRADE = PROJECT_ROOT / "data/processed/trade/trade_import_monthly.csv"
DEFAULT_ALL_ORIGIN_PANEL = CAUSAL_DIR / "causal_trade_hs6_monthly.csv"
DEFAULT_EXPOSURE = CAUSAL_DIR / "trade_action_exposure.csv"
DEFAULT_EXCLUSIONS = CAUSAL_DIR / "list1_exclusion_timeline.csv"
DEFAULT_ELIGIBILITY = CAUSAL_DIR / "control_eligibility.csv"
DEFAULT_POLICY_HS6 = CAUSAL_DIR / "policy_exposure_hs6.csv"
DEFAULT_MAPPING_EXCEPTIONS = CAUSAL_DIR / "treated_mapping_exceptions.csv"
DEFAULT_REPORT_JSON = CAUSAL_DIR / "control_eligibility_report.json"
DEFAULT_REPORT_MD = CAUSAL_DIR / "control_eligibility_report.md"

CHINA_ORIGIN_CODE = "5700"
CONCURRENT_POLICY_IDS = {
    "us_301_list2_2018",
    "us_301_list3_2018",
    "us_232_aluminum_2018",
    "us_232_steel_2018",
    "us_201_solar_2018",
    "us_201_washers_2018",
}

ELIGIBILITY_FIELDS = [
    "hs6_2017",
    "assignment_status",
    "primary_role",
    "exclusion_reasons",
    "pre_china_value_usd",
    "list1_pre_china_value_usd",
    "list1_pre_value_share",
    "positive_pre_months",
    "minimum_positive_pre_months",
    "list1_scope_overlap",
    "concurrent_policy_ids",
    "explicit_list1_exclusion",
    "naics3_candidates",
    "selection_window",
    "post_policy_activity_used",
]

POLICY_HS6_FIELDS = [
    "policy_id",
    "policy_name",
    "hs6_2017",
    "effective_dates",
    "source_scope_entries",
    "matched_2018_hts10_count",
    "fallback_hs6_only_scope_entries",
    "source_urls",
    "expansion_status",
]

MAPPING_EXCEPTION_FIELDS = [
    "source_year",
    "source_hts10",
    "source_hs6",
    "mapping_status",
    "wco_candidate_hs6",
    "wco_partial_or_ex",
    "historical_validity_status",
    "pre_china_value_usd",
    "value_share_of_raw_list1_pre",
    "resolution_status",
]


def digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def month_keys(
    start: tuple[int, int], end: tuple[int, int]
) -> list[tuple[int, int]]:
    keys: list[tuple[int, int]] = []
    year, month = start
    while (year, month) <= end:
        keys.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return keys


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def load_design(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        design = json.load(handle)
    if design.get("protocol_id") != "section301_list1_control_v1":
        raise ValueError(f"Unexpected causal protocol in {path}")
    if design["pre_policy_eligibility"].get("post_policy_activity_used_for_selection") is not False:
        raise ValueError("Frozen design must prohibit post-policy activity in selection")
    return design


def load_mapping(
    path: Path,
) -> tuple[
    dict[int, dict[str, dict[str, str]]],
    list[dict[str, str]],
    dict[str, set[str]],
]:
    mapping_by_year: dict[int, dict[str, dict[str, str]]] = defaultdict(dict)
    valid_2018: list[dict[str, str]] = []
    naics3_by_hs6: dict[str, set[str]] = defaultdict(set)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            year = int(row["source_year"])
            code = row["source_hts10"]
            if code in mapping_by_year[year]:
                raise ValueError(f"Duplicate mapping key {year}/{code}")
            mapping_by_year[year][code] = row
            hs6 = row["hs6_2017"]
            if hs6 and row["historical_validity_status"] == "valid":
                naics3 = row["naics6"][:3]
                if naics3:
                    naics3_by_hs6[hs6].add(naics3)
                if year == 2018:
                    valid_2018.append(row)
    if not valid_2018:
        raise ValueError("No valid 2018 mapping universe was found")
    return dict(mapping_by_year), valid_2018, dict(naics3_by_hs6)


def scope_matches(
    exposure: dict[str, str],
    *,
    by_hts8: dict[str, set[tuple[str, str]]],
    by_hts10: dict[str, set[tuple[str, str]]],
    by_source_hs6: dict[str, set[tuple[str, str]]],
    canonical_hs6_universe: set[str],
) -> tuple[set[tuple[str, str]], set[str], list[str]]:
    """Expand one official scope row into (HTS10, canonical HS6) pairs."""

    policy_id = exposure["policy_id"]
    level = exposure["coverage_level"]
    specification = exposure["hts_code"]
    matched: set[tuple[str, str]] = set()
    fallback_hs6: set[str] = set()
    unmatched_components: list[str] = []

    def add_component(
        component: str,
        pairs: set[tuple[str, str]],
        *,
        fallback_target: str | None = None,
    ) -> None:
        if pairs:
            matched.update(pairs)
        elif fallback_target and len(fallback_target) == 6:
            # The 2018 policy notice and HS6_2017 use the same HS revision.
            # Retaining the official code's first six digits records policy
            # scope even if Census has no import line for that product.  It
            # does not invent a trade observation or a cross-year mapping.
            fallback_hs6.add(str(fallback_target))
        else:
            unmatched_components.append(component)

    if level == "HTS8":
        code = digits(specification)
        add_component(code, by_hts8.get(code, set()), fallback_target=code[:6])
    elif level == "HTS8_set":
        for raw_code in specification.split(";"):
            code = digits(raw_code)
            add_component(code, by_hts8.get(code, set()), fallback_target=code[:6])
    elif policy_id == "us_232_aluminum_2018":
        for raw_code in specification.split(";"):
            code = digits(raw_code)
            if len(code) == 10:
                add_component(code, by_hts10.get(code, set()), fallback_target=code[:6])
            else:
                pairs = {
                    pair
                    for source_hs6, source_pairs in by_source_hs6.items()
                    if source_hs6.startswith(code)
                    for pair in source_pairs
                }
                add_component(code, pairs)
    elif level == "HTS6_heading":
        code = digits(specification)
        add_component(code, by_source_hs6.get(code, set()), fallback_target=code)
    elif level == "heading_range":
        bounds = [digits(value) for value in re.split(r"[–-]", specification)]
        if len(bounds) != 2 or any(len(value) != 6 for value in bounds):
            raise ValueError(f"Invalid heading range: {specification}")
        start, end = bounds
        pairs = {
            pair
            for source_hs6, source_pairs in by_source_hs6.items()
            if start <= source_hs6 <= end
            for pair in source_pairs
        }
        add_component(f"{start}-{end}", pairs)
    else:
        raise ValueError(
            f"Unsupported official scope rule: {policy_id}/{level}/{specification}"
        )
    return matched, fallback_hs6, unmatched_components


def expand_policy_exposure(
    exposure_path: Path, valid_2018: list[dict[str, str]]
) -> tuple[list[dict[str, object]], dict[str, set[str]], list[str]]:
    by_hts8: dict[str, set[tuple[str, str]]] = defaultdict(set)
    by_hts10: dict[str, set[tuple[str, str]]] = defaultdict(set)
    by_source_hs6: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in valid_2018:
        pair = (row["source_hts10"], row["hs6_2017"])
        by_hts8[row["source_hts10"][:8]].add(pair)
        by_hts10[row["source_hts10"]].add(pair)
        by_source_hs6[row["source_hs6"]].add(pair)
    canonical_hs6_universe = {row["hs6_2017"] for row in valid_2018}

    aggregation: dict[tuple[str, str], dict[str, object]] = {}
    policy_hs6: dict[str, set[str]] = defaultdict(set)
    unmatched: list[str] = []
    with exposure_path.open(newline="", encoding="utf-8") as handle:
        for exposure in csv.DictReader(handle):
            pairs, fallback_targets, missing_components = scope_matches(
                exposure,
                by_hts8=by_hts8,
                by_hts10=by_hts10,
                by_source_hs6=by_source_hs6,
                canonical_hs6_universe=canonical_hs6_universe,
            )
            unmatched.extend(
                f"{exposure['exposure_id']}:{component}"
                for component in missing_components
            )
            pairs_by_target: dict[str, set[str]] = defaultdict(set)
            for hts10, target_hs6 in pairs:
                pairs_by_target[target_hs6].add(hts10)
            for target_hs6 in sorted(set(pairs_by_target) | fallback_targets):
                hts10_codes = pairs_by_target.get(target_hs6, set())
                policy_hs6[exposure["policy_id"]].add(target_hs6)
                key = (exposure["policy_id"], target_hs6)
                if key not in aggregation:
                    aggregation[key] = {
                        "policy_id": exposure["policy_id"],
                        "policy_name": exposure["policy_name"],
                        "hs6_2017": target_hs6,
                        "effective_dates": set(),
                        "source_scope_entries": set(),
                        "matched_hts10": set(),
                        "fallback_scope_entries": set(),
                        "source_urls": set(),
                    }
                item = aggregation[key]
                item["effective_dates"].add(exposure["effective_date"])
                item["source_scope_entries"].add(
                    f"{exposure['exposure_id']}={exposure['hts_code']}"
                )
                item["matched_hts10"].update(hts10_codes)
                if target_hs6 in fallback_targets:
                    item["fallback_scope_entries"].add(
                        f"{exposure['exposure_id']}={exposure['hts_code']}"
                    )
                item["source_urls"].add(exposure["source_url"])

    output_rows: list[dict[str, object]] = []
    for key in sorted(aggregation):
        item = aggregation[key]
        output_rows.append(
            {
                "policy_id": item["policy_id"],
                "policy_name": item["policy_name"],
                "hs6_2017": item["hs6_2017"],
                "effective_dates": "|".join(sorted(item["effective_dates"])),
                "source_scope_entries": "|".join(
                    sorted(item["source_scope_entries"])
                ),
                "matched_2018_hts10_count": len(item["matched_hts10"]),
                "fallback_hs6_only_scope_entries": "|".join(
                    sorted(item["fallback_scope_entries"])
                ),
                "source_urls": "|".join(sorted(item["source_urls"])),
                "expansion_status": (
                    "official_scope_recorded_at_same_revision_hs6_no_trade_line"
                    if item["fallback_scope_entries"]
                    and item["hs6_2017"] not in canonical_hs6_universe
                    else "official_scope_expanded_with_same_revision_hs6_fallback"
                    if item["fallback_scope_entries"]
                    else "official_scope_expanded_on_valid_2018_hts_universe"
                ),
            }
        )
    return output_rows, dict(policy_hs6), sorted(unmatched)


def audit_list1_preperiod(
    trade_path: Path,
    mapping_by_year: dict[int, dict[str, dict[str, str]]],
    *,
    pre_start: tuple[int, int],
    pre_end: tuple[int, int],
    official_list1_hts8: set[str],
) -> tuple[dict[str, object], dict[str, int], list[dict[str, object]]]:
    raw_value = 0
    mapped_value = 0
    ambiguous_value = 0
    invalid_or_unmapped_value = 0
    positive_year_codes: set[tuple[int, str]] = set()
    mapped_positive_year_codes: set[tuple[int, str]] = set()
    ambiguous_positive_year_codes: set[tuple[int, str]] = set()
    invalid_positive_year_codes: set[tuple[int, str]] = set()
    list1_value_by_hs6: dict[str, int] = defaultdict(int)
    exception_value_by_key: dict[tuple[int, str], int] = defaultdict(int)
    exception_metadata: dict[tuple[int, str], dict[str, str]] = {}
    unexpected_hts8: set[str] = set()

    with trade_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            year, month = int(row["year"]), int(row["month"])
            if not (pre_start <= (year, month) <= pre_end):
                continue
            if row["origin_code"] != CHINA_ORIGIN_CODE:
                continue
            value = int(row["import_value_consumption_usd"])
            code = row["hts10"]
            if row["hts8"] not in official_list1_hts8:
                unexpected_hts8.add(row["hts8"])
            raw_value += value
            if value > 0:
                positive_year_codes.add((year, code))
            mapping = mapping_by_year.get(year, {}).get(code)
            if (
                mapping
                and mapping["historical_validity_status"] == "valid"
                and mapping["hs6_2017"]
            ):
                mapped_value += value
                list1_value_by_hs6[mapping["hs6_2017"]] += value
                if value > 0:
                    mapped_positive_year_codes.add((year, code))
            elif mapping and mapping["mapping_status"] == "wco_partial_or_ambiguous":
                ambiguous_value += value
                key = (year, code)
                exception_value_by_key[key] += value
                exception_metadata[key] = mapping
                if value > 0:
                    ambiguous_positive_year_codes.add((year, code))
            else:
                invalid_or_unmapped_value += value
                key = (year, code)
                exception_value_by_key[key] += value
                exception_metadata[key] = mapping or {}
                if value > 0:
                    invalid_positive_year_codes.add((year, code))

    if unexpected_hts8:
        raise ValueError(
            "List 1-only trade panel contains codes outside the official list: "
            + ", ".join(sorted(unexpected_hts8)[:5])
        )
    if raw_value <= 0 or not positive_year_codes:
        raise ValueError("No positive pre-policy List 1 China trade was found")
    audit = {
        "raw_china_value_usd": raw_value,
        "mapped_china_value_usd": mapped_value,
        "mapped_value_coverage": mapped_value / raw_value,
        "ambiguous_china_value_usd": ambiguous_value,
        "ambiguous_value_share": ambiguous_value / raw_value,
        "invalid_or_unmapped_china_value_usd": invalid_or_unmapped_value,
        "observed_positive_year_hts10_count": len(positive_year_codes),
        "mapped_positive_year_hts10_count": len(mapped_positive_year_codes),
        "mapped_hts10_code_coverage": len(mapped_positive_year_codes)
        / len(positive_year_codes),
        "ambiguous_positive_year_hts10_count": len(
            ambiguous_positive_year_codes
        ),
        "invalid_or_unmapped_positive_year_hts10_count": len(
            invalid_positive_year_codes
        ),
        "observed_unique_hts10_count": len(
            {code for _, code in positive_year_codes}
        ),
    }
    exception_rows: list[dict[str, object]] = []
    for year, code in sorted(
        exception_value_by_key,
        key=lambda key: (-exception_value_by_key[key], key),
    ):
        mapping = exception_metadata[(year, code)]
        mapping_status = mapping.get("mapping_status", "mapping_key_not_found")
        exception_rows.append(
            {
                "source_year": year,
                "source_hts10": code,
                "source_hs6": mapping.get("source_hs6", code[:6]),
                "mapping_status": mapping_status,
                "wco_candidate_hs6": mapping.get("wco_candidate_hs6", ""),
                "wco_partial_or_ex": mapping.get("wco_partial_or_ex", ""),
                "historical_validity_status": mapping.get(
                    "historical_validity_status", "mapping_key_not_found"
                ),
                "pre_china_value_usd": exception_value_by_key[(year, code)],
                "value_share_of_raw_list1_pre": (
                    f"{exception_value_by_key[(year, code)] / raw_value:.12f}"
                ),
                "resolution_status": (
                    "requires_official_concordance_resolution"
                    if mapping_status == "wco_partial_or_ambiguous"
                    else "requires_missing_or_invalid_mapping_review"
                ),
            }
        )
    return audit, dict(list1_value_by_hs6), exception_rows


def load_preperiod_panel(
    panel_path: Path,
    *,
    pre_start: tuple[int, int],
    pre_end: tuple[int, int],
) -> tuple[dict[str, int], dict[str, set[tuple[int, int]]]]:
    china_value_by_hs6: dict[str, int] = defaultdict(int)
    positive_months_by_hs6: dict[str, set[tuple[int, int]]] = defaultdict(set)
    seen_keys: set[tuple[int, int, str]] = set()
    observed_months: set[tuple[int, int]] = set()
    with panel_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            year, month = int(row["year"]), int(row["month"])
            if not (pre_start <= (year, month) <= pre_end):
                continue
            observed_months.add((year, month))
            hs6 = row["hs6_2017"]
            key = (year, month, hs6)
            if key in seen_keys:
                raise ValueError(f"Duplicate all-origin panel key: {key}")
            seen_keys.add(key)
            value = int(row["china_import_value_consumption_usd"])
            china_value_by_hs6[hs6] += value
            if value > 0:
                positive_months_by_hs6[hs6].add((year, month))
    if not china_value_by_hs6:
        raise ValueError("No pre-policy all-origin panel rows were found")
    expected_months = set(month_keys(pre_start, pre_end))
    if observed_months != expected_months:
        missing = sorted(expected_months - observed_months)
        extra = sorted(observed_months - expected_months)
        raise ValueError(
            f"Pre-policy panel month coverage mismatch; missing={missing}, extra={extra}"
        )
    return dict(china_value_by_hs6), dict(positive_months_by_hs6)


def map_explicit_exclusions(
    exclusions_path: Path,
    mapping_by_year: dict[int, dict[str, dict[str, str]]],
) -> tuple[set[str], dict[str, object]]:
    explicit_codes: set[str] = set()
    mapped_hs6: set[str] = set()
    unmapped_codes: set[str] = set()
    description_scope_present = False
    with exclusions_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            description_scope_present = description_scope_present or row[
                "descriptive_scope_count"
            ] not in {"", "0", "unknown"}
            for raw_code in row["explicit_hts10_codes"].split("|"):
                code = digits(raw_code)
                if not code:
                    continue
                explicit_codes.add(code)
                targets: set[str] = set()
                for year in (2018, 2019):
                    mapping = mapping_by_year.get(year, {}).get(code)
                    if (
                        mapping
                        and mapping["historical_validity_status"] == "valid"
                        and mapping["hs6_2017"]
                    ):
                        targets.add(mapping["hs6_2017"])
                if targets:
                    mapped_hs6.update(targets)
                else:
                    unmapped_codes.add(code)
    return mapped_hs6, {
        "explicit_hts10_count": len(explicit_codes),
        "mapped_hs6_count": len(mapped_hs6),
        "unmapped_explicit_hts10": sorted(unmapped_codes),
        "narrative_product_descriptions_present": description_scope_present,
        "sensitivity_scope_complete": not description_scope_present
        and not unmapped_codes,
    }


def classify_families(
    *,
    china_value_by_hs6: dict[str, int],
    positive_months_by_hs6: dict[str, set[tuple[int, int]]],
    list1_value_by_hs6: dict[str, int],
    policy_hs6: dict[str, set[str]],
    explicit_exclusion_hs6: set[str],
    naics3_by_hs6: dict[str, set[str]],
    minimum_positive_months: int,
    selection_window: str,
) -> tuple[list[dict[str, object]], Counter[str]]:
    all_policy_by_hs6: dict[str, set[str]] = defaultdict(set)
    for policy_id, families in policy_hs6.items():
        for hs6 in families:
            all_policy_by_hs6[hs6].add(policy_id)

    output: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    for hs6 in sorted(china_value_by_hs6):
        total_value = china_value_by_hs6[hs6]
        list1_value = list1_value_by_hs6.get(hs6, 0)
        if list1_value > total_value:
            raise ValueError(
                f"List 1 value exceeds all-China value for {hs6}: "
                f"{list1_value} > {total_value}"
            )
        list1_share = list1_value / total_value if total_value else 0.0
        if list1_value > 0 and list1_value == total_value:
            assignment = "pure_list1"
        elif list1_value > 0:
            assignment = "mixed_list1"
        else:
            assignment = "non_list1"

        positive_months = len(positive_months_by_hs6.get(hs6, set()))
        policy_ids = all_policy_by_hs6.get(hs6, set())
        concurrent = sorted(policy_ids & CONCURRENT_POLICY_IDS)
        reasons: list[str] = []
        role = "excluded"
        if positive_months < minimum_positive_months:
            reasons.append("insufficient_positive_pre_months")
        if assignment == "mixed_list1":
            reasons.append("mixed_list1_pre_value_share")

        if assignment == "pure_list1":
            if concurrent:
                reasons.append("concurrent_policy_scope_overlap")
            if not reasons:
                role = "treated_candidate"
        elif assignment == "non_list1":
            if policy_ids:
                reasons.append("direct_policy_scope_overlap")
            if not reasons:
                role = "control_candidate"

        counts[f"assignment_{assignment}"] += 1
        counts[f"primary_role_{role}"] += 1
        for reason in reasons:
            counts[f"reason_{reason}"] += 1
        output.append(
            {
                "hs6_2017": hs6,
                "assignment_status": assignment,
                "primary_role": role,
                "exclusion_reasons": "|".join(reasons),
                "pre_china_value_usd": total_value,
                "list1_pre_china_value_usd": list1_value,
                "list1_pre_value_share": f"{list1_share:.12f}",
                "positive_pre_months": positive_months,
                "minimum_positive_pre_months": minimum_positive_months,
                "list1_scope_overlap": int(
                    hs6 in policy_hs6.get("us_301_list1_2018", set())
                ),
                "concurrent_policy_ids": "|".join(concurrent),
                "explicit_list1_exclusion": int(hs6 in explicit_exclusion_hs6),
                "naics3_candidates": "|".join(sorted(naics3_by_hs6.get(hs6, set()))),
                "selection_window": selection_window,
                "post_policy_activity_used": 0,
            }
        )
    return output, counts


def threshold_results(
    *,
    design: dict[str, object],
    mapping_audit: dict[str, object],
    classification_counts: Counter[str],
    unmatched_policy_scope: list[str],
) -> dict[str, dict[str, object]]:
    thresholds = design["product_mapping"]["mapping_adoption_thresholds"]
    minimum_sample = design["minimum_sample"]
    values = {
        "treated_pre_value_coverage": (
            mapping_audit["mapped_value_coverage"],
            thresholds["treated_pre_value_coverage_min"],
            "minimum",
        ),
        "treated_hts10_code_coverage": (
            mapping_audit["mapped_hts10_code_coverage"],
            thresholds["treated_hts10_code_coverage_min"],
            "minimum",
        ),
        "ambiguous_value_share": (
            mapping_audit["ambiguous_value_share"],
            thresholds["ambiguous_value_share_max"],
            "maximum",
        ),
        "pure_treated_hs6": (
            classification_counts["primary_role_treated_candidate"],
            minimum_sample["treated_canonical_hs6"],
            "minimum",
        ),
        "clean_control_hs6": (
            classification_counts["primary_role_control_candidate"],
            minimum_sample["control_canonical_hs6"],
            "minimum",
        ),
        "official_policy_scope_expansion": (
            len(unmatched_policy_scope),
            0,
            "maximum",
        ),
    }
    results: dict[str, dict[str, object]] = {}
    for name, (observed, threshold, direction) in values.items():
        passed = observed >= threshold if direction == "minimum" else observed <= threshold
        results[name] = {
            "observed": observed,
            "threshold": threshold,
            "direction": direction,
            "passed": passed,
        }
    return results


def build_report_markdown(report: dict[str, object]) -> str:
    audit = report["mapping_audit"]
    counts = report["classification_counts"]
    gates = report["eligibility_gates"]
    gate_lines = []
    for name, gate in gates.items():
        observed = gate["observed"]
        threshold = gate["threshold"]
        if isinstance(observed, float):
            observed_text = f"{observed:.2%}"
            threshold_text = f"{threshold:.2%}"
        else:
            observed_text = f"{observed:,}"
            threshold_text = f"{threshold:,}"
        gate_lines.append(
            f"| `{name}` | {observed_text} | {gate['direction']} {threshold_text} | "
            f"{'通过' if gate['passed'] else '失败'} |"
        )
    status_text = (
        "资格门槛通过，可以进入匹配设计；仍然没有因果结果。"
        if report["status"] == "eligibility_gates_passed_matching_pending"
        else "至少一道冻结门槛失败，停止在资格层，不进入匹配。"
    )
    return f"""# Phase 07：处理组与对照组资格审查

> 状态：`{report['status']}`

## 本阶段回答了什么

本阶段只回答“哪些 HS6 有资格进入下一步匹配”。资格只使用 2016-01 至 2018-05 的政策前信息；没有根据政策后的涨跌选择商品，也没有运行事件研究。

## 冻结门槛结果

| 门槛 | 实际值 | 规则 | 结果 |
|---|---:|---:|---|
{chr(10).join(gate_lines)}

{status_text}

## 样本分类

- 纯 List 1 家族：{counts.get('assignment_pure_list1', 0):,}；
- 混合 List 1 家族：{counts.get('assignment_mixed_list1', 0):,}；
- 非 List 1 家族：{counts.get('assignment_non_list1', 0):,}；
- 通过政策前活跃度与污染规则的处理候选：{counts.get('primary_role_treated_candidate', 0):,}；
- 通过政策前活跃度与污染规则的对照候选：{counts.get('primary_role_control_candidate', 0):,}；
- 必须排除：{counts.get('primary_role_excluded', 0):,}。

## 覆盖率怎样理解

原始 List 1 政策前中国进口金额为 {audit['raw_china_value_usd']:,} 美元，其中 {audit['mapped_china_value_usd']:,} 美元成功映射到 `HS6_2017`。金额覆盖率和 HTS10 覆盖率是“处理组原始细项能否可靠放入统一商品家族”的检查，不是模型准确率，也不是关税效果。

## 尚未完成

`control_eligibility.csv` 记录每个 HS6 的角色和排除原因；`policy_exposure_hs6.csv` 记录官方政策范围怎样展开到统一商品家族；`treated_mapping_exceptions.csv` 按政策前进口金额从高到低列出不能唯一映射的年份 × HTS10，供下一阶段逐项查证。List 1 产品排除中的明确 HTS10 已作为元数据映射，但官方通知里的文字商品描述仍未自动猜测，因此“删除所有曾排除商品”的敏感性分析仍标记为不完整。

下一步只有在本页所有资格门槛通过后，才会计算政策前特征、在相同 NAICS3 内匹配，并检查标准化差异与前趋势。
"""


def build_eligibility(
    *,
    design_path: Path,
    mapping_path: Path,
    list1_trade_path: Path,
    all_origin_panel_path: Path,
    exposure_path: Path,
    exclusions_path: Path,
    eligibility_path: Path,
    policy_hs6_path: Path,
    mapping_exceptions_path: Path,
    report_json_path: Path,
    report_md_path: Path,
) -> dict[str, object]:
    design = load_design(design_path)
    pre_start_text, pre_end_text = design["time_windows"]["clean_pre"]
    pre_start = tuple(int(value) for value in pre_start_text.split("-"))
    pre_end = tuple(int(value) for value in pre_end_text.split("-"))
    selection_window = f"{pre_start_text}_to_{pre_end_text}"
    minimum_positive_months = design["pre_policy_eligibility"][
        "minimum_positive_months_out_of_29"
    ]

    mapping_by_year, valid_2018, naics3_by_hs6 = load_mapping(mapping_path)
    policy_rows, policy_hs6, unmatched_policy_scope = expand_policy_exposure(
        exposure_path, valid_2018
    )
    # Use the source exposure table as the authoritative List 1 code set.
    with exposure_path.open(newline="", encoding="utf-8") as handle:
        official_list1_hts8 = {
            digits(row["hts_code"])
            for row in csv.DictReader(handle)
            if row["policy_id"] == "us_301_list1_2018"
        }

    mapping_audit, list1_value_by_hs6, mapping_exception_rows = audit_list1_preperiod(
        list1_trade_path,
        mapping_by_year,
        pre_start=pre_start,
        pre_end=pre_end,
        official_list1_hts8=official_list1_hts8,
    )
    china_value_by_hs6, positive_months_by_hs6 = load_preperiod_panel(
        all_origin_panel_path, pre_start=pre_start, pre_end=pre_end
    )
    explicit_exclusion_hs6, exclusion_audit = map_explicit_exclusions(
        exclusions_path, mapping_by_year
    )
    eligibility_rows, classification_counts = classify_families(
        china_value_by_hs6=china_value_by_hs6,
        positive_months_by_hs6=positive_months_by_hs6,
        list1_value_by_hs6=list1_value_by_hs6,
        policy_hs6=policy_hs6,
        explicit_exclusion_hs6=explicit_exclusion_hs6,
        naics3_by_hs6=naics3_by_hs6,
        minimum_positive_months=minimum_positive_months,
        selection_window=selection_window,
    )
    gates = threshold_results(
        design=design,
        mapping_audit=mapping_audit,
        classification_counts=classification_counts,
        unmatched_policy_scope=unmatched_policy_scope,
    )
    all_passed = all(gate["passed"] for gate in gates.values())
    report: dict[str, object] = {
        "status": (
            "eligibility_gates_passed_matching_pending"
            if all_passed
            else "blocked_before_matching"
        ),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "protocol_id": design["protocol_id"],
        "selection_window": {
            "start": pre_start_text,
            "end": pre_end_text,
            "month_count": len(month_keys(pre_start, pre_end)),
            "post_policy_outcomes_used": False,
        },
        "mapping_audit": mapping_audit,
        "policy_scope_hs6_counts": {
            policy_id: len(families)
            for policy_id, families in sorted(policy_hs6.items())
        },
        "unmatched_official_policy_scope_components": unmatched_policy_scope,
        "list1_exclusion_audit": exclusion_audit,
        "classification_counts": dict(classification_counts),
        "eligibility_gates": gates,
        "outputs": {
            "control_eligibility": eligibility_path.relative_to(PROJECT_ROOT).as_posix(),
            "policy_exposure_hs6": policy_hs6_path.relative_to(PROJECT_ROOT).as_posix(),
            "treated_mapping_exceptions": mapping_exceptions_path.relative_to(
                PROJECT_ROOT
            ).as_posix(),
        },
        "input_sha256": {
            "design": sha256_file(design_path),
            "mapping": sha256_file(mapping_path),
            "list1_trade_panel": sha256_file(list1_trade_path),
            "all_origin_panel": sha256_file(all_origin_panel_path),
            "policy_exposure": sha256_file(exposure_path),
            "list1_exclusions": sha256_file(exclusions_path),
        },
        "interpretation_boundary": "Eligibility only. No matching, post-policy selection, event-study estimation, or causal claim was produced.",
    }

    write_csv(policy_hs6_path, POLICY_HS6_FIELDS, policy_rows)
    write_csv(eligibility_path, ELIGIBILITY_FIELDS, eligibility_rows)
    write_csv(
        mapping_exceptions_path,
        MAPPING_EXCEPTION_FIELDS,
        mapping_exception_rows,
    )
    report_json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_md_path.write_text(build_report_markdown(report), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--list1-trade", type=Path, default=DEFAULT_LIST1_TRADE)
    parser.add_argument("--all-origin-panel", type=Path, default=DEFAULT_ALL_ORIGIN_PANEL)
    parser.add_argument("--exposure", type=Path, default=DEFAULT_EXPOSURE)
    parser.add_argument("--exclusions", type=Path, default=DEFAULT_EXCLUSIONS)
    parser.add_argument("--eligibility", type=Path, default=DEFAULT_ELIGIBILITY)
    parser.add_argument("--policy-hs6", type=Path, default=DEFAULT_POLICY_HS6)
    parser.add_argument(
        "--mapping-exceptions", type=Path, default=DEFAULT_MAPPING_EXCEPTIONS
    )
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_eligibility(
            design_path=args.design,
            mapping_path=args.mapping,
            list1_trade_path=args.list1_trade,
            all_origin_panel_path=args.all_origin_panel,
            exposure_path=args.exposure,
            exclusions_path=args.exclusions,
            eligibility_path=args.eligibility,
            policy_hs6_path=args.policy_hs6,
            mapping_exceptions_path=args.mapping_exceptions,
            report_json_path=args.report_json,
            report_md_path=args.report_md,
        )
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"Control eligibility build failed: {exc}")
        return 1
    print(f"Status: {report['status']}")
    print(
        "Eligible HS6: "
        f"treated={report['classification_counts'].get('primary_role_treated_candidate', 0)}, "
        f"controls={report['classification_counts'].get('primary_role_control_candidate', 0)}"
    )
    print(f"Wrote {args.report_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
