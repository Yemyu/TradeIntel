"""Protocol 0050: metadata-only HTS8 inventory, no trade outcomes."""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from build_hts6_mapping import read_annual_concordance
from build_control_eligibility import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def continuous(interval):
    if interval.count("→") != 1:
        return False
    start, end = interval.split("→")
    def date(value):
        match = re.fullmatch(r"(\d{2})/(\d{4})", value)
        return (int(match[2]), int(match[1])) if match else None
    left = (2006, 12) if start == "Prior to 2007" else date(start)
    right = (9999, 12) if end == "Current" else date(end)
    return left is not None and right is not None and left <= (2016, 1) and right >= (2018, 5)


def inventory():
    annual = {year: read_annual_concordance(year) for year in (2016, 2017, 2018)}
    groups = {year: defaultdict(set) for year in annual}
    for year, rows in annual.items():
        for code in rows:
            groups[year][code[:8]].add(code)
    policy_path = ROOT / "data/processed/causal/policy_exposure_hs6.csv"
    list_path = ROOT / "data/processed/policy/section301_list1_products.csv"
    history_path = ROOT / "data/processed/causal/hts_history_mapping.csv"
    policies = defaultdict(set)
    with policy_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            policies[row["hs6_2017"]].add(row["policy_id"])
    with list_path.open(newline="") as handle:
        list1 = {row["canonical_hts8"].replace(".", "") for row in csv.DictReader(handle)}
    with history_path.open(newline="") as handle:
        history = {row["source_hts10"]: row["historical_intervals"] for row in csv.DictReader(handle) if row["source_year"] == "2018"}
    records, exclusions = [], []
    counts = defaultdict(Counter)
    for hts8, children in sorted(groups[2018].items()):
        if not any(annual[2018][code]["naics6"].startswith("333") for code in children):
            continue
        reason = None
        sectors = {annual[2018][code]["naics6"][:4] for code in children}
        if any(groups[year].get(hts8) != children for year in annual):
            reason = "child_set_change"
        elif any(annual[year][code] != annual[2018][code] for year in annual for code in children):
            reason = "metadata_change"
        elif len(sectors) != 1 or not next(iter(sectors)).startswith("333"):
            reason = "industry_ambiguous"
        elif not all(continuous(history.get(code, "")) for code in children):
            reason = "history_requires_review"
        if reason:
            exclusions.append(dict(hts8=hts8, reason=reason))
            continue
        sector = next(iter(sectors))
        policy = policies[hts8[:6]]
        role = "policy_excluded"
        if hts8 in list1 and not (policy - {"us_301_list1_2018"}):
            role = "treated"
        elif not policy and hts8 not in list1:
            role = "control"
        counts[sector][role] += 1
        records.append(dict(hts8=hts8, naics4=sector, role=role, children=sorted(children), policies=sorted(policy)))
    sources = [policy_path, list_path, history_path, ROOT / "docs/decisions/0050-hts8-research-route.zh-CN.md"]
    sources += [ROOT / f"data/raw/policy/census-import-concordance-{year}.xls" for year in annual]
    return dict(scope="metadata candidates only; not adopted controls", source_sha256={str(p.relative_to(ROOT)):sha256_file(p) for p in sources},
                sector_counts=dict(counts), exclusion_counts=dict(Counter(x['reason'] for x in exclusions)), records=records, exclusions=exclusions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory()
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result["sector_counts"], ensure_ascii=False))
