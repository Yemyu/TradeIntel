"""Build compact deterministic monthly metrics from policy exposure CSVs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

try:
    from scripts.build_trade_panel import month_range
    from scripts.extract_policy_case_monthly import (
        DEFAULT_OUTPUT_DIR,
        DEFAULT_POLICY,
        load_policy_scope,
    )
except ModuleNotFoundError:  # pragma: no cover
    from build_trade_panel import month_range  # type: ignore[no-redef]
    from extract_policy_case_monthly import (  # type: ignore[no-redef]
        DEFAULT_OUTPUT_DIR,
        DEFAULT_POLICY,
        load_policy_scope,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def build_summary(
    *, start: tuple[int, int], end: tuple[int, int], policy_path: Path, output_dir: Path,
) -> dict[str, object]:
    policy_id, descriptions, policy_codes = load_policy_scope(policy_path)
    months: list[dict[str, object]] = []
    products: list[dict[str, object]] = []
    expected = month_range(start, end)
    for source in expected:
        path = output_dir / f"{policy_id}_{source.year}_{source.month:02d}.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise ValueError(f"Empty monthly output: {path}")
        hashes = {row["source_sha256"] for row in rows}
        if len(hashes) != 1:
            raise ValueError(f"Mixed source hashes: {path}")
        total = 0
        target = 0
        by_product: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        for row in rows:
            if row["policy_id"] != policy_id or int(row["year"]) != source.year or int(row["month"]) != source.month:
                raise ValueError(f"Wrong policy/month in {path}: {row}")
            code = row["canonical_hts8"]
            if code not in policy_codes:
                raise ValueError(f"Out-of-scope code in {path}: {code}")
            value = int(row["import_value_consumption_usd"])
            total += value
            by_product[code][0] += value
            if row["origin_name"].upper() == "CHINA":
                target += value
                by_product[code][1] += value
        months.append({
            "year": source.year,
            "month": source.month,
            "period": f"{source.year}-{source.month:02d}",
            "policy_id": policy_id,
            "import_value_consumption_usd": total,
            "china_origin_value_usd": target,
            "china_origin_share_percent": round(target / total * 100, 4) if total else None,
            "output_rows": len(rows),
            "source_sha256": next(iter(hashes)),
            "source_file_name": source.filename,
        })
        for code in sorted(policy_codes):
            product_total, product_target = by_product[code]
            products.append({
                "period": f"{source.year}-{source.month:02d}",
                "year": source.year,
                "month": source.month,
                "canonical_hts8": code,
                "product_description": descriptions[code],
                "import_value_consumption_usd": product_total,
                "china_origin_value_usd": product_target,
                "china_origin_share_percent": round(product_target / product_total * 100, 4) if product_total else None,
            })
    return {
        "report_type": "descriptive_policy_exposure_window",
        "policy_id": policy_id,
        "window": {
            "start": f"{start[0]}-{start[1]:02d}",
            "end": f"{end[0]}-{end[1]:02d}",
            "month_count": len(months),
        },
        "target_origin": "CHINA",
        "months": months,
        "products": products,
        "limitations": [
            "这是美国消费进口规模和原产地份额，不是政策造成的损失或因果效果。",
            "金额是名义美元，不能直接解释为数量或利润变化。",
            "统计数据按月发布，不等于实时数据；窗口中的 2026-07 是当前已验证的最后月份。",
            "中国份额不代表中国对美国的出口依赖，也不代表其他来源可以立即替代。",
        ],
    }


def render_markdown(summary: dict[str, object]) -> str:
    window = summary["window"]
    lines = [
        "# 政策贸易暴露：多月数据窗口",
        "",
        f"- 政策案例：`{summary['policy_id']}`",
        f"- 已验证窗口：{window['start']} 至 {window['end']}，共 {window['month_count']} 个月",
        "- 口径：五个登记 HTS8 对应的美国消费进口金额；中国为原产地份额",
        "",
        "这张表把每个月的真实贸易明细压缩成可供 AI 查询的确定性指标。它回答“涉及规模和来源如何变化”，不回答“政策造成了多少变化”。",
        "",
        "## 月度总览",
        "",
        "| 月份 | 美国进口金额 | 中国原产金额 | 中国份额 | 明细分组 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summary["months"]:
        share = "不可计算" if row["china_origin_share_percent"] is None else f"{row['china_origin_share_percent']:.2f}%"
        lines.append(
            f"| {row['period']} | ${row['import_value_consumption_usd']:,.0f} | ${row['china_origin_value_usd']:,.0f} | {share} | {row['output_rows']} |"
        )
    lines.extend(["", "## 限制", ""])
    lines.extend(f"- {item}" for item in summary["limitations"])
    return "\n".join(lines) + "\n"


def _month(value: str) -> tuple[int, int]:
    year, month = (int(part) for part in value.split("-", 1))
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError(f"Invalid month: {value}")
    return year, month


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_month, required=True)
    parser.add_argument("--end", type=_month, required=True)
    parser.add_argument("--policy-products", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = build_summary(start=args.start, end=args.end, policy_path=args.policy_products, output_dir=args.output_dir)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"status": "ok", "months": summary["window"]["month_count"], "json": _display(args.json_output), "markdown": _display(args.markdown_output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
