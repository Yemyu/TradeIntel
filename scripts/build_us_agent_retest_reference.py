"""Independent processed-CSV reference; deliberately imports no product modules."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

CODES = ("1201", "1507", "4001", "1801", "2204", "8101")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def aggregate(path, flow, *, expected=None):
    cells = {(code, partner): {"matched": 0, "observed": 0, "sum": 0}
             for code in CODES for partner in ("all", "china")}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            code = row["hts10" if flow == "import" else "scheduleb10"][:4]
            if code not in CODES:
                continue
            if expected is not None:
                if (row.get("year") != str(expected["year"]) or row.get("month") != str(expected["month"])
                        or row.get("source_sha256") != expected["source_sha256"]
                        or flow == "import" and row.get("source_url") != expected["source_url"]):
                    raise ValueError("CSV row month/source identity mismatch")
                if flow == "export":
                    components = [(row["domestic_observed"], row["domestic_export_fas_usd"]),
                                  (row["foreign_observed"], row["foreign_reexport_fas_usd"])]
                    if any(flag not in ("0", "1") for flag, _ in components):
                        raise ValueError("Invalid observation flag")
                    if any(flag == "1" for flag, _ in components):
                        if sum(int(value) if flag == "1" else 0 for flag, value in components) != int(row["total_export_fas_usd"]):
                            raise ValueError("Export total does not reconcile")
                    elif row["total_export_fas_usd"] not in ("", "0"):
                        raise ValueError("Unobserved export total must remain unknown")
            for partner in ("all", "china"):
                if flow == "export" and partner == "china" and row["partner_code"] != "5700":
                    continue
                cell = cells[code, partner]
                cell["matched"] += 1
                if flow == "import":
                    prefix = "all_origin" if partner == "all" else "china"
                    flag = row[prefix + "_observed"]
                    value = row[prefix + "_import_value_consumption_usd"]
                    observed = flag == "1"
                    if flag not in ("0", "1"):
                        raise ValueError("Invalid observation flag")
                else:
                    flags = (row["domestic_observed"], row["foreign_observed"])
                    if any(flag not in ("0", "1") for flag in flags):
                        raise ValueError("Invalid observation flag")
                    observed = "1" in flags
                    value = row["total_export_fas_usd"]
                if observed:
                    cell["observed"] += 1
                    cell["sum"] += int(value)
    return {code: {partner: {
        "value_usd": cells[code, partner]["sum"] if cells[code, partner]["observed"] else None,
        "matched_rows": cells[code, partner]["matched"],
        "observed_rows": cells[code, partner]["observed"],
        "unobserved_rows": cells[code, partner]["matched"] - cells[code, partner]["observed"],
    } for partner in ("all", "china")} for code in CODES}


def build_reference(root, *, coverage_profile="core12"):
    if coverage_profile not in {"core12", "manifest_available"}:
        raise ValueError("Unknown reference coverage profile")
    root = root.resolve()
    bundle_path = root / "BUNDLE_MANIFEST.json"
    bundle = json.loads(bundle_path.read_text())
    listed = {item["path"]: item for item in bundle["files"]}
    result = {"kind": "independent-csv-reference-v1", "dataset_versions": bundle["dataset_versions"],
              "bundle_sha256": digest(bundle_path), "files": {}, "months": {},
              "coverage_profile": coverage_profile, "registered_months": {}}

    def verify(relative, expected=None):
        path = root / relative
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError("Unsafe reference path")
        entry = listed.get(relative)
        actual = digest(path)
        if not entry or entry["sha256"] != actual or entry["bytes"] != path.stat().st_size:
            raise ValueError("Bundle file mismatch: " + relative)
        if expected is not None and expected != actual:
            raise ValueError("Processed manifest mismatch: " + relative)
        result["files"][relative] = actual
        return path

    classification = json.loads(verify("data/processed/trade_classification/manifest.json").read_text())
    for flow in ("import", "export"):
        if classification["dataset_versions"].get(flow) != bundle["dataset_versions"].get(flow):
            raise ValueError("Classification dataset version mismatch")
    if classification.get("catalog_version") != bundle["dataset_versions"].get("classification"):
        raise ValueError("Classification catalog version mismatch")
    for flow, directory in (("import", "trade_hts10"), ("export", "trade_scheduleb10")):
        manifest = json.loads(verify(f"data/processed/{directory}/manifest.json").read_text())
        if flow == "export" and manifest["dataset_version"] != bundle["dataset_versions"][flow]:
            raise ValueError("Export dataset version mismatch")
        registered = set()
        for item in manifest["months"]:
            month = f'{item["year"]:04d}-{item["month"]:02d}'
            if not 1 <= item["month"] <= 12 or month in registered:
                raise ValueError("Invalid or duplicate processed month")
            registered.add(month)
            if coverage_profile == "core12" and not "2025-08" <= month <= "2026-07":
                continue
            if flow in result["months"].get(month, {}):
                raise ValueError("Duplicate processed month")
            relative = item["monthly_output" if flow == "import" else "processed_file"]
            path = verify(relative, item.get("processed_sha256"))
            result["months"].setdefault(month, {})[flow] = {
                "values": aggregate(path, flow, expected=item), "source_sha256": item["source_sha256"],
                "source_url": item.get("source_url"), "file": relative}
        result["registered_months"][flow] = sorted(registered)
    required_months = {f"2025-{month:02d}" for month in range(8, 13)} | {f"2026-{month:02d}" for month in range(1, 8)}
    if not required_months <= set(result["months"]) or any(
            set(result["months"][month]) != {"import", "export"} for month in required_months):
        raise ValueError("Required twelve-month coverage incomplete")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage-profile", choices=("core12", "manifest_available"), default="core12")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; refusing overwrite")
    reference = build_reference(args.data_root, coverage_profile=args.coverage_profile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(reference, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"months": len(reference["months"]), "verified_files": len(reference["files"]), "api_calls": 0}))


if __name__ == "__main__":
    main()
