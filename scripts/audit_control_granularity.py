"""Inventory policy-scope granularity only; never reads trade outcomes."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from build_control_eligibility import load_mapping, scope_matches, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def audit():
    base = ROOT / "data/processed/causal"
    paths = [base / name for name in (
        "control_eligibility.csv", "hts_history_mapping.csv", "trade_action_exposure.csv"
    )]
    _, valid, _ = load_mapping(paths[1])
    indexes = [defaultdict(set) for _ in range(3)]
    families = defaultdict(set)
    for row in valid:
        code, family = row["source_hts10"], row["hs6_2017"]
        pair = (code, family)
        for index, key in zip(indexes, (code[:8], code, row["source_hs6"])):
            index[key].add(pair)
        families[family].add(code)
    covered = defaultdict(set)
    fallbacks = defaultdict(set)
    missing = []
    policies = defaultdict(set)
    with paths[2].open(newline="") as handle:
        for row in csv.DictReader(handle):
            pairs, fallback, unresolved = scope_matches(
                row, by_hts8=indexes[0], by_hts10=indexes[1],
                by_source_hs6=indexes[2], canonical_hs6_universe=set(families)
            )
            for code, family in pairs:
                covered[family].add(code)
            for family in fallback:
                fallbacks[family].add(row["policy_id"])
            missing.extend(f"{row['exposure_id']}:{item}" for item in unresolved)
            policies[row["policy_id"]].add((row["effective_date"], row["target_origin"]))
    records = []
    with paths[0].open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len({row["hs6_2017"] for row in rows}) != len(rows):
        raise ValueError("Duplicate eligibility family")
    for row in rows:
        if row["naics3_candidates"] != "333" or row["primary_role"] != "excluded":
            continue
        if row["post_policy_activity_used"] != "0":
            raise ValueError("Post-policy selection flag")
        family = row["hs6_2017"]
        children = families[family]
        uncovered = children - covered[family]
        records.append({
            "hs6": family, "reasons": row["exclusion_reasons"],
            "positive_pre_months": int(row["positive_pre_months"]),
            "valid_2018_children": len(children),
            "covered_children": len(children & covered[family]),
            "uncovered_children": sorted(uncovered),
            "family_fallback_policies": sorted(fallbacks[family]),
        })
    return {
        "scope": "333 excluded families; policy metadata only; no outcome parsing",
        "source_sha256": {str(p.relative_to(ROOT)): sha256_file(p) for p in paths},
        "protocol_sha256": sha256_file(ROOT / "docs/decisions/0045-control-granularity-audit.zh-CN.md"),
        "excluded_families": len(records),
        "reason_counts": dict(Counter(r["reasons"] for r in records)),
        "families_with_uncovered_children_by_reason": dict(Counter(
            r["reasons"] for r in records if r["uncovered_children"])),
        "families_without_2018_children": [r["hs6"] for r in records if not r["valid_2018_children"]],
        "unresolved_policy_components": missing,
        "policy_dates_and_origins": {k: sorted(v) for k, v in policies.items()},
        "records": records,
        "interpretation": "Uncovered is not a clean control, cross-year mapping, or causal identification.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, ensure_ascii=False, indent=2))
