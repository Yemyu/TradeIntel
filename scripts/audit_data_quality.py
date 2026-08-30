"""Audit the verified policy and trade outputs before downstream AI use.

The audit separates blocking failures from review findings.  It also creates
small reference tables for stable origin identities and policy-code coverage.
No source row is silently dropped or rewritten.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT = PROJECT_ROOT / "data/processed/policy/section301_list1_event.csv"
DEFAULT_PRODUCTS = PROJECT_ROOT / "data/processed/policy/section301_list1_products.csv"
DEFAULT_MANIFEST = PROJECT_ROOT / "data/processed/trade/source_manifest.csv"
DEFAULT_PANEL = PROJECT_ROOT / "data/processed/trade/trade_import_monthly.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data/processed/quality"

CENSUS_COUNTRY_REFERENCE = (
    "https://www.census.gov/foreign-trade/schedules/c/countrycode.html"
)
USITC_HTS_ARCHIVE = "https://hts.usitc.gov/download/archive"
EXPECTED_POLICY_COUNT = 818
EXPECTED_START_MONTH = (2016, 1)
EXPECTED_END_MONTH = (2019, 12)


class QualityAuditError(RuntimeError):
    """Raised when an audit cannot read its declared inputs."""


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    dimension: str
    severity: str
    status: str
    summary: str
    metrics: dict[str, object]


def month_range(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    year, month = start
    result: list[tuple[int, int]] = []
    while (year, month) <= end:
        result.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def month_label(value: tuple[int, int]) -> str:
    return f"{value[0]:04d}-{value[1]:02d}"


def normalise_hts8(value: str) -> str:
    return value.replace(".", "").strip()


def valid_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return list(reader.fieldnames or []), list(reader)
    except OSError as exc:
        raise QualityAuditError(f"Could not read {path}: {exc}") from exc


def require_fields(path: Path, fields: Iterable[str], required: set[str]) -> None:
    missing = sorted(required - set(fields))
    if missing:
        raise QualityAuditError(f"{path} is missing required fields: {missing}")


def make_rule(
    rule_id: str,
    dimension: str,
    severity: str,
    passed: bool,
    summary: str,
    metrics: dict[str, object],
    *,
    review_when_failed: bool = False,
) -> RuleResult:
    if passed:
        status = "pass"
    elif review_when_failed:
        status = "review"
    else:
        status = "fail"
    return RuleResult(rule_id, dimension, severity, status, summary, metrics)


def mysql_snapshot(login_path: str, database: str) -> tuple[dict[str, int], str | None]:
    sql = (
        "SELECT COUNT(*) FROM policy_event;\n"
        "SELECT COUNT(*) FROM policy_product;\n"
        "SELECT COUNT(*), COALESCE(SUM(import_value_consumption_usd), 0), "
        "MIN(year * 100 + month), MAX(year * 100 + month), "
        "COUNT(DISTINCT year * 100 + month) FROM trade_monthly;\n"
    )
    result = subprocess.run(
        [
            "mysql",
            f"--login-path={login_path}",
            "--batch",
            "--raw",
            "--skip-column-names",
            database,
        ],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return {}, result.stderr.strip() or result.stdout.strip()
    lines = [line.split("\t") for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 3 or len(lines[2]) != 5:
        return {}, f"Unexpected MySQL verification output: {result.stdout!r}"
    try:
        return {
            "policy_event_rows": int(lines[0][0]),
            "policy_product_rows": int(lines[1][0]),
            "trade_rows": int(lines[2][0]),
            "trade_value_usd": int(lines[2][1]),
            "first_yyyymm": int(lines[2][2]),
            "last_yyyymm": int(lines[2][3]),
            "month_count": int(lines[2][4]),
        }, None
    except ValueError as exc:
        return {}, f"Invalid numeric MySQL verification output: {exc}"


def audit_data_quality(
    *,
    event_path: Path = DEFAULT_EVENT,
    products_path: Path = DEFAULT_PRODUCTS,
    manifest_path: Path = DEFAULT_MANIFEST,
    panel_path: Path = DEFAULT_PANEL,
    expected_policy_count: int = EXPECTED_POLICY_COUNT,
    expected_months: list[tuple[int, int]] | None = None,
    mysql_login_path: str | None = None,
    mysql_database: str = "tradeintel",
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Return report, origin dimension, policy-origin mapping, and HTS coverage."""

    expected_months = expected_months or month_range(
        EXPECTED_START_MONTH, EXPECTED_END_MONTH
    )
    expected_month_set = set(expected_months)
    rules: list[RuleResult] = []

    event_fields, event_rows = read_csv(event_path)
    require_fields(
        event_path,
        event_fields,
        {
            "policy_id",
            "policy_name",
            "target_origin",
            "announcement_date",
            "effective_date",
            "additional_rate",
            "source_url",
        },
    )
    event_errors: list[str] = []
    event = event_rows[0] if len(event_rows) == 1 else {}
    if len(event_rows) != 1:
        event_errors.append(f"expected one event, found {len(event_rows)}")
    if event:
        for field in ("policy_id", "policy_name", "target_origin", "source_url"):
            if not event[field].strip():
                event_errors.append(f"empty {field}")
        try:
            announcement = date.fromisoformat(event["announcement_date"])
            effective = date.fromisoformat(event["effective_date"])
            if effective < announcement:
                event_errors.append("effective date precedes announcement date")
        except ValueError:
            event_errors.append("invalid policy date")
        try:
            if Decimal(event["additional_rate"]) < 0:
                event_errors.append("negative policy rate")
        except InvalidOperation:
            event_errors.append("invalid policy rate")
    rules.append(
        make_rule(
            "POLICY-001",
            "政策事件",
            "critical",
            not event_errors,
            "政策事件的身份、日期、税率和来源有效。",
            {"row_count": len(event_rows), "errors": event_errors},
        )
    )

    product_fields, product_rows = read_csv(products_path)
    require_fields(
        products_path,
        product_fields,
        {
            "policy_id",
            "raw_hts",
            "canonical_hts8",
            "amended",
            "amendment_source_url",
        },
    )
    policy_codes = [normalise_hts8(row["canonical_hts8"]) for row in product_rows]
    invalid_policy_codes = sorted(
        {code for code in policy_codes if len(code) != 8 or not code.isdigit()}
    )
    duplicate_policy_codes = len(policy_codes) - len(set(policy_codes))
    rules.append(
        make_rule(
            "HTS-001",
            "政策商品身份",
            "critical",
            len(product_rows) == expected_policy_count
            and not invalid_policy_codes
            and duplicate_policy_codes == 0,
            "政策商品数量符合预期，8 位 HTS 身份合法且唯一。",
            {
                "row_count": len(product_rows),
                "expected_row_count": expected_policy_count,
                "unique_code_count": len(set(policy_codes)),
                "invalid_codes": invalid_policy_codes,
                "duplicate_code_count": duplicate_policy_codes,
            },
        )
    )
    correction_rows = [row for row in product_rows if row["raw_hts"].strip() == "9033.00"]
    correction_valid = len(correction_rows) == 1
    if correction_rows:
        correction = correction_rows[0]
        correction_valid = correction_valid and (
            correction["canonical_hts8"].strip() == "9033.00.90"
            and correction["amended"].strip().lower() == "true"
            and bool(correction["amendment_source_url"].strip())
        )
    rules.append(
        make_rule(
            "HTS-002",
            "官方修正",
            "critical",
            correction_valid,
            "9033.00 的官方修正已经明确记录并且可以追溯。",
            {
                "raw_exception_count": len(correction_rows),
                "expected_canonical_hts8": "9033.00.90",
            },
        )
    )

    manifest_fields, manifest_rows = read_csv(manifest_path)
    require_fields(
        manifest_path,
        manifest_fields,
        {
            "year",
            "month",
            "source_url",
            "source_file_name",
            "source_sha256",
            "source_archive_bytes",
            "source_retrieved_at_utc",
            "status",
            "raw_archive_retained_after_processing",
        },
    )
    manifest_by_month: dict[tuple[int, int], dict[str, str]] = {}
    manifest_errors: list[str] = []
    for row in manifest_rows:
        try:
            key = (int(row["year"]), int(row["month"]))
            archive_bytes = int(row["source_archive_bytes"])
        except ValueError:
            manifest_errors.append("invalid month or archive size")
            continue
        if key in manifest_by_month:
            manifest_errors.append(f"duplicate month {month_label(key)}")
        manifest_by_month[key] = row
        if (
            not row["source_url"].strip()
            or not row["source_file_name"].strip()
            or not valid_sha256(row["source_sha256"].strip())
            or archive_bytes <= 0
            or not row["source_retrieved_at_utc"].strip()
            or row["status"].strip() != "processed"
            or row["raw_archive_retained_after_processing"].strip().lower()
            not in {"false", "0", "no"}
        ):
            manifest_errors.append(f"invalid lineage metadata for {month_label(key)}")

    panel_fields: list[str]
    try:
        panel_handle = panel_path.open(newline="", encoding="utf-8")
    except OSError as exc:
        raise QualityAuditError(f"Could not read {panel_path}: {exc}") from exc
    with panel_handle:
        reader = csv.DictReader(panel_handle)
        panel_fields = list(reader.fieldnames or [])
        require_fields(
            panel_path,
            panel_fields,
            {
                "year",
                "month",
                "origin_code",
                "origin_name",
                "hts10",
                "hts8",
                "import_value_consumption_usd",
                "detail_row_count",
                "source_url",
                "source_file_name",
                "source_sha256",
            },
        )
        seen_keys: set[tuple[int, int, str, str]] = set()
        duplicate_count = 0
        observed_months: set[tuple[int, int]] = set()
        month_sources: defaultdict[tuple[int, int], set[tuple[str, str, str]]] = defaultdict(set)
        origin_names: defaultdict[str, defaultdict[str, set[tuple[int, int]]]] = defaultdict(
            lambda: defaultdict(set)
        )
        coverage: dict[str, dict[str, object]] = {
            code: {"rows": 0, "months": set(), "value": 0}
            for code in set(policy_codes)
        }
        panel_rows = 0
        total_value = 0
        invalid_month_count = 0
        invalid_hts10_count = 0
        invalid_hts8_count = 0
        hts_prefix_mismatch_count = 0
        trade_codes_not_in_policy: set[str] = set()
        invalid_origin_code_count = 0
        empty_origin_name_count = 0
        unknown_origin_name_count = 0
        invalid_value_count = 0
        negative_value_count = 0
        zero_value_count = 0
        nonpositive_detail_row_count = 0
        invalid_hash_count = 0

        for row in reader:
            panel_rows += 1
            try:
                year, month = int(row["year"]), int(row["month"])
            except ValueError:
                invalid_month_count += 1
                continue
            key_month = (year, month)
            if month < 1 or month > 12:
                invalid_month_count += 1
            observed_months.add(key_month)
            origin_code = row["origin_code"].strip()
            origin_name = row["origin_name"].strip()
            hts10 = row["hts10"].strip()
            hts8 = normalise_hts8(row["hts8"])
            key = (year, month, origin_code, hts10)
            if key in seen_keys:
                duplicate_count += 1
            seen_keys.add(key)
            if len(hts10) != 10 or not hts10.isdigit():
                invalid_hts10_count += 1
            if len(hts8) != 8 or not hts8.isdigit():
                invalid_hts8_count += 1
            if hts10[:8] != hts8:
                hts_prefix_mismatch_count += 1
            if hts8 not in coverage:
                trade_codes_not_in_policy.add(hts8)
            if len(origin_code) != 4 or not origin_code.isdigit():
                invalid_origin_code_count += 1
            if not origin_name:
                empty_origin_name_count += 1
            if origin_name == "<unknown>":
                unknown_origin_name_count += 1
            origin_names[origin_code][origin_name].add(key_month)
            try:
                value = int(row["import_value_consumption_usd"])
                detail_rows = int(row["detail_row_count"])
            except ValueError:
                invalid_value_count += 1
                continue
            total_value += value
            if value < 0:
                negative_value_count += 1
            if value == 0:
                zero_value_count += 1
            if detail_rows <= 0:
                nonpositive_detail_row_count += 1
            if hts8 in coverage:
                item = coverage[hts8]
                item["rows"] = int(item["rows"]) + 1
                item["months"].add(key_month)  # type: ignore[union-attr]
                item["value"] = int(item["value"]) + value
            source_hash = row["source_sha256"].strip()
            if not valid_sha256(source_hash):
                invalid_hash_count += 1
            month_sources[key_month].add(
                (row["source_url"], row["source_file_name"], source_hash)
            )

    manifest_months = set(manifest_by_month)
    rules.append(
        make_rule(
            "TIME-001",
            "月份覆盖",
            "critical",
            not invalid_month_count
            and observed_months == expected_month_set
            and manifest_months == expected_month_set,
            "贸易面板和来源清单覆盖声明的连续月份。",
            {
                "expected_month_count": len(expected_months),
                "panel_month_count": len(observed_months),
                "manifest_month_count": len(manifest_months),
                "missing_panel_months": [
                    month_label(value) for value in sorted(expected_month_set - observed_months)
                ],
                "unexpected_panel_months": [
                    month_label(value) for value in sorted(observed_months - expected_month_set)
                ],
                "invalid_month_rows": invalid_month_count,
            },
        )
    )
    rules.append(
        make_rule(
            "KEY-001",
            "贸易数据粒度",
            "critical",
            duplicate_count == 0,
            "月份 × 原产国代码 × HTS10 业务键唯一。",
            {
                "row_count": panel_rows,
                "unique_key_count": len(seen_keys),
                "duplicate_row_count": duplicate_count,
            },
        )
    )
    code_errors = (
        invalid_hts10_count
        + invalid_hts8_count
        + hts_prefix_mismatch_count
        + len(trade_codes_not_in_policy)
    )
    rules.append(
        make_rule(
            "CODE-001",
            "贸易商品代码",
            "critical",
            code_errors == 0,
            "贸易 HTS10/HTS8 格式合法、前缀一致，并且属于政策范围。",
            {
                "invalid_hts10_rows": invalid_hts10_count,
                "invalid_hts8_rows": invalid_hts8_count,
                "hts10_hts8_prefix_mismatches": hts_prefix_mismatch_count,
                "trade_codes_not_in_policy": sorted(trade_codes_not_in_policy),
            },
        )
    )
    rules.append(
        make_rule(
            "VALUE-001",
            "贸易金额",
            "critical",
            invalid_value_count == 0
            and negative_value_count == 0
            and nonpositive_detail_row_count == 0,
            "贸易金额是非负整数，并且存在对应的明细记录。",
            {
                "invalid_numeric_rows": invalid_value_count,
                "negative_value_rows": negative_value_count,
                "zero_value_rows": zero_value_count,
                "nonpositive_detail_row_count_rows": nonpositive_detail_row_count,
                "total_value_usd": total_value,
            },
        )
    )
    origin_identity_errors = (
        invalid_origin_code_count + empty_origin_name_count + unknown_origin_name_count
    )
    rules.append(
        make_rule(
            "ORIGIN-001",
            "原产国身份",
            "critical",
            origin_identity_errors == 0,
            "每条贸易记录都有合法的 4 位 Census 原产国代码和名称。",
            {
                "invalid_origin_code_rows": invalid_origin_code_count,
                "empty_origin_name_rows": empty_origin_name_count,
                "unknown_origin_name_rows": unknown_origin_name_count,
            },
        )
    )

    origin_dimension: list[dict[str, object]] = []
    variant_codes: list[dict[str, object]] = []
    for origin_code, names in sorted(origin_names.items()):
        all_months = {value for values in names.values() for value in values}
        latest_month = max(all_months)
        latest_names = sorted(name for name, values in names.items() if latest_month in values)
        canonical_name = latest_names[0]
        status = "review_name_change" if len(names) > 1 or len(latest_names) > 1 else "pass"
        row = {
            "origin_code": origin_code,
            "canonical_origin_name": canonical_name,
            "observed_origin_names": " | ".join(sorted(names)),
            "first_observed_month": month_label(min(all_months)),
            "last_observed_month": month_label(max(all_months)),
            "name_variant_count": len(names),
            "canonical_name_method": "latest_observed_name",
            "quality_status": status,
            "reference_url": CENSUS_COUNTRY_REFERENCE,
        }
        origin_dimension.append(row)
        if status != "pass":
            variant_codes.append(
                {
                    "origin_code": origin_code,
                    "canonical_origin_name": canonical_name,
                    "observed_origin_names": sorted(names),
                }
            )
    rules.append(
        make_rule(
            "ORIGIN-002",
            "原产国名称历史",
            "review",
            not variant_codes,
            "稳定国家代码存在历史名称变化；分析必须按代码聚合。",
            {"variant_code_count": len(variant_codes), "variant_codes": variant_codes},
            review_when_failed=True,
        )
    )

    target_name = event.get("target_origin", "").strip().upper()
    matching_origin_codes = sorted(
        origin_code
        for origin_code, names in origin_names.items()
        if any(name.upper() == target_name for name in names)
    )
    canonical_by_code = {
        str(row["origin_code"]): str(row["canonical_origin_name"])
        for row in origin_dimension
    }
    mapping_valid = bool(event) and len(matching_origin_codes) == 1
    policy_origin_mapping: list[dict[str, object]] = []
    if mapping_valid:
        origin_code = matching_origin_codes[0]
        policy_origin_mapping.append(
            {
                "policy_id": event["policy_id"],
                "policy_target_origin_name": event["target_origin"],
                "origin_code": origin_code,
                "canonical_origin_name": canonical_by_code[origin_code],
                "mapping_method": "exact_observed_name_to_stable_census_code",
                "quality_status": "pass",
                "reference_url": CENSUS_COUNTRY_REFERENCE,
            }
        )
    rules.append(
        make_rule(
            "POLICY-ORIGIN-001",
            "政策—原产国映射",
            "critical",
            mapping_valid,
            "政策目标国唯一映射到一个稳定的 Census 原产国代码。",
            {
                "policy_target_origin_name": event.get("target_origin"),
                "matching_origin_codes": matching_origin_codes,
            },
        )
    )

    source_mismatches: list[str] = []
    for key, source_values in month_sources.items():
        manifest_row = manifest_by_month.get(key)
        if manifest_row is None:
            source_mismatches.append(f"{month_label(key)} missing from manifest")
            continue
        expected_source = {
            (
                manifest_row["source_url"],
                manifest_row["source_file_name"],
                manifest_row["source_sha256"],
            )
        }
        if source_values != expected_source:
            source_mismatches.append(f"{month_label(key)} source metadata differs")
    lineage_valid = (
        not manifest_errors
        and not source_mismatches
        and invalid_hash_count == 0
        and set(month_sources) == manifest_months
    )
    rules.append(
        make_rule(
            "SOURCE-001",
            "来源追溯",
            "critical",
            lineage_valid,
            "每个月只有一个合法来源指纹，并且与来源清单一致。",
            {
                "manifest_errors": manifest_errors,
                "panel_invalid_hash_rows": invalid_hash_count,
                "source_mismatches": source_mismatches,
            },
        )
    )

    hts_coverage: list[dict[str, object]] = []
    missing_policy_codes: list[str] = []
    product_by_code = {
        normalise_hts8(row["canonical_hts8"]): row for row in product_rows
    }
    for code in sorted(set(policy_codes)):
        item = coverage[code]
        months = sorted(item["months"])  # type: ignore[arg-type]
        observed = bool(item["rows"])
        if not observed:
            missing_policy_codes.append(code)
        hts_coverage.append(
            {
                "policy_id": product_by_code[code]["policy_id"],
                "canonical_hts8": code,
                "observed_trade_row_count": item["rows"],
                "observed_month_count": len(months),
                "first_observed_month": month_label(months[0]) if months else "",
                "last_observed_month": month_label(months[-1]) if months else "",
                "total_import_value_consumption_usd": item["value"],
                "coverage_status": "observed" if observed else "not_observed_review",
                "policy_source_url": product_by_code[code]["source_url"],
                "classification_reference_url": USITC_HTS_ARCHIVE,
            }
        )
    rules.append(
        make_rule(
            "COVERAGE-001",
            "政策商品覆盖",
            "review",
            not missing_policy_codes,
            "没有贸易记录的政策 HTS8 需要复核，不能静默补零。",
            {
                "policy_code_count": len(set(policy_codes)),
                "observed_policy_code_count": len(set(policy_codes)) - len(missing_policy_codes),
                "not_observed_policy_codes": missing_policy_codes,
            },
            review_when_failed=True,
        )
    )

    csv_snapshot = {
        "policy_event_rows": len(event_rows),
        "policy_product_rows": len(product_rows),
        "trade_rows": panel_rows,
        "trade_value_usd": total_value,
        "first_yyyymm": min(year * 100 + month for year, month in observed_months),
        "last_yyyymm": max(year * 100 + month for year, month in observed_months),
        "month_count": len(observed_months),
    }
    mysql_data: dict[str, int] | None = None
    if mysql_login_path:
        mysql_data, mysql_error = mysql_snapshot(mysql_login_path, mysql_database)
        mysql_matches = mysql_error is None and mysql_data == csv_snapshot
        rules.append(
            make_rule(
                "DB-001",
                "CSV 与 MySQL 对账",
                "critical",
                mysql_matches,
                "MySQL 的行数、金额总额和月份覆盖与 CSV 一致。",
                {
                    "csv": csv_snapshot,
                    "mysql": mysql_data,
                    "error": mysql_error,
                },
            )
        )
    else:
        rules.append(
            RuleResult(
                "DB-001",
                "CSV 与 MySQL 对账",
                "optional",
                "not_run",
                "本次运行没有请求 MySQL 对账。",
                {"csv": csv_snapshot},
            )
        )

    failed_rules = [rule.rule_id for rule in rules if rule.status == "fail"]
    review_rules = [rule.rule_id for rule in rules if rule.status == "review"]
    overall_status = (
        "blocked" if failed_rules else "pass_with_review" if review_rules else "pass"
    )
    report: dict[str, object] = {
        "audit_version": 1,
        "overall_status": overall_status,
        "summary": {
            "failed_rule_count": len(failed_rules),
            "review_rule_count": len(review_rules),
            "failed_rules": failed_rules,
            "review_rules": review_rules,
            "policy_event_rows": len(event_rows),
            "policy_product_rows": len(product_rows),
            "trade_rows": panel_rows,
            "trade_value_usd": total_value,
            "month_count": len(observed_months),
            "origin_count": len(origin_dimension),
            "policy_codes_without_trade": missing_policy_codes,
            "origin_codes_with_name_changes": [
                item["origin_code"] for item in variant_codes
            ],
        },
        "input_fingerprints": {
            "policy_event_sha256": sha256_file(event_path),
            "policy_products_sha256": sha256_file(products_path),
            "source_manifest_sha256": sha256_file(manifest_path),
            "trade_panel_sha256": sha256_file(panel_path),
        },
        "rules": [asdict(rule) for rule in rules],
        "adoption_decisions": {
            "aggregate_descriptive_analysis": (
                "allowed_with_coverage_disclosure"
                if overall_status != "blocked"
                else "blocked"
            ),
            "origin_level_analysis": (
                "allowed_only_when_grouped_by_origin_code"
                if overall_status != "blocked"
                else "blocked"
            ),
            "unobserved_hts8_product_analysis": "blocked_pending_review",
            "causal_policy_claims": "blocked_pending_exclusions_crosswalks_and_design_checks",
        },
        "official_references": {
            "census_schedule_c_country_codes": CENSUS_COUNTRY_REFERENCE,
            "usitc_hts_archive": USITC_HTS_ARCHIVE,
        },
    }
    return report, origin_dimension, policy_origin_mapping, hts_coverage


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise QualityAuditError(f"Cannot write an empty artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_report_markdown(path: Path, report: dict[str, object]) -> None:
    summary = report["summary"]
    assert isinstance(summary, dict)
    rules = report["rules"]
    assert isinstance(rules, list)
    decisions = report["adoption_decisions"]
    assert isinstance(decisions, dict)
    lines = [
        "# TradeShock AI 数据质量报告",
        "",
        f"- 总体状态：`{report['overall_status']}`",
        f"- 政策事件：{summary['policy_event_rows']} 条",
        f"- 政策商品：{summary['policy_product_rows']} 条",
        f"- 贸易记录：{summary['trade_rows']:,} 条",
        f"- 月份：{summary['month_count']} 个月",
        f"- 原产国代码：{summary['origin_count']} 个",
        "",
        "## 规则结果",
        "",
        "| 规则 | 维度 | 严重性 | 状态 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for item in rules:
        lines.append(
            f"| {item['rule_id']} | {item['dimension']} | {item['severity']} | "
            f"{item['status']} | {item['summary']} |"
        )
    lines.extend(
        [
            "",
            "## 需要人工复核",
            "",
            "- 未观察到贸易记录的政策 HTS8："
            + (", ".join(summary["policy_codes_without_trade"]) or "无"),
            "- 存在历史名称变化的原产国代码："
            + (", ".join(summary["origin_codes_with_name_changes"]) or "无"),
            "",
            "## 数据采纳决定",
            "",
        ]
    )
    for name, decision in decisions.items():
        lines.append(f"- `{name}`：`{decision}`")
    lines.extend(
        [
            "",
            "## 解释",
            "",
            "`pass_with_review` 不是失败。它表示结构、主键、金额和来源检查通过，"
            "但仍有不能自动猜测的业务问题。分析可以按上面的采纳条件继续，"
            "相关限制必须进入后续报告和 AI 证据包。",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)


def write_outputs(
    output_dir: Path,
    report: dict[str, object],
    origin_dimension: list[dict[str, object]],
    policy_origin_mapping: list[dict[str, object]],
    hts_coverage: list[dict[str, object]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json = output_dir / "data_quality_report.json"
    temporary = report_json.with_suffix(".json.part")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(report_json)
    write_report_markdown(output_dir / "data_quality_report.md", report)
    write_csv(output_dir / "origin_dimension.csv", origin_dimension)
    write_csv(output_dir / "policy_origin_mapping.csv", policy_origin_mapping)
    write_csv(output_dir / "hts8_coverage.csv", hts_coverage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mysql-login-path")
    parser.add_argument("--mysql-database", default="tradeintel")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report, origins, policy_origins, coverage = audit_data_quality(
            event_path=args.event,
            products_path=args.products,
            manifest_path=args.manifest,
            panel_path=args.panel,
            mysql_login_path=args.mysql_login_path,
            mysql_database=args.mysql_database,
        )
        write_outputs(args.output_dir, report, origins, policy_origins, coverage)
    except QualityAuditError as exc:
        print(f"Data quality audit failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Data quality audit: {report['overall_status']} "
        f"({report['summary']['trade_rows']} trade rows)"
    )
    return 1 if report["overall_status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
