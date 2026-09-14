"""Build a deterministic markdown/JSON exposure report from policy-case rows."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT = Path("data/processed/policy/section301_review2025_event.csv")
DEFAULT_PRODUCTS = Path("data/processed/policy/section301_review2025_products.csv")
DEFAULT_INPUT = Path(
    "data/processed/policy_exposure/monthly/"
    "us_301_review2025_tungsten_solar_2026_07.csv"
)
DEFAULT_JSON = Path("data/processed/policy_exposure/report_2026_07.json")
DEFAULT_MARKDOWN = Path("data/processed/policy_exposure/report_2026_07.zh-CN.md")


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _read_one(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError(f"Expected one row in {path}, found {len(rows)}")
    return rows[0]


def _read_products(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        code = row.get("canonical_hts8", "").strip()
        if len(code) != 8 or not code.isdigit() or code in result:
            raise ValueError(f"Invalid or duplicate product code in {path}: {code!r}")
        result[code] = row
    if not result:
        raise ValueError(f"No policy products in {path}")
    return result


def _read_rows(path: Path, policy_id: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "policy_id", "year", "month", "canonical_hts8", "origin_name",
        "import_value_consumption_usd", "source_sha256",
    }
    if rows and not required.issubset(rows[0]):
        raise ValueError(f"Exposure rows are missing fields: {sorted(required - set(rows[0]))}")
    if not rows or any(row.get("policy_id") != policy_id for row in rows):
        raise ValueError("Exposure rows do not match the registered policy")
    for row in rows:
        if int(row["import_value_consumption_usd"]) < 0:
            raise ValueError("Negative import value in exposure rows")
    return rows


def build_report(event_path: Path, products_path: Path, input_path: Path) -> dict[str, object]:
    event = _read_one(event_path)
    products = _read_products(products_path)
    rows = _read_rows(input_path, event["policy_id"])
    months = {(row["year"], row["month"]) for row in rows}
    if len(months) != 1:
        raise ValueError(f"Report input must contain one month, found {sorted(months)}")
    source_hashes = sorted({row["source_sha256"] for row in rows})
    if len(source_hashes) != 1:
        raise ValueError("Report input mixes source archive hashes")

    values: defaultdict[str, int] = defaultdict(int)
    china: defaultdict[str, int] = defaultdict(int)
    origins: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        code = row["canonical_hts8"]
        value = int(row["import_value_consumption_usd"])
        values[code] += value
        origins[code][row["origin_name"]] += value
        if row["origin_name"] == event["target_origin"].upper():
            china[code] += value

    product_rows: list[dict[str, object]] = []
    for code in sorted(products):
        total = values.get(code, 0)
        target_value = china.get(code, 0)
        share = (target_value / total * 100) if total else None
        top_origins = [
            {"origin_name": name, "import_value_consumption_usd": amount}
            for name, amount in sorted(origins.get(code, {}).items(), key=lambda item: (-item[1], item[0]))
            if amount > 0
        ][:5]
        product_rows.append({
            "canonical_hts8": code,
            "product_description": products[code]["product_description"],
            "product_description_zh": products[code].get("product_description_zh", "").strip(),
            "additional_rate_percent": float(products[code]["additional_rate_percent"]),
            "import_value_consumption_usd": total,
            "target_origin_value_usd": target_value,
            "target_origin_share_percent": round(share, 4) if share is not None else None,
            "top_origins": top_origins,
        })
    grand_total = sum(values.values())
    grand_target = sum(china.values())
    grand_share = grand_target / grand_total * 100 if grand_total else None
    return {
        "report_type": "descriptive_policy_exposure",
        "policy": event,
        "statistical_period": {"year": int(next(iter(months))[0]), "month": int(next(iter(months))[1])},
        "source_sha256": source_hashes[0],
        "input_path": _display(input_path),
        "scope": {"policy_hts8_count": len(products), "observed_policy_hts8_count": len(values)},
        "overall": {
            "import_value_consumption_usd": grand_total,
            "target_origin_value_usd": grand_target,
            "target_origin_share_percent": round(grand_share, 4) if grand_share is not None else None,
        },
        "products": product_rows,
        "limitations": [
            "这是美国消费进口规模和原产地份额，不是关税造成的损失或政策因果效果。",
            "税率是公告写明的额外税率，不是完整叠加后的当前总税率。",
            "只覆盖五个登记 HTS8；没有把相似商品或 HS6 前缀静默扩进来。",
            "统计期为 2026-07；月度统计有发布滞后，不能称实时数据。",
            "供应来源份额不代表该来源拥有足够产能，也不代表发生了贸易转移。",
        ],
    }


def _money(value: int) -> str:
    return f"${value:,.0f}"


def render_markdown(report: dict[str, object]) -> str:
    event = report["policy"]
    period = report["statistical_period"]
    overall = report["overall"]
    lines = [
        f"# 政策贸易暴露简报：{event['policy_name']}",
        "",
        f"- 统计期：{period['year']}-{int(period['month']):02d}",
        f"- 政策公布：{event['announcement_date']}；登记生效日：{event['effective_date']}",
        f"- 目标原产地：{event['target_origin']}；额外税率按商品分别为 25% 或 50%",
        f"- 数据来源哈希：`{report['source_sha256']}`",
        "",
        "## 先看结论",
        "",
        f"五个登记税号在该月的美国消费进口合计为 **{_money(int(overall['import_value_consumption_usd']))}**，其中中国原产金额为 **{_money(int(overall['target_origin_value_usd']))}**，占该五项美国进口的 **{overall['target_origin_share_percent']:.2f}%**。",
        "",
        "这个数字描述的是政策范围对应的贸易底数，不是政策造成的损失，也不证明政策导致了后续变化。",
        "",
        "## 分商品结果",
        "",
        "| HTS8 | 商品 | 公告额外税率 | 美国进口金额 | 中国金额 | 中国份额 | 主要正值来源 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for product in report["products"]:
        origins = "；".join(
            f"{item['origin_name']} {_money(int(item['import_value_consumption_usd']))}"
            for item in product["top_origins"]
        ) or "没有正值记录"
        share = "不可计算" if product["target_origin_share_percent"] is None else f"{product['target_origin_share_percent']:.2f}%"
        lines.append(
            f"| {product['canonical_hts8']} | {product['product_description_zh'] or product['product_description']} | {product['additional_rate_percent']:.0f}% | {_money(int(product['import_value_consumption_usd']))} | {_money(int(product['target_origin_value_usd']))} | {share} | {origins} |"
        )
    lines.extend([
        "",
        "## 解释边界",
        "",
        "- 报告回答“这项政策覆盖的商品目前涉及多大贸易、来源集中在哪里”，不回答“政策造成了多少损失”。",
        "- 中国份额较高表示当前来源依赖较高；不等于其他来源可以立即替代，也不等于政策一定会改变份额。",
        "- 报告使用确定性程序汇总明细；政策说明和机制解释仍需要人工核对原文。",
        "",
        "## 原始来源",
        "",
        f"- 政策原文：{event['source_url']}",
        f"- 实施说明：{event['implementation_source_url']}",
        f"- 贸易明细文件：`{report['input_path']}`，来源文件 SHA-256 `{report['source_sha256']}`",
        "",
        "## 限制",
    ])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args(argv)
    report = build_report(args.event, args.products, args.input)
    for path, content in (
        (args.json_output, json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
        (args.markdown_output, render_markdown(report)),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    print(json.dumps({"status": "ok", "json": str(args.json_output), "markdown": str(args.markdown_output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
