"""Read-only tools for the registered 2025 policy-exposure case.

This module is intentionally separate from the frozen 2018 causal prototype.
It reads the verified monthly CSV artifacts, validates the requested scope,
and returns source-linked descriptive trade exposure.  It never estimates a
policy effect and never accepts arbitrary SQL or filesystem paths.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from .repository import EvidenceRepository, RepositoryError
from .tools import ToolError, ToolRegistry
from .policy_cases import resolve_case


POLICY_EXPOSURE_ID = "us_301_review2025_tungsten_solar"
EXPOSURE_EVENT_RELATIVE = "data/processed/policy/section301_review2025_event.csv"
EXPOSURE_PRODUCTS_RELATIVE = "data/processed/policy/section301_review2025_products.csv"
EXPOSURE_MANIFEST_RELATIVE = "data/processed/policy_exposure/manifest.json"
EXPOSURE_MONTHLY_RELATIVE = "data/processed/policy_exposure/monthly"
EXPOSURE_START = (2025, 1)
EXPOSURE_END = (2026, 7)
EXPOSURE_FIELDS = [
    "policy_id", "year", "month", "canonical_hts8", "hts10", "origin_code",
    "origin_name", "import_value_consumption_usd", "detail_row_count",
    "source_url", "source_file_name", "source_sha256",
]
HTS8_PATTERN = re.compile(r"^[0-9]{8}$")


def _month_key(value: object) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ToolError(f"月份必须使用 YYYY-MM 格式：{value!r}")
    year, month = int(value[:4]), int(value[5:])
    if not 1 <= month <= 12:
        raise ToolError(f"月份无效：{value!r}")
    return year, month


def _month_label(key: tuple[int, int]) -> str:
    return f"{key[0]:04d}-{key[1]:02d}"


def _month_range(start: str, end: str) -> list[tuple[int, int]]:
    first, last = _month_key(start), _month_key(end)
    if first < EXPOSURE_START or last > EXPOSURE_END:
        raise ToolError(
            f"月份必须位于已验证窗口 {_month_label(EXPOSURE_START)} 至 "
            f"{_month_label(EXPOSURE_END)}；超出部分不能假装已覆盖"
        )
    if first > last:
        raise ToolError("start 不能晚于 end")
    result: list[tuple[int, int]] = []
    year, month = first
    while (year, month) <= last:
        result.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return result


def _normalise_origin(origin: object) -> str:
    if not isinstance(origin, str):
        raise ToolError("origin 必须是 China、other_origins 或 all_origins")
    key = origin.strip().lower().replace(" ", "")
    aliases = {
        "china": "China", "中国": "China", "target": "China",
        "other_origins": "other_origins", "otherorigins": "other_origins", "其他原产地": "other_origins",
        "all_origins": "all_origins", "allorigins": "all_origins", "all": "all_origins", "全部原产地": "all_origins",
    }
    try:
        return aliases[key]
    except KeyError as exc:
        raise ToolError("origin 只能是 China、other_origins 或 all_origins") from exc


def _paths(repository: EvidenceRepository, policy_id=POLICY_EXPOSURE_ID) -> tuple[Path, Path, Path, Path]:
    root = repository.paths.root
    case = resolve_case(policy_id)
    return (
        root / case.event,
        root / case.products,
        root / case.manifest,
        root / case.monthly,
    )


def _read_one(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RepositoryError(f"登记资源缺失：{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise RepositoryError(f"登记资源应恰好一行：{path}")
    return rows[0]


def _read_products(path: Path, policy_id: str) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise RepositoryError(f"政策商品登记缺失：{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("policy_id", "").strip() != policy_id:
            continue
        code = row.get("canonical_hts8", "").replace(".", "").strip()
        if not HTS8_PATTERN.fullmatch(code) or code in result:
            raise RepositoryError(f"政策商品登记含无效或重复 HTS8：{code!r}")
        result[code] = row
    if not result:
        raise RepositoryError(f"没有找到政策 {policy_id!r} 的商品登记")
    return result


def _read_manifest(path: Path, policy_id: str) -> dict[tuple[int, int], dict[str, object]]:
    if not path.exists():
        raise RepositoryError(f"政策暴露 manifest 缺失：{path}")
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryError(f"无法读取政策暴露 manifest：{path}") from exc
    if payload.get("policy_id") != policy_id or not isinstance(payload.get("months"), list):
        raise RepositoryError("政策暴露 manifest 的 policy_id 或 months 无效")
    result: dict[tuple[int, int], dict[str, object]] = {}
    for item in payload["months"]:
        if not isinstance(item, dict):
            raise RepositoryError("政策暴露 manifest 的月份不是对象")
        key = (int(item["year"]), int(item["month"]))
        if key in result:
            raise RepositoryError(f"政策暴露 manifest 重复月份：{_month_label(key)}")
        result[key] = item
    return result


def _read_month_rows(path: Path, policy_id: str, key: tuple[int, int]) -> list[dict[str, str]]:
    if not path.exists():
        raise RepositoryError(f"政策暴露月度文件缺失：{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPOSURE_FIELDS:
            raise RepositoryError(f"月度文件字段不符合契约：{path}")
        rows = list(reader)
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in rows:
        row_key = (
            row.get("policy_id", ""), row.get("year", ""), row.get("month", ""),
            row.get("canonical_hts8", ""), row.get("hts10", ""), row.get("origin_code", ""),
        )
        if row_key in seen:
            raise RepositoryError(f"月度文件存在重复键：{path} {row_key}")
        seen.add(row_key)
        if row["policy_id"] != policy_id or int(row["year"]) != key[0] or int(row["month"]) != key[1]:
            raise RepositoryError(f"月度文件含错误 policy_id 或统计期：{path}")
        if not HTS8_PATTERN.fullmatch(row["canonical_hts8"]):
            raise RepositoryError(f"月度文件含无效 HTS8：{path}")
        try:
            value = int(row["import_value_consumption_usd"])
            detail_count = int(row["detail_row_count"])
        except ValueError as exc:
            raise RepositoryError(f"月度文件含非整数金额或明细行数：{path}") from exc
        if value < 0 or detail_count < 1:
            raise RepositoryError(f"月度文件含负数金额或空明细组：{path}")
    return rows


def get_policy_exposure_series(
    origin: str = "China",
    *,
    policy_id: str = POLICY_EXPOSURE_ID,
    hts8: str | None = None,
    start: str = "2025-01",
    end: str = "2026-07",
    repository: EvidenceRepository | None = None,
) -> dict[str, object]:
    """Return a registered policy's monthly descriptive exposure series."""

    repository = repository or EvidenceRepository()
    try:
        case = resolve_case(policy_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    from .exposure_version_store import pin_repository, VersionStoreError
    repository = pin_repository(repository, policy_id=policy_id)
    snapshot = getattr(repository, 'exposure_snapshot', None)
    if snapshot and (start < snapshot['start'] or end > snapshot['end']):
        raise VersionStoreError('请求月份超出发布版本范围')
    if snapshot and snapshot['policy_id'] != policy_id:
        raise VersionStoreError('发布快照的政策案例与请求不一致')
    if start < case.start or end > case.end:
        raise ToolError('请求超出案例登记窗口')
    selected_origin = _normalise_origin(origin)
    selected_months = _month_range(start, end)
    event_path, products_path, manifest_path, monthly_dir = _paths(repository, policy_id)
    event = _read_one(event_path)
    if event.get("policy_id") != policy_id:
        raise RepositoryError("政策事件登记与请求 policy_id 不一致")
    products = _read_products(products_path, policy_id)
    correction_path = manifest_path.parent / 'policy_metadata_corrections.json'
    correction = None
    if correction_path.exists():
        correction = json.loads(correction_path.read_text())
        if correction.get('policy_id') != policy_id:
            raise RepositoryError('政策元数据修订范围不一致')
        for code, fields in correction['products'].items():
            if code not in products:
                raise RepositoryError('修订包含未登记税号')
            products[code].update(fields)
    if hts8 is not None:
        hts8 = str(hts8).replace(".", "").strip()
        if hts8 not in products:
            raise ToolError("hts8 必须是该登记政策的 8 位税号之一")
    manifest = _read_manifest(manifest_path, policy_id)

    series: list[dict[str, object]] = []
    sources: list[dict[str, str]] = [
        repository.file_source(event_path, source_url=event.get("source_url")),
        repository.file_source(products_path, source_url=event.get("source_url")),
        repository.file_source(manifest_path),
    ]
    missing_months: list[str] = []
    if correction:
        sources.append(repository.file_source(correction_path))
    for key in selected_months:
        label = _month_label(key)
        item = manifest.get(key)
        if item is None:
            missing_months.append(label)
            series.append({"month": label, "value_usd": None, "target_share_percent": None})
            continue
        output_path = monthly_dir / f"{policy_id}_{key[0]}_{key[1]:02d}.csv"
        receipt_path = monthly_dir.parent / "window_validation_2025-01_2026-07.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        matches = [entry for entry in receipt.get("months", [])
                   if (entry.get("year"), entry.get("month")) == key]
        if (receipt.get("status") != "validated" or receipt.get("policy_id") != policy_id
                or len(matches) != 1
                or matches[0].get("archive_sha256") != item.get("source_sha256")
                or matches[0].get("output_sha256") != hashlib.sha256(output_path.read_bytes()).hexdigest()):
            raise RepositoryError(f"月度文件与窗口验收版本不一致：{label}")
        rows = _read_month_rows(output_path, policy_id, key)
        expected_hash = str(item.get("source_sha256", ""))
        row_hashes = {row["source_sha256"] for row in rows}
        if len(row_hashes) != 1 or next(iter(row_hashes), "") != expected_hash:
            raise RepositoryError(f"月度文件来源哈希与 manifest 不一致：{label}")
        observed_codes = {row["canonical_hts8"] for row in rows}
        if observed_codes != set(products):
            raise RepositoryError(f"月度商品覆盖与登记范围不一致：{label}")
        for row in rows:
            if not re.fullmatch(r"[0-9]{10}", row["hts10"]) or row["hts10"][:8] != row["canonical_hts8"]:
                raise RepositoryError(f"HTS10 与 HTS8 不匹配：{label}")
            if not re.fullmatch(r"[0-9]{4}", row["origin_code"]):
                raise RepositoryError(f"原产地代码无效：{label}")
            if row["source_url"] != item.get("source_url") or row["source_file_name"] != item.get("source_file_name"):
                raise RepositoryError(f"来源 URL 或文件名不一致：{label}")
        if sum(int(row["import_value_consumption_usd"]) for row in rows) != item.get("total_consumption_value_usd"):
            raise RepositoryError(f"月度金额与提取清单不一致：{label}")
        if sum(int(row["detail_row_count"]) for row in rows) != item.get("matched_detail_rows"):
            raise RepositoryError(f"月度明细行数与提取清单不一致：{label}")
        sources.append(repository.file_source(output_path))
        sources.append({
            "kind": "official_census_archive",
            "month": label,
            "url": str(item.get("source_url", "")),
            "file_name": str(item.get("source_file_name", "")),
            "sha256": expected_hash,
        })
        filtered = [row for row in rows if hts8 is None or row["canonical_hts8"] == hts8]
        all_value = sum(int(row["import_value_consumption_usd"]) for row in filtered)
        china_value = sum(
            int(row["import_value_consumption_usd"])
            for row in filtered if row["origin_code"] == "5700"
        )
        if selected_origin == "China":
            value = china_value
        elif selected_origin == "other_origins":
            value = all_value - china_value
        else:
            value = all_value
        breakdown = []
        for code in sorted({row['canonical_hts8'] for row in filtered}):
            group = [row for row in filtered if row['canonical_hts8'] == code]
            world = sum(int(row['import_value_consumption_usd']) for row in group)
            china = sum(int(row['import_value_consumption_usd']) for row in group if row['origin_code'] == '5700')
            breakdown.append({'hts8': code, 'all_origins_value_usd': world,
                              'china_value_usd': china,
                              'china_share_percent': round(china / world * 100, 4) if world else None,
                              'share_of_scope_imports_percent': round(world / all_value * 100, 4) if all_value else None})
        series.append({
            "month": label,
            "value_usd": value,
            "all_origins_value_usd": all_value,
            "china_value_usd": china_value,
            "target_share_percent": round(china_value / all_value * 100, 4) if all_value else None,
            "product_breakdown": breakdown,
        })

    observed = [item["value_usd"] for item in series if item["value_usd"] is not None]
    result = {
        "tool_name": "get_policy_exposure_series",
        "tool_version": "1.0",
        "status": "ok",
        "causal_claim": False,
        "post_policy_activity_used_for_matching": False,
        "data": {
            "policy_id": policy_id,
            "policy_name": event.get("policy_name", ""),
            "scope": "registered_policy_hts8",
            "hts8": hts8,
            "origin": selected_origin,
            "measure": "import_value_consumption_usd",
            "start": start,
            "end": end,
            "months": len(series),
            "requested_months": [_month_label(key) for key in selected_months],
            "series": series,
            "total_usd": None if missing_months else sum(int(value) for value in observed),
            "observed_total_usd": sum(int(value) for value in observed),
            "coverage_complete": not missing_months,
            "missing_months": missing_months,
            "product": products.get(hts8) if hts8 else None,
        },
        "evidence": {
            "sources": sources,
            "selection_rule": "登记政策的精确 HTS8；不扩大到 HS6 或相似商品",
        },
        "limitations": [
            "CONCORD 编码存在性已检查；跨期编码定义连续性仍待审阅，不能据此保证同比可比。",
            "金额是美国消费进口的描述性贸易暴露，不是关税造成的损失或因果效果。",
            "中国份额不等于中国对美国出口依赖，也不代表其他来源可以立即替代。",
            "统计期按月发布；缺失月份保留为未知，不能补零。",
        ],
    }
    result['policy_metadata'] = correction or {'status': 'no_reviewed_correction_record'}
    corpus_path = manifest_path.parent / 'policy_corpus.json'
    if corpus_path.exists():
        from datetime import datetime, timezone
        if policy_id == 'us_301_solar2024':
            from .solar_policy import retrieve_solar_policy as retrieve_policy
        else:
            from .exposure_policy import retrieve_exposure_policy as retrieve_policy
        result['policy_evidence'] = retrieve_policy(
            repository.paths.root, '登记政策 ' + (hts8 or '') + ' 税率 生效 商品范围',
            as_of=datetime.now(timezone.utc).date().isoformat())
        result['evidence']['sources'].append(repository.file_source(corpus_path))
    else:
        result['policy_evidence'] = {'status': 'unavailable', 'hits': [], 'reason': 'policy corpus not built'}
    pin_repository(repository, policy_id=policy_id)
    result['data_version'] = getattr(repository, 'exposure_version', None)
    return result


class PolicyExposureRegistry(ToolRegistry):
    """The new-case registry; the frozen six-tool registry remains unchanged."""

    def __init__(self, repository: EvidenceRepository | None = None) -> None:
        super().__init__(repository)
        self._functions["get_policy_exposure_series"] = get_policy_exposure_series

    def schemas(self) -> list[dict[str, object]]:
        schemas = super().schemas()
        schemas.append({
            "type": "function",
            "name": "get_policy_exposure_series",
            "description": (
                "Query the verified monthly US consumption-import exposure for the registered 2025 Section 301 case. "
                "Use exact registered HTS8 codes and one of China, other_origins, or all_origins. "
                "This is descriptive exposure, not a causal estimate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "policy_id": {"type": "string", "enum": [POLICY_EXPOSURE_ID], "default": POLICY_EXPOSURE_ID},
                    "origin": {"type": "string", "enum": ["China", "other_origins", "all_origins"], "default": "China"},
                    "hts8": {"type": ["string", "null"], "pattern": "^[0-9]{8}$", "default": None},
                    "start": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$", "default": "2025-01"},
                    "end": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$", "default": "2026-07"},
                },
                "additionalProperties": False,
            },
        })
        return schemas
