"""Build a static, explicitly whitelisted showcase from four saved records.

No provider configuration is read. Source mappings and the audit stay outside
the site. Changed/missing sources fail closed; this never runs an experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from tradeintel_ai.trade_agent_report_view import build_reader_view
from tradeintel_ai.trade_report_store import load_record

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web/design-preview"
IDS = ("soybean-trade", "soybean-oil", "policy-materials", "missing-month")
ASSETS = ("index.html", "style.css", "app.js", "cases.js", "report-view.js",
          "vendor/cobe.mjs", "vendor/COBE-LICENSE", "vendor/PHENOMENON-LICENSE")
# Private local mappings. Never copied to site/.
SOURCES = {
    ".local/trade-agent-sessions/954ba89ef27843fbb8ef38ce9cdc7811.json": "de538202c28b4099e0847ff5f832db951f20d62a4a0b4d828a6d5ed91a2892a8",
    ".local/trade-agent-sessions/8b72abdef42f454bb8a0718b355a7bf8.json": "ed23f8a62e8f3944341cc9476368246ba35e379d9fa5ca4b4dcc20d3058c60e5",
    ".local/trade-agent-sessions/269e1982bc1048eabd304921159c43be.json": "94677a4df770d68ce1be7c2c8d71f8b219a1e63c27ab6cf333d2475004775183",
    ".local/trade-reports/e96b7fa47fbb44cda03d0a3c491d7e35.json": "7ea98f9b354f7e0897bf1aa29ff73cf3547a8f9dc4882a71d0097d0dc424d487",
    ".local/trade-reports/c157cfc33ca1427f9ab5349d01333c55.json": "f5163832b830c297cf9c4c3df418801ca54cecfb296b2c9792bc8cc98804d50f",
    ".local/trade-reports/96a5b06dcdf2470e81f209df9d0a1a67.json": "0b2fe5b50a22e71ebded452cba5567a6ee0f48aef3b875d00155edd21a63a1dc",
    ".local/trade-reports/296cd28afda34d458bffe2a326fa0ec6.json": "e37491923b69b2ce0178375a53171089e1843a510504aaca779ae5d68a029852",
    "web/design-preview/data.json": "94da1167297b108288fb329a5f5c460d17972fe2613e608c44520d5d251094fa",
}
SESSIONS = {IDS[0]: "954ba89ef27843fbb8ef38ce9cdc7811",
            IDS[1]: "8b72abdef42f454bb8a0718b355a7bf8",
            IDS[3]: "269e1982bc1048eabd304921159c43be"}
REPORTS = {IDS[0]: ["e96b7fa47fbb44cda03d0a3c491d7e35", "c157cfc33ca1427f9ab5349d01333c55", "96a5b06dcdf2470e81f209df9d0a1a67"],
           IDS[1]: ["296cd28afda34d458bffe2a326fa0ec6"]}
EXPECTED = {"soybean-trade": [46041287, 889379312, 152115], "soybean-oil": [27503913]}
SCOPE_KEYS = {"product_code", "product_label", "official_product_en", "flow", "partner", "start_month", "end_month", "metric"}
SUMMARY_KEYS = {"complete_window", "latest_month", "latest_value_usd", "previous_month", "month_change_usd", "period_total_usd"}
OFFICIAL_HOSTS = {"www.census.gov", "www.usitc.gov", "content.govdelivery.com"}
# Translate the frozen saved replies themselves. Report facts may contain
# additional comparisons and must not be inserted into the saved conversation.
SAVED_ANSWER_TRANSLATIONS = {
    "已查询美国大豆，不论是否破碎（1201）2025-08 至 2026-07的已发布进口数据。2026-07（全部来源地）进口消费额为 46,041,287 美元。已查询美国大豆，不论是否破碎（1201）2025-08 至 2026-07的已发布进口数据。2026-07（中国来源地）进口消费额为 152,115 美元。仅凭这些贸易金额不能判断政策效果；图表与来源见报告。":
        "Published U.S. import data for soybeans, whether or not broken (1201), were queried for 2025-08 to 2026-07. In 2026-07, imports for consumption from all origins were 46,041,287 USD. Published U.S. import data for soybeans, whether or not broken (1201), were queried for 2025-08 to 2026-07. In 2026-07, imports for consumption from China were 152,115 USD. Trade values alone cannot establish policy effects; see the reports for charts and sources.",
    "已查询美国大豆，不论是否破碎（1201）2025-08 至 2026-07的已发布出口数据。2026-07（全部目的地）出口 FAS 总额为 889,379,312 美元。仅凭这些贸易金额不能判断政策效果；图表与来源见报告。":
        "Published U.S. export data for soybeans, whether or not broken (1201), were queried for 2025-08 to 2026-07. In 2026-07, total exports (FAS) to all destinations were 889,379,312 USD. Trade values alone cannot establish policy effects; see the reports for charts and sources.",
    "已查询美国豆油及其分离品，不论是否精制，但未经化学改性（1507）2025-08 至 2026-07的已发布进口数据。2026-07（全部来源地）进口消费额为 27,503,913 美元。仅凭这些贸易金额不能判断政策效果；图表与来源见报告。":
        "Published U.S. import data for soybean oil and its fractions, whether or not refined, but not chemically modified (1507), were queried for 2025-08 to 2026-07. In 2026-07, imports for consumption from all origins were 27,503,913 USD. Trade values alone cannot establish policy effects; see the reports for charts and sources.",
    "用户指定的是日历上月；缺少 2026-08 的已核验可查询数据。最新可用月为 2026-07。如需改查最新可用月，请明确提出。":
        "The requested calendar month is August 2026, but verified data is available only through July 2026. Please explicitly ask to use the latest available month if that is what you want.",
}


def translate_saved_answer(message):
    if type(message) is not str or message not in SAVED_ANSWER_TRANSLATIONS:
        raise ValueError("Saved answer has no verified English translation")
    return SAVED_ANSWER_TRANSLATIONS[message]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("Duplicate JSON field")
            obj[key] = value
        return obj
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid number")))


def keys(obj, expected):
    if type(obj) is not dict or set(obj) != set(expected):
        raise ValueError("Unexpected public fields")


def url(value):
    if type(value) is not str:
        raise ValueError("Invalid source URL")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"https", "http"} or parsed.hostname not in OFFICIAL_HOSTS
            or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment
            or "\\" in value):
        raise ValueError("Non-official source URL")
    if parsed.hostname == "content.govdelivery.com" and not parsed.path.startswith("/accounts/USDHSCBP/bulletins/"):
        raise ValueError("Non-official bulletin")


def scan(value):
    """Reject credential-shaped strings and private local paths, at any depth."""
    if isinstance(value, dict):
        for item in value.values():
            scan(item)
    elif isinstance(value, list):
        for item in value:
            scan(item)
    elif isinstance(value, str):
        if re.search(r"sk-[A-Za-z0-9_.-]{8,}|[0-9a-f]{32}\.[A-Za-z0-9_-]{8,}|/Users/|/home/|\.local/|tmp/handoff|(?:file|javascript|data):|localhost|127\.0\.0\.1|[A-Z]:\\", value, re.I):
            raise ValueError("Private or credential-like public content")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Invalid number")


def bilingual(value):
    keys(value, {"zh", "en"})
    if any(type(x) is not str or not x.strip() for x in value.values()):
        raise ValueError("Invalid bilingual text")


def array(value):
    if type(value) is not list:
        raise ValueError("Invalid public array")


def sentence(value):
    if type(value) is not str or not value.strip():
        raise ValueError("Invalid public text")


def validate_report(report):
    keys(report, {"report_id", "kind", "question", "scope", "summary", "series", "sources", "notes"})
    if type(report["report_id"]) is not str or not re.fullmatch(r"r[1-9][0-9]*", report["report_id"]):
        raise ValueError("Invalid public alias")
    keys(report["scope"], SCOPE_KEYS)
    for value in report["scope"].values():
        sentence(value)
    sentence(report["question"])
    if report["kind"] != "trade-query-v1" or report["scope"]["flow"] not in {"import", "export"}:
        raise ValueError("Unexpected report kind")
    expected_metric = "total_export_fas_usd" if report["scope"]["flow"] == "export" else "import_value_consumption_usd"
    all_partner = "ALL_DESTINATIONS" if report["scope"]["flow"] == "export" else "ALL_ORIGINS"
    if report["scope"]["metric"] != expected_metric or report["scope"]["partner"] not in {"CHINA", all_partner}:
        raise ValueError("Invalid statistical basis")
    keys(report["summary"], SUMMARY_KEYS)
    rows = report["series"]
    if type(rows) is not list or len(rows) < 2:
        raise ValueError("Missing saved series")
    for row in rows:
        keys(row, {"month", "status", "value_usd"})
        if type(row["month"]) is not str or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", row["month"]) or row["status"] != "observed" or type(row["value_usd"]) is not int or row["value_usd"] < 0:
            raise ValueError("Invalid saved row")
    if len({r["month"] for r in rows}) != len(rows) or [r["month"] for r in rows] != sorted(r["month"] for r in rows):
        raise ValueError("Invalid saved month order")
    summary, scope = report["summary"], report["scope"]
    for name in ("latest_value_usd", "period_total_usd", "month_change_usd"):
        if type(summary[name]) is not int:
            raise ValueError("Invalid summary number")
    if (summary["complete_window"] is not True or summary["latest_month"] != rows[-1]["month"]
            or summary["latest_value_usd"] != rows[-1]["value_usd"]
            or summary["period_total_usd"] != sum(r["value_usd"] for r in rows)
            or scope["start_month"] != rows[0]["month"] or scope["end_month"] != rows[-1]["month"]
            or summary["previous_month"] != rows[-2]["month"]
            or summary["month_change_usd"] != rows[-1]["value_usd"] - rows[-2]["value_usd"]):
        raise ValueError("Saved summary mismatch")
    array(report["sources"]); array(report["notes"])
    for note in report["notes"]:
        sentence(note)
    for link in report["sources"]:
        url(link)


def validate_case(case):
    keys(case, {"schema", "id", "kind", "turns", "reports", "reader_view", "evidence_meta", "guard"})
    scan(case)
    for name in ("schema", "id", "kind"):
        sentence(case[name])
    array(case["reports"]); array(case["turns"])
    if case["schema"] != "tradeintel-public-case-v1" or case["id"] not in IDS:
        raise ValueError("Invalid public case")
    expected_kind = "edited_evidence_report" if case["id"] == IDS[2] else "guarded_run" if case["id"] == IDS[3] else "real_agent_run"
    if case["kind"] != expected_kind:
        raise ValueError("Wrong case identity")
    aliases = set()
    for report in case["reports"]:
        validate_report(report)
        if report["report_id"] in aliases:
            raise ValueError("Duplicate report alias")
        aliases.add(report["report_id"])
    if case["id"] in EXPECTED and [r["summary"]["latest_value_usd"] for r in case["reports"]] != EXPECTED[case["id"]]:
        raise ValueError("Frozen amount mismatch")
    for turn in case["turns"]:
        keys(turn, {"role", "text", "steps", "reports", "primary_report"})
        bilingual(turn["text"])
        sentence(turn["role"]); array(turn["reports"]); array(turn["steps"])
        if any(type(alias) is not str for alias in turn["reports"]) or (turn["primary_report"] is not None and type(turn["primary_report"]) is not str):
            raise ValueError("Invalid turn alias type")
        if turn["role"] not in {"user", "assistant"} or not set(turn["reports"]) <= aliases or turn["primary_report"] not in aliases | {None}:
            raise ValueError("Invalid turn/report binding")
        if turn["role"] == "assistant" and turn["text"]["en"] != translate_saved_answer(turn["text"]["zh"]):
            raise ValueError("Saved answer translation mismatch")
        for step in turn["steps"]:
            keys(step, {"label", "status"}); bilingual(step["label"])
            sentence(step["status"])
            if step["status"] not in {"ok", "completed", "unavailable"}:
                raise ValueError("Invalid step status")
    if case["kind"] != "real_agent_run" and case["reports"]:
        raise ValueError("Invented report")
    if case["kind"] == "edited_evidence_report" and case["turns"]:
        raise ValueError("Invented policy dialogue")
    guard = case["guard"]
    if case["id"] == IDS[3]:
        keys(guard, {"requested_month", "latest_available_month", "model_month_selection"})
        if guard != {"requested_month": "2026-08", "latest_available_month": "2026-07", "model_month_selection": "rejected"}:
            raise ValueError("Invalid missing-month boundary")
    elif guard is not None:
        raise ValueError("Unexpected guard")
    view = case["reader_view"]
    if view is not None:
        keys(view, {"facts", "unanswered", "method"})
        array(view["facts"]); array(view["unanswered"])
        for fact in view["facts"]:
            keys(fact, {"report_id", "text", "text_en"})
            for value in fact.values(): sentence(value)
            if fact["report_id"] not in aliases:
                raise ValueError("Invalid fact alias")
        for missing in view["unanswered"]:
            keys(missing, {"text", "text_en"})
            for value in missing.values(): sentence(value)
        keys(view["method"], {"text", "text_en"})
        for value in view["method"].values(): sentence(value)
    evidence = case["evidence_meta"]
    keys(evidence, {"original_sha256", "data_versions", "official_urls"})
    for value in evidence.values(): array(value)
    if any(type(x) is not str or not re.fullmatch(r"[0-9a-f]{64}", x) for x in evidence["original_sha256"] + evidence["data_versions"]):
        raise ValueError("Invalid evidence digest")
    for link in evidence["official_urls"]:
        url(link)


def catalog():
    definitions = [
        ("大豆进口，接着问出口", "Soybean imports, then exports", "先问大豆进口，再追问出口，查看两个方向的图表和金额。", "An import question followed by an export question, with separate charts and figures.", "real_agent_run", "2026-09-30", "模型选择查询工具，程序计算金额与摘要。以下保留当时的问答和报告。", "The model selected query tools; the program calculated figures and summaries. The saved exchange and reports are shown below."),
        ("豆油进口查询", "Soybean oil imports", "按“豆油”查找对应商品，查看十二个月的进口变化。", "Look up soybean oil by name and view twelve months of import values.", "real_agent_run", "2026-09-30", "该案例查询豆油（1507），不是原料大豆（1201）。", "This case queries soybean oil (1507), not raw soybeans (1201)."),
        ("钨和光伏材料：政策与进口", "Tungsten and solar materials", "五类商品分别展示公告背景、进口金额和中国来源份额。", "An archived notice alongside import values and China-origin shares for five product codes.", "edited_evidence_report", "2026-10-01", "这是一份资料编辑报告。公告中的附加税率与现行全部税率不同；图表展示进口金额，不计算政策效果。", "An edited report. The notice gives additional duties, not current total duties; the charts show import values rather than policy effects."),
        ("所问月份还没有数据", "The requested month is not available", "所问月份未收录，说明缺口而不是改查另一月份。", "Explain a missing month rather than substitute another one.", "guarded_run", "2026-09-30", "提问日期为2026-09-29。模型尝试改查7月，被程序拦截；本次没有生成报告。", "The question was asked on 29 September 2026. The model tried July instead; the program blocked that request and no report was generated."),
    ]
    return {"schema": "tradeintel-public-cases-v1", "cases": [
        {"id": cid, "title": {"zh": d[0], "en": d[1]}, "description": {"zh": d[2], "en": d[3]},
         "kind": d[4], "recorded_on": d[5], "data_cutoff": "2026-07",
         "model": None if d[4] == "edited_evidence_report" else {"request_name": "deepseek-flash", "reasoning": "high"},
         "limitations": {"zh": d[6], "en": d[7]}, "asset": f"cases/{cid}.json"}
        for cid, d in zip(IDS, definitions)]}


def validate_catalog(index):
    keys(index, {"schema", "cases"}); scan(index)
    if index["schema"] != "tradeintel-public-cases-v1" or [c["id"] for c in index["cases"]] != list(IDS):
        raise ValueError("Invalid case manifest")
    for item in index["cases"]:
        keys(item, {"id", "title", "description", "kind", "recorded_on", "data_cutoff", "model", "limitations", "asset"})
        for name in ("title", "description", "limitations"):
            bilingual(item[name])
        if item["asset"] != f"cases/{item['id']}.json":
            raise ValueError("Invalid case asset")
        if item["model"] is not None:
            keys(item["model"], {"request_name", "reasoning"})
    if index != catalog():
        raise ValueError("Frozen case labels differ")


def project_report(root, rid, alias):
    record = load_record(root, rid)  # Existing hash/schema checks, never loads keys.
    source = record["report"]
    result = {"report_id": alias, "kind": source["kind"], "question": source["question"],
              "scope": {key: source["scope"][key] for key in SCOPE_KEYS},
              "summary": {key: source["summary"][key] for key in SUMMARY_KEYS},
              "series": [{key: row[key] for key in ("month", "status", "value_usd")} for row in source["series"]],
              "sources": source["sources"], "notes": source["notes"]}
    validate_report(result)
    return result, source["scope"]["dataset_version"]


def make_cases(root):
    labels = {"get_trade_coverage": ("检查可用月份", "Check available months"),
              "search_products": ("查找商品范围", "Find product scope"),
              "query_trade": ("查询贸易金额", "Query trade values"),
              "finish": ("保存查询结果", "Save the result")}
    questions = {"最近美国大豆进口有什么变化？": "How have recent U.S. soybean imports changed?",
                 "出口呢？": "What about exports?", "美国豆油进口最近怎样？": "How are recent U.S. soybean oil imports?",
                 "上个月美国大豆进口额是多少？": "What was the value of U.S. soybean imports last month?"}
    result = []
    for cid in IDS:
        case = {"schema": "tradeintel-public-case-v1", "id": cid,
                "kind": next(c["kind"] for c in catalog()["cases"] if c["id"] == cid),
                "turns": [], "reports": [], "reader_view": None,
                "evidence_meta": {"original_sha256": [], "data_versions": [], "official_urls": []}, "guard": None}
        if cid == IDS[2]:
            data = read_json(root / "web/design-preview/data.json")
            case["evidence_meta"] = {"original_sha256": [sha(root / "web/design-preview/data.json"), data["source_sha256"]],
                                     "data_versions": [data["data_version"]], "official_urls": ["https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1", "https://www.census.gov/trade/downloads/2026/Merch/im_m/IMDB2607.ZIP"]}
        else:
            sid = SESSIONS[cid]; session_path = root / f".local/trade-agent-sessions/{sid}.json"
            state = read_json(session_path)
            if state.get("schema") != "trade-agent-session-v1" or state.get("session_id") != sid:
                raise ValueError("Saved case session mismatch")
            case["evidence_meta"]["original_sha256"].append(sha(session_path))
            aliases = {}
            for index, rid in enumerate(REPORTS.get(cid, []), 1):
                alias = f"r{index}"; aliases[rid] = alias
                report, version = project_report(root, rid, alias); case["reports"].append(report)
                case["evidence_meta"]["data_versions"].append(version)
                case["evidence_meta"]["original_sha256"].append(sha(root / f".local/trade-reports/{rid}.json"))
                case["evidence_meta"]["official_urls"] += report["sources"]
            for turn in state["turns"]:
                question = turn["question"]
                case["turns"].append({"role": "user", "text": {"zh": question, "en": questions[question]},
                                       "steps": [], "reports": [], "primary_report": None})
                if cid != IDS[3] and (turn["status"] != "completed" or turn.get("message_kind") != "program_summary_v1"):
                    raise ValueError("Unreviewed case text")
                if cid == IDS[3]:
                    if turn["status"] != "needs_clarification" or turn["report_ids"]:
                        raise ValueError("Missing-month case changed")
                en = translate_saved_answer(turn["message"])
                case["turns"].append({"role": "assistant", "text": {"zh": turn["message"], "en": en},
                                       "steps": [{"label": dict(zip(("zh", "en"), labels[c["tool"]])), "status": c["status"]} for c in turn["tool_calls"]],
                                       "reports": [aliases[rid] for rid in turn["report_ids"]],
                                       "primary_report": aliases.get(turn.get("primary_report_id"))})
            if case["reports"]:
                view = build_reader_view(" ".join(t["question"] for t in state["turns"]), case["reports"])
                case["reader_view"] = {"facts": [{key: f[key] for key in ("report_id", "text", "text_en")} for f in view["facts"]],
                                       "unanswered": view["unanswered"], "method": view["method"]}
            else:
                case["guard"] = {"requested_month": "2026-08", "latest_available_month": "2026-07", "model_month_selection": "rejected"}
        for field in ("original_sha256", "data_versions", "official_urls"):
            case["evidence_meta"][field] = sorted(set(case["evidence_meta"][field]))
        validate_case(case); result.append(case)
    return result


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def verify(site):
    expected = set(ASSETS) | {"data.json", "cases/index.json"} | {f"cases/{cid}.json" for cid in IDS}
    actual = {str(p.relative_to(site)) for p in site.rglob("*") if p.is_file()}
    if actual != expected or any(p.is_symlink() for p in site.rglob("*")):
        raise ValueError("Static asset allowlist mismatch")
    html = (site / "index.html").read_text()
    if html.count('data-runtime="showcase"') != 1 or 'src="live.js"' in html or 'id="question-form"' in html or 'id="open-model-settings"' in html:
        raise ValueError("Public runtime isolation failed")
    validate_catalog(read_json(site / "cases/index.json"))
    originals = {c["id"]: c for c in make_cases(ROOT)}
    if {name: sha(ROOT / name) for name in SOURCES} != SOURCES:
        raise ValueError("Frozen source changed")
    for cid in IDS:
        case = read_json(site / f"cases/{cid}.json")
        if case["id"] != cid:
            raise ValueError("Case file identity mismatch")
        validate_case(case)
        if case != originals[cid]:
            raise ValueError("Public case differs from saved source projection")
    data = read_json(site / "data.json"); keys(data, {"data_version", "note", "rows", "source_sha256"}); scan(data)
    if len(data["rows"]) != 30:
        raise ValueError("Policy data count mismatch")
    for row in data["rows"]:
        keys(row, {"product", "name", "period", "world", "china"})
        if type(row["world"]) is not int or type(row["china"]) is not int or not 0 <= row["china"] <= row["world"]:
            raise ValueError("Invalid policy amount")
    original_data = read_json(ROOT / "web/design-preview/data.json")
    if data != {k: original_data[k] for k in ("data_version", "note", "rows", "source_sha256")}:
        raise ValueError("Policy data differs from saved source")
    # Audit digests include assets; verification never rewrites a manifest to pass.
    audit = read_json(site.parent / "audit/manifest.json")
    if set(audit["assets"]) != expected or any(sha(site / name) != digest for name, digest in audit["assets"].items()):
        raise ValueError("Candidate digest mismatch")
    return {"case_count": 4, "asset_count": len(actual), "status": "verified"}


def build(root, site):
    if site.exists() or site.parent.joinpath("audit").exists():
        raise ValueError("Output already exists; use a new run directory")
    before = {name: sha(root / name) for name in SOURCES}
    if before != SOURCES:
        raise ValueError("Frozen source changed")
    cases = make_cases(root)
    data = read_json(root / "web/design-preview/data.json")
    public_data = {key: data[key] for key in ("data_version", "note", "rows", "source_sha256")}
    scan(public_data)
    site.mkdir(parents=True)
    for name in ASSETS:
        source = root / "web/design-preview" / name
        if source.is_symlink():
            raise ValueError("Unsafe source asset")
        content = source.read_bytes()
        if name == "index.html":
            html = content.decode()
            marker = '<script type="module" src="live.js"></script>'
            if html.count(marker) != 1:
                raise ValueError("Local script marker changed")
            start, end = html.index('<section id="workspace"'), html.index('<section id="report"')
            html = html[:start] + html[end:]
            content = html.replace(marker, "", 1).encode()
        target = site / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    save_json(site / "data.json", public_data); save_json(site / "cases/index.json", catalog())
    for case in cases:
        save_json(site / f"cases/{case['id']}.json", case)
    after = {name: sha(root / name) for name in SOURCES}
    if before != after:
        raise ValueError("Sources changed during export")
    audit = {"sources_before": before, "sources_after": after,
             "assets": {str(p.relative_to(site)): sha(p) for p in site.rglob("*") if p.is_file()},
             "model_configuration_evidence": ["docs/handoff/runs/20260930-REAL-WEB-TWO-TURN-ACCEPTANCE.zh-CN.md", "docs/handoff/runs/20260930-TRADE-AGENT-SUPPLEMENTAL-LIVE.zh-CN.md"]}
    save_json(site.parent / "audit/manifest.json", audit)
    return verify(site)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.output and args.verify:
        parser.error("Choose build or verify")
    if args.verify:
        result = verify(args.verify.resolve())
    else:
        site = args.output or ROOT / f"tmp/handoff-runs/showcase-{datetime.now():%Y%m%d-%H%M%S-%f}/site"
        result = build(ROOT, site.resolve()); result["site"] = str(site.resolve())
    print(json.dumps(result))


if __name__ == "__main__":
    main()
