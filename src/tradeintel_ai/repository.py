"""Read-only access to the verified TradeIntel evidence artifacts.

The AI layer deliberately reads declared files through this small repository
instead of accepting arbitrary SQL from a language model.  MySQL remains the
project's learning database; the default demo backend uses the already audited
CSV/JSON snapshots so a reviewer can run the tools without credentials.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class RepositoryError(RuntimeError):
    """Raised when a declared evidence artifact is missing or invalid."""


@dataclass(frozen=True)
class DataPaths:
    """The only files the MVP evidence tools are allowed to read."""

    root: Path

    @property
    def policy_event(self) -> Path:
        return self.root / "data/processed/policy/section301_list1_event.csv"

    @property
    def policy_products(self) -> Path:
        return self.root / "data/processed/policy/section301_list1_products.csv"

    @property
    def policy_exposure_hs6(self) -> Path:
        return self.root / "data/processed/causal/policy_exposure_hs6.csv"

    @property
    def policy_case_monthly(self) -> Path:
        return self.root / "data/processed/analysis/policy_case_monthly.csv"

    @property
    def statistical_baseline_summary(self) -> Path:
        return self.root / "data/processed/analysis/statistical_baseline_summary.json"

    @property
    def statistical_baseline_monthly(self) -> Path:
        return self.root / "data/processed/analysis/statistical_baseline_monthly.csv"

    @property
    def quality_report(self) -> Path:
        return self.root / "data/processed/quality/data_quality_report.json"

    @property
    def eligibility_report(self) -> Path:
        return self.root / "data/processed/causal/control_eligibility_report.json"

    @property
    def causal_design(self) -> Path:
        return self.root / "config/causal_control_design.json"

    @property
    def matching_v1_report(self) -> Path:
        return self.root / "data/processed/causal/matching_balance_report.json"

    @property
    def matching_v2_report(self) -> Path:
        return self.root / "data/processed/causal/matching_balance_report_v2.json"

    @property
    def matching_v3_report(self) -> Path:
        return self.root / "data/processed/causal/matching_balance_report_v3.json"

    @property
    def causal_panel(self) -> Path:
        return self.root / "data/processed/causal/causal_trade_hs6_monthly.csv"

    @property
    def causal_panel_manifest(self) -> Path:
        return self.root / "data/processed/causal/causal_trade_panel_manifest.json"


def default_paths() -> DataPaths:
    """Return paths for a checkout of this repository."""

    return DataPaths(Path(__file__).resolve().parents[2])


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise RepositoryError(f"Evidence file is missing: {path}")
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise RepositoryError(f"Could not read evidence file {path}: {exc}") from exc


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RepositoryError(f"Evidence file is missing: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryError(f"Could not read evidence JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RepositoryError(f"Evidence JSON must be an object: {path}")
    return value


def _month_key(value: str) -> tuple[int, int]:
    try:
        year_text, month_text = value.split("-", 1)
        year, month = int(year_text), int(month_text)
    except (ValueError, AttributeError) as exc:
        raise RepositoryError(f"Invalid month in evidence: {value!r}") from exc
    if year < 1900 or not 1 <= month <= 12:
        raise RepositoryError(f"Invalid month in evidence: {value!r}")
    return year, month


def _month_label(key: tuple[int, int]) -> str:
    return f"{key[0]:04d}-{key[1]:02d}"


def _parse_int(value: str, *, field: str, path: Path) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RepositoryError(f"Invalid integer {field} in {path}: {value!r}") from exc
    if parsed < 0:
        raise RepositoryError(f"Negative value {field} in {path}: {value!r}")
    return parsed


class EvidenceRepository:
    """Validated, read-only access to the project's evidence files."""

    def __init__(self, paths: DataPaths | None = None) -> None:
        self.paths = paths or default_paths()

    def file_source(self, path: Path, *, source_url: str | None = None) -> dict[str, str]:
        """Return a traceable local-file reference and optional official URL."""

        if not path.exists():
            raise RepositoryError(f"Evidence file is missing: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        reference: dict[str, str] = {
            "kind": "local_evidence_file",
            "path": str(path.relative_to(self.paths.root)),
            "sha256": digest,
        }
        if source_url:
            reference["url"] = source_url
        return reference

    def policy_event(self, policy_id: str) -> dict[str, str]:
        rows = _read_csv(self.paths.policy_event)
        matches = [row for row in rows if row.get("policy_id", "").strip() == policy_id]
        if len(matches) != 1:
            raise RepositoryError(
                f"Expected one policy event for {policy_id!r}, found {len(matches)}"
            )
        row = matches[0]
        required = {
            "policy_id",
            "policy_name",
            "target_origin",
            "announcement_date",
            "effective_date",
            "additional_rate",
            "source_url",
        }
        if not required.issubset(row):
            raise RepositoryError(f"Policy event is missing fields: {sorted(required - set(row))}")
        return row

    def policy_products(self, policy_id: str) -> set[str]:
        rows = _read_csv(self.paths.policy_products)
        products = {
            row.get("canonical_hts8", "").replace(".", "").strip()
            for row in rows
            if row.get("policy_id", "").strip() == policy_id
        }
        if not products or any(len(code) != 8 or not code.isdigit() for code in products):
            raise RepositoryError(f"Policy product table is invalid for {policy_id!r}")
        return products

    def policy_hs6(self, policy_id: str) -> set[str]:
        """Return the conservative HS6 exposure universe for a policy."""

        rows = _read_csv(self.paths.policy_exposure_hs6)
        codes = {
            row.get("hs6_2017", "").strip()
            for row in rows
            if row.get("policy_id", "").strip() == policy_id
        }
        if not codes or any(len(code) != 6 or not code.isdigit() for code in codes):
            raise RepositoryError(f"Policy HS6 exposure table is invalid for {policy_id!r}")
        return codes

    def policy_case_monthly(self) -> dict[tuple[int, int], dict[str, object]]:
        rows = _read_csv(self.paths.policy_case_monthly)
        result: dict[tuple[int, int], dict[str, object]] = {}
        for row in rows:
            key = (int(row["year"]), int(row["month"]))
            if key in result:
                raise RepositoryError(f"Duplicate policy monthly key: {_month_label(key)}")
            target = _parse_int(
                row["target_import_value_consumption_usd"],
                field="target_import_value_consumption_usd",
                path=self.paths.policy_case_monthly,
            )
            others = _parse_int(
                row["other_origins_import_value_consumption_usd"],
                field="other_origins_import_value_consumption_usd",
                path=self.paths.policy_case_monthly,
            )
            all_origins = _parse_int(
                row["all_origins_import_value_consumption_usd"],
                field="all_origins_import_value_consumption_usd",
                path=self.paths.policy_case_monthly,
            )
            if target + others != all_origins:
                raise RepositoryError(f"Inconsistent policy monthly totals at {_month_label(key)}")
            result[key] = {
                "year": key[0],
                "month": key[1],
                "month_label": row.get("month_label", _month_label(key)),
                "period": row.get("period", ""),
                "target": target,
                "other_origins": others,
                "all_origins": all_origins,
                "target_share": float(row.get("target_share_of_all_origins") or 0.0),
                "unique_origin_count": int(row.get("unique_origin_count") or 0),
                "unique_policy_hts8_count": int(row.get("unique_policy_hts8_count") or 0),
            }
        if len(result) != 48:
            raise RepositoryError(f"Expected 48 policy monthly rows, found {len(result)}")
        return result

    def statistical_baseline(self) -> dict[str, object]:
        return _read_json(self.paths.statistical_baseline_summary)

    def quality_report(self) -> dict[str, object]:
        return _read_json(self.paths.quality_report)

    def eligibility_report(self) -> dict[str, object]:
        return _read_json(self.paths.eligibility_report)

    def causal_design(self) -> dict[str, object]:
        return _read_json(self.paths.causal_design)

    def matching_reports(self) -> dict[str, dict[str, object]]:
        return {
            "v1": _read_json(self.paths.matching_v1_report),
            "v2": _read_json(self.paths.matching_v2_report),
            "v3": _read_json(self.paths.matching_v3_report),
        }

    def source_manifest(self) -> dict[tuple[int, int], dict[str, object]]:
        manifest = _read_json(self.paths.causal_panel_manifest)
        months = manifest.get("months")
        if not isinstance(months, list):
            raise RepositoryError("Causal panel manifest has no months list")
        result: dict[tuple[int, int], dict[str, object]] = {}
        for item in months:
            if not isinstance(item, dict):
                raise RepositoryError("Causal panel manifest contains a non-object month")
            key = (int(item["year"]), int(item["month"]))
            result[key] = item
        if len(result) != 48:
            raise RepositoryError(f"Expected 48 manifest months, found {len(result)}")
        return result

    def causal_panel_rows(self, hs6: str) -> Iterator[dict[str, object]]:
        """Yield one stable-HS6 series without exposing arbitrary SQL."""

        if not self.paths.causal_panel.exists():
            raise RepositoryError(
                "The compact HS6 panel is not present. Run the documented causal-panel build first."
            )
        with self.paths.causal_panel.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("hs6_2017", "").strip() != hs6:
                    continue
                key = (int(row["year"]), int(row["month"]))
                china = _parse_int(
                    row["china_import_value_consumption_usd"],
                    field="china_import_value_consumption_usd",
                    path=self.paths.causal_panel,
                )
                all_origins = _parse_int(
                    row["all_origin_import_value_consumption_usd"],
                    field="all_origin_import_value_consumption_usd",
                    path=self.paths.causal_panel,
                )
                if china > all_origins:
                    raise RepositoryError(f"China value exceeds all-origin value at {_month_label(key)}")
                yield {
                    "year": key[0],
                    "month": key[1],
                    "month_label": _month_label(key),
                    "china": china,
                    "all_origins": all_origins,
                    "other_origins": all_origins - china,
                    "china_share": float(row.get("china_share") or 0.0),
                    "source_hts10_count": int(row.get("source_hts10_count") or 0),
                    "source_hts10_mapped_count": int(row.get("source_hts10_mapped_count") or 0),
                    "source_url": row.get("source_url", ""),
                    "source_file_name": row.get("source_file_name", ""),
                    "source_sha256": row.get("source_sha256", ""),
                }
