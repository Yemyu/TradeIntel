"""A bounded, policy-optional US import/export question and report flow.

The name registry is intentionally small and sourced from published HTS
headings. Numeric HTS8/10 questions remain possible without pretending that
the registry covers every commodity. No model is used to invent a code.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .trade_data_repository import TradeDataError, TradeDataRepository, TradeQuery
from .trade_export_repository import ExportDataRepository, ExportTradeQuery
from .trade_classification_catalog import CATALOG_DIR, ClassificationCatalog


HTS_SOURCES = {
    "2025": "https://www.usitc.gov/sites/default/files/tata/hts/hts_2025_revision_32_csv.csv",
    "2026": "https://www.usitc.gov/sites/default/files/tata/hts/hts_2026_revision_11_csv.csv",
}
PRODUCTS = {
    "soybeans": {"label": "大豆", "code": "1201", "pattern": re.compile(r"大豆|soybeans?", re.I)},
    "corn": {"label": "玉米", "code": "1005", "pattern": re.compile(r"玉米|\bcorn\b|\bmaize\b", re.I)},
}


def _add_month(month: str, offset: int) -> str:
    year, number = map(int, month.split("-"))
    index = year * 12 + number - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _product(question: str) -> tuple[str, str] | None:
    matched = [item for item in PRODUCTS.values() if item["pattern"].search(question)]
    numeric = set(re.findall(r"(?<!\d)\d{8}(?:\d{2})?(?!\d)", question))
    if len(matched) + len(numeric) != 1:
        return None
    if matched:
        return str(matched[0]["code"]), str(matched[0]["label"])
    code = numeric.pop()
    return code, f"商品编码 {code}"


_PRODUCT_JOIN = re.compile(r"以及|和|与|及|、|\band\b", re.I)
_EXTRA_PRODUCT_PATTERNS = [re.compile(pattern, re.I) for pattern in (
    r"小麦|\bwheat\b", r"咖啡|\bcoffee\b", r"茶叶?|\btea\b", r"棉花|\bcotton\b")]
_QUERY_CONTEXT = re.compile(
    r"(?:最近|最新|美国|来自中国|从中国|中国来源|对华|到中国|出口中国|与中国|"
    r"进口|出口|进出口|贸易|金额|总额|数据|商品|变化|变动|走势|趋势|情况|"
    r"怎么样|如何|多少|什么|有什么|有何|请问|查询|查一下|看一下|分析|"
    r"今年|去年|前年|本月|上月|同期|相比|相较|比较|同比|环比|增加|减少|上涨|下降|持平|上升|下滑|过去|近|年|月|"
    r"美元|的|于|为|在|是|及|以及|各|分别|总|各项|现状|"
    r"\b(?:20\d{2}|from|to|and|or|imports?|exports?|trade|value|trend|"
    r"change|latest|recent|monthly|yearly|yoy|mom)\b)", re.I)


def _contains_unresolved_product_join(question: str) -> bool:
    """Fail closed when a known product is joined to an unrecognized item.

    The registry is intentionally small. A conjunction next to a recognized
    product must not make the parser silently drop the other item.
    """
    patterns = [item["pattern"] for item in PRODUCTS.values()] + _EXTRA_PRODUCT_PATTERNS
    for join in _PRODUCT_JOIN.finditer(question):
        left_start = max(question.rfind(mark, 0, join.start()) for mark in ("，", ",", "。", ";", "；", "？", "?")) + 1
        right_ends = [question.find(mark, join.end()) for mark in ("，", ",", "。", ";", "；", "？", "?")]
        right_end = min((position for position in right_ends if position >= 0), default=len(question))
        left, right = question[left_start:join.start()], question[join.end():right_end]
        left_has_product = any(pattern.search(left) for pattern in patterns) or bool(
            re.search(r"(?<!\d)\d{8}(?:\d{2})?(?!\d)", left))
        right_has_product = any(pattern.search(right) for pattern in patterns) or bool(
            re.search(r"(?<!\d)\d{8}(?:\d{2})?(?!\d)", right))
        if left_has_product and right_has_product:
            left_kinds = {index for index, pattern in enumerate(patterns) if pattern.search(left)}
            right_kinds = {index for index, pattern in enumerate(patterns) if pattern.search(right)}
            if left_kinds != right_kinds:
                # A named HS4 group plus its own detailed code has a more
                # precise clarification below; do not replace it with the
                # generic multi-product message.
                names = [item for item in PRODUCTS.values() if item["pattern"].search(left + right)]
                numbers = set(re.findall(r"(?<!\d)\d{8}(?:\d{2})?(?!\d)", left + right))
                if len(names) == 1 and numbers and all(
                        code.startswith(names[0]["code"]) for code in numbers):
                    continue
                return True
            continue
        if not left_has_product and not right_has_product:
            continue
        other = right if left_has_product else left
        # Remove recognized names/codes and ordinary query wording. Any
        # remaining term could be a second product or scope, so ask first.
        residual = other
        for pattern in patterns:
            residual = pattern.sub("", residual)
        residual = re.sub(r"(?<!\d)\d{8}(?:\d{2})?(?!\d)", "", residual)
        residual = _QUERY_CONTEXT.sub("", residual)
        residual = re.sub(r"[\s\d年月日：:至到—~～/\\()（）【】\[\]{}'\"“”‘’]+", "", residual)
        if residual:
            return True
    return False


def _explicit_period(question: str) -> tuple[str, str] | str | None:
    """Return an explicit month/range, a clarification message, or None.

    Unqualified month names (for example, "7月") are deliberately not mapped
    to the latest year. A bounded range such as "2026年5月至7月" is accepted.
    """
    # Chinese calendar-month ranges, including a range whose end inherits the
    # first year: 2026年5月至7月. A second explicit year is also accepted.
    month = r"(0?[1-9]|1[0-2])"
    range_match = re.search(
        rf"(?P<start_year>20\d{{2}})年\s*(?P<start_month>{month})月?\s*"
        rf"(?:至|到|—|~|～)\s*(?:(?P<end_year>20\d{{2}})年\s*)?"
        rf"(?P<end_month>{month})月",
        question)
    if range_match:
        start_year = range_match.group("start_year")
        end_year = range_match.group("end_year") or start_year
        start = f"{start_year}-{int(range_match.group('start_month')):02d}"
        end = f"{end_year}-{int(range_match.group('end_month')):02d}"
        if start > end:
            return "日期范围顺序不清楚，请按起始月份到结束月份重新描述。"
        return start, end

    # Collect explicitly named calendar months. “12个月” is a duration, not
    # the calendar month December, hence the negative lookahead for 个.
    mentions: list[tuple[str | None, int, int]] = []
    for match in re.finditer(r"(?:(20\d{2})\s*年\s*)?(0?[1-9]|1[0-2])\s*月(?!个)", question):
        mentions.append((match.group(1), int(match.group(2)), match.start()))
    for match in re.finditer(r"(20\d{2})[-/](0?[1-9]|1[0-2])(?!\d)", question):
        mentions.append((match.group(1), int(match.group(2)), match.start()))
    mentions.sort(key=lambda item: item[2])
    deduplicated: list[tuple[str | None, int, int]] = []
    seen: set[tuple[str | None, int]] = set()
    for year, number, position in mentions:
        key = (year, number)
        if key not in seen:
            deduplicated.append((year, number, position))
            seen.add(key)
    mentions = deduplicated

    if len(mentions) > 1:
        return "问题里提到了多个分开的月份。请说明是逐月比较，还是查询某个连续月份范围。"
    if len(mentions) == 1:
        year, number, _ = mentions[0]
        if not year:
            return "请补充“7月”对应的年份；系统不会把没有年份的月份自动当成最新一年。"
        month_key = f"{year}-{number:02d}"
        return month_key, month_key
    return None


def _direction(question: str) -> str:
    # “进出口” is a common shorthand for both directions. Looking for the
    # complete words “进口” and “出口” separately sees only “出口” here.
    if re.search(r"进\s*(?:[、/／]\s*)?出口", question):
        return "both"
    import_word = bool(re.search(r"进口|imports?", question, re.I))
    export_word = bool(re.search(r"出口|exports?", question, re.I))
    if import_word and export_word:
        return "both"
    if import_word:
        return "import"
    if export_word:
        return "export"
    return "ambiguous"


def prepare_trade_question(root: Path, question: str, *, selected_flow: str | None = None,
                           selected_product_id: str | None = None,
                           catalog_version: str | None = None) -> dict:
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise TradeDataError("请先输入一个问题（不超过2000字）")
    question = question.strip()
    if selected_flow not in {None, "import", "export", "both"}:
        raise TradeDataError("贸易方向无效")
    if (selected_product_id is None) != (catalog_version is None):
        raise TradeDataError("商品选择和目录版本必须同时提供")
    classification = (ClassificationCatalog(root) if
                      (Path(root) / CATALOG_DIR / "manifest.json").is_file() else None)
    if re.search(r"豆粕|豆油|大豆油|大豆粉|soybean meal|soybean oil|玉米淀粉", question, re.I):
        return {"status": "needs_product", "message": "大豆、豆粕和大豆油（或玉米与玉米淀粉）属于不同商品范围，请给出准确的 HTS 编码。"}
    if re.search(r"中国对美|(?<!从)中国进口|欧盟|欧洲|日本进口|英国进口", question):
        return {"status": "not_available", "message": "目前只接入美国作为报告国的贸易数据。"}
    if _contains_unresolved_product_join(question):
        return {"status": "needs_product", "message": "问题里除了已识别商品，还出现了另一项未识别范围。请先选定一种商品，或提供准确的商品编码。"}
    product = _product(question)
    if product is None and classification is None:
        named = [item for item in PRODUCTS.values() if item["pattern"].search(question)]
        numeric = set(re.findall(r"(?<!\d)\d{8}(?:\d{2})?(?!\d)", question))
        if len(named) == 1 and numeric and len(named[0]["code"]) == 4 and all(
                code.startswith(named[0]["code"]) for code in numeric):
            message = "问题同时提到商品组和它的细分编码；两者范围不同。请确认要查整个商品组，还是只查该细分编码。"
        else:
            message = "请先选定一种商品：目前可直接识别大豆、玉米或一个明确的 HTS8/HTS10 编码；多个商品的比较尚未接入。"
        return {"status": "needs_product", "message": message}
    actual_flow = _direction(question)
    if actual_flow == "ambiguous" and selected_flow is None:
        return {"status": "needs_direction", "message": "你想看美国进口、出口，还是两者？具体可查月份会在确认范围时列出。",
                "product_label": product[1] if product else None}
    if actual_flow != "ambiguous" and selected_flow not in {None, actual_flow}:
        return {"status": "needs_direction", "message": "问题里的进口/出口方向与所选方向不一致，请重新确认。",
                "product_label": product[1] if product else None}
    flow = selected_flow if actual_flow == "ambiguous" else actual_flow
    if flow not in {"import", "export", "both"}:
        raise TradeDataError("贸易方向无效")
    if flow == "both" and product and len(product[0]) > 4 and classification is None:
        return {"status": "needs_product", "message": "进口 HTS 细码与出口 Schedule B 细码可能不同；请改用“大豆”“玉米”等已核实的共同商品组。"}
    if flow == "export" and product and len(product[0]) == 8:
        return {"status": "needs_product", "message": "这是进口 HTS8 编码；出口请使用已核实的 Schedule B 十位码或商品名称。"}
    if re.search(r"今年|去年|前年|本月|上月|近几天|近几年|近[一二三四五六七八九十两\d]+年|过去[一二三四五六七八九十两\d]+年|20\d{2}年以来", question):
        return {"status": "needs_period", "message": "请写明具体年份或月份；“最近”默认使用数据目录末月之前的12个连续月份。"}
    requested_period = _explicit_period(question)
    if isinstance(requested_period, str):
        return {"status": "needs_period", "message": requested_period}
    if re.search(r"同比|环比|去年同期|前年比|year.over.year|month.over.month", question, re.I):
        return {"status": "not_available", "message": "当前通用报告先提供原始月度趋势；同比、环比和分类口径可比性尚未验收，不能直接给出比较结论。"}
    import_catalog = TradeDataRepository(root).catalog() if flow in {"import", "both"} else None
    export_repo = ExportDataRepository(root) if flow in {"export", "both"} else None
    if export_repo and not export_repo.manifest.exists():
        if flow == "export":
            return {"status": "not_available", "message": "尚无已核验、可查询的美国出口月份。"}
        return {"status": "not_available", "message": "进口可查，但出口版本尚未接入，因此不能生成进出口并列报告。"}
    # A present but corrupted release is an integrity error, not "no data".
    export_catalog = export_repo.catalog() if export_repo else None
    catalogs = [catalog for catalog in (import_catalog, export_catalog) if catalog]
    month_sets = [{(item.get("month_key") or item["month"]) for item in catalog["months"]
                   if item["status"] == "queryable_aggregate"} for catalog in catalogs]
    months = sorted(set.intersection(*month_sets)) if month_sets else []
    if not months:
        return {"status": "not_available", "message": "所选方向没有共同的已核验月份。"}
    latest = max(months)
    years = set(re.findall(r"(?<!\d)(20\d{2})年?(?!\d)", question))
    if len(years) > 1 and requested_period is None:
        return {"status": "needs_period", "message": "一次只查询一个年份；请说明要查询哪一年。"}
    if requested_period is not None:
        start, end = requested_period
        if start > latest:
            return {"status": "not_available", "message": f"目前没有 {start[:4]} 年的已发布数据。"}
    elif years:
        year = years.pop()
        start, end = f"{year}-01", min(f"{year}-12", latest)
        if start > end:
            return {"status": "not_available", "message": f"目前没有 {year} 年的已发布数据。"}
    else:
        end = latest
        start = end
        # A newly added direction may have fewer than 12 verified months.
        # Show only the contiguous published tail, never cross a missing month.
        while len(months) >= 1 and start != _add_month(end, -11):
            previous = _add_month(start, -1)
            if previous not in months:
                break
            start = previous
    required = []
    current = start
    while current <= end:
        required.append(current)
        current = _add_month(current, 1)
    missing = [month for month in required if month not in months]
    if missing:
        return {"status": "not_available", "message": f"{start} 至 {end} 不是连续可查询区间；缺少 {', '.join(missing[:6])} 等月份。这里不会跨缺月画趋势。"}
    selected_candidate = None
    if classification is not None:
        candidates = classification.search(question, flow)
        if selected_product_id is None:
            if not candidates:
                return {"status": "needs_product", "message": "这个名称暂时没有经过核实的中文对应项。可用英文商品名或官方编码查找；不会猜测编码。"}
            return {"status": "needs_product_choice", "question": question, "flow": flow,
                    "start_month": start, "end_month": end,
                    "catalog_version": classification.version, "candidates": candidates,
                    "message": "请选择与问题相符的商品范围；英文名称是美国官方目录原文。"}
        if selected_product_id not in {item["id"] for item in candidates}:
            raise TradeDataError("所选商品与原问题或贸易方向不匹配，请重新选择")
        selected_candidate = classification.validate_choice(
            selected_product_id, catalog_version, flow, required)
        product = (selected_candidate["code"],
                   selected_candidate["zh_label"] or selected_candidate["official_en"])
    if product is None:
        return {"status": "needs_product", "message": "请先选择一种商品。"}
    if flow == "export" and re.search(r"来自中国|从中国|中国来源|from China", question, re.I):
        return {"status": "needs_direction", "message": "出口按目的地查询；你是想看美国出口到中国，还是美国从中国进口？"}
    china = bool(re.search(r"来自中国|从中国|中国来源|对华|到中国|出口中国|与中国|from China|to China", question, re.I))
    partner = "CHINA" if china else ("ALL_DESTINATIONS" if flow == "export" else "ALL_ORIGINS")
    if re.search(r"巴西|加拿大|欧盟来源|Brazil|Canada", question, re.I):
        return {"status": "not_available", "message": "当前加工数据只区分全部来源和中国来源；其他伙伴国明细尚未接入。"}
    code, label = product
    if classification is None and len(code) == 4 and import_catalog and any(month[:4] not in HTS_SOURCES for month in required):
        return {"status": "not_available", "message": "这个较早年份的商品组分类尚未核定；请用该年份的准确 HTS8/HTS10 编码查询。"}
    # Numeric codes must occur in the published snapshot; a typo must never
    # produce an authoritative-looking zero-valued report.
    if len(code) > 4 and classification is None:
        catalog = export_catalog if flow == "export" else import_catalog
        latest_entry = next(item for item in catalog["months"]
                            if (item.get("month_key") or item["month"]) == end)
        latest_file = root / latest_entry["processed_file"]
        with latest_file.open(encoding="utf-8") as stream:
            if not any(line.split(",")[2].startswith(code) for line in stream if line[:4].isdigit()):
                system = "Schedule B" if flow == "export" else "HTS"
                return {"status": "not_available", "message": f"最新已发布月份没有 {system} {code} 记录，请核对编码及分类年份。"}
    versions = {"import": import_catalog["dataset_version"] if import_catalog else None,
                "export": export_catalog["dataset_version"] if export_catalog else None}
    version = (hashlib.sha256(json.dumps(versions, sort_keys=True).encode()).hexdigest()
               if flow == "both" else versions[flow])
    urls = ([classification.entries[(direction, month)]["source_url"]
             for month in required for direction in (("import", "export") if flow == "both" else (flow,))]
            if classification is not None else
            [HTS_SOURCES[year] for year in sorted({month[:4] for month in required})
             if import_catalog and year in HTS_SOURCES])
    if export_catalog and classification is None:
        urls.extend(f"https://www.census.gov/foreign-trade/schedules/b/{year}/c{int(code[:2]):02d}.pdf"
                    for year in sorted({month[:4] for month in required}))
    return {"status": "ready", "kind": "trade-query-v1", "question": question,
            "reporter": "US", "flow": flow, "product_code": code,
            "product_label": label, "start_month": start, "end_month": end,
            "selected_product_id": selected_product_id,
            "catalog_version": classification.version if classification else None,
            "official_product_en": selected_candidate["official_en"] if selected_candidate else None,
            "latest_available_month": latest,
            "partner": partner, "dataset_version": version, "dataset_versions": versions,
            "metric": "mixed_separate" if flow == "both" else
                      ("total_export_fas_usd" if flow == "export" else "import_value_consumption_usd"),
            "classification_source_urls": urls,
            "coverage_note": (f"出口目前只有 {len(required)} 个月可用于这次查询；不足12个月，不能据此判断长期趋势。"
                              if export_catalog and len(required) < 12 else None),
            "message": "请核对商品、方向、月份和来源范围，再生成报告。"}


def generate_trade_report(root: Path, question: str, *, selected_flow: str | None,
                          dataset_version: str, selected_product_id: str | None = None,
                          catalog_version: str | None = None) -> dict:
    proposal = prepare_trade_question(root, question, selected_flow=selected_flow,
                                      selected_product_id=selected_product_id,
                                      catalog_version=catalog_version)
    if proposal["status"] != "ready":
        raise TradeDataError(proposal["message"])
    if dataset_version != proposal["dataset_version"]:
        raise TradeDataError("数据版本已变化，请重新确认查询范围")
    if proposal["flow"] == "both":
        import_facts = TradeDataRepository(root).query(TradeQuery(
            "US", "import", proposal["product_code"], proposal["start_month"],
            proposal["end_month"], proposal["partner"] if proposal["partner"] == "CHINA" else "ALL_ORIGINS",
            proposal["dataset_versions"]["import"]))
        export_facts = ExportDataRepository(root).query(ExportTradeQuery(
            "US", "export", proposal["product_code"], proposal["start_month"],
            proposal["end_month"], proposal["partner"] if proposal["partner"] == "CHINA" else "ALL_DESTINATIONS",
            proposal["dataset_versions"]["export"]))
        return {"kind": "trade-query-both-v1", "question": question, "scope": proposal,
                "import_report": _report_from_facts(
                    question, dict(proposal, flow="import",
                                   metric="import_value_consumption_usd",
                                   partner="CHINA" if proposal["partner"] == "CHINA" else "ALL_ORIGINS"),
                    import_facts),
                "export_report": _report_from_facts(
                    question, dict(proposal, flow="export",
                                   metric="total_export_fas_usd",
                                   partner="CHINA" if proposal["partner"] == "CHINA" else "ALL_DESTINATIONS"),
                    export_facts),
                "ai_status": "not_run",
                "notes": ["进口消费额与出口 FAS 总额是不同统计口径，不能直接相减称为贸易差额。"]}
    if proposal["flow"] == "export":
        facts = ExportDataRepository(root).query(ExportTradeQuery(
            "US", "export", proposal["product_code"], proposal["start_month"],
            proposal["end_month"], proposal["partner"], dataset_version))
    else:
        facts = TradeDataRepository(root).query(TradeQuery(
            "US", "import", proposal["product_code"], proposal["start_month"],
            proposal["end_month"], proposal["partner"], dataset_version))
    return _report_from_facts(question, proposal, facts)


def _report_from_facts(question: str, proposal: dict, facts: dict) -> dict:
    rows = facts["months"]
    observed = [row for row in rows if row["status"] == "observed"]
    complete = len(observed) == len(rows)
    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    change = None
    if previous and latest["status"] == previous["status"] == "observed":
        change = latest["value_usd"] - previous["value_usd"]
    sources = list(dict.fromkeys(row.get("source_url") for row in rows if row.get("source_url")))
    export = proposal["flow"] == "export"
    notes = (["本报告只使用美国商品总出口额（国产出口与再出口之和，FAS），不包含进口。",
              "金额变化可能来自数量或价格，不能仅凭金额判断政策效果。"] if export else
             ["本报告只使用美国消费进口额，不包含出口。",
              "金额变化可能来自进口数量或价格；仅凭金额不能判断政策效果。"])
    notes.append("目前未运行模型解释；本页摘要和图表均由已发布数据计算。")
    return {"kind": "trade-query-v1", "question": question, "scope": proposal,
            "series": rows, "summary": {"latest_month": latest["month"],
                                       "latest_value_usd": latest["value_usd"] if latest["status"] == "observed" else None,
                                       "previous_month": previous["month"] if previous else None,
                                       "month_change_usd": change,
                                       "period_total_usd": sum(row["value_usd"] for row in observed) if complete else None,
                                       "complete_window": complete},
            "sources": sources, "ai_status": "not_run",
            "notes": notes}
