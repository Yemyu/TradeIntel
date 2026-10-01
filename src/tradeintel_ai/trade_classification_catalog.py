"""Versioned Census commodity names, kept separate from measured trade values.

HSDESC/CONCORD are the classification files shipped inside each monthly
Census archive. Chinese names below are *search aids*, never classification
authority; the complete US description is always shown before a query.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import zipfile
import csv
from pathlib import Path

from .trade_data_repository import TradeDataError, TradeDataRepository, _sha256
from .trade_export_repository import ExportDataRepository


CATALOG_DIR = Path("data/processed/trade_classification")
MOF_URL = "https://gss.mof.gov.cn/gzdt/zhengcefabu/202512/t20251231_3981044.htm"
MOF_PDF_SHA256 = "76af4db0b3af966ef4f95f4ffc6b4b2e34f1a95ef47f68e7299670a18b337d57"
# Confirmed against the 2026 MOF tariff headings (PDF pages are zero-based).
# These names help locate US headings; they do not assign a Chinese tariff rate.
ZH_HS4 = {
    "0901": ("咖啡，不论是否焙炒或浸除咖啡碱；咖啡豆荚及咖啡豆皮；含咖啡的咖啡代用品", 157, ("咖啡",)),
    "0902": ("茶，不论是否加香料", 158, ("茶", "茶叶")),
    "1001": ("小麦及混合麦", 167, ("小麦",)),
    "1005": ("玉米", 168, ("玉米",)),
    "1201": ("大豆，不论是否破碎", 177, ("大豆", "黄豆")),
    "2101": ("咖啡、茶、马黛茶的浓缩精汁及以其为基本成分或以咖啡、茶、马黛茶为基本成分的制品；烘焙菊苣和其他烘焙咖啡代用品及其浓缩精汁", 250,
             ("咖啡", "茶")),
    "5201": ("未梳的棉花", 645, ("棉花",)),
    "5202": ("废棉（包括废棉纱线及回收纤维）", 645, ("棉花", "废棉")),
    "5203": ("已梳的棉花", 645, ("棉花",)),
}
# Everyday words that do not appear verbatim in an official heading. A broad
# word maps to several plausible headings so the user, not the parser, narrows it.
ZH_SEARCH_SYNONYMS = {
    "稻米": ("1006",),
    "稻谷": ("1006",),
    "大米": ("1006",),
    "汽车": ("8702", "8703", "8704"),
    "乘用车": ("8703",),
    "轿车": ("8703",),
    "卡车": ("8704",),
    "手机": ("8517",),
    "电脑": ("8471",),
    "计算机": ("8471",),
    "原油": ("2709",),
}

# Reviewed against the complete Census headings, not against measured values.
# Longer processed names are consumed before their shorter everyday names.
REVIEWED_HEADINGS = {
    "1801": (r"可可豆|\bcocoa\s+beans?\b", "可可豆整组，包括生豆、焙炒豆及破碎豆。", "The whole cocoa-bean heading includes raw, roasted and broken beans."),
    "2204": (r"葡萄酒|\bwine\b", "葡萄酒整组，包括加强酒和本税目所列葡萄汁。", "The whole wine heading includes fortified wines and grape must covered by this heading."),
    "4001": (r"天然橡胶|\bnatural\s+rubber\b", "按4001整组统计，除天然橡胶外还包括巴拉塔胶、古塔波胶等其他天然胶；不是仅天然橡胶的金额。", "Heading 4001 includes natural rubber and other natural gums such as balata and gutta-percha; these values are not a natural-rubber-only subtotal."),
    "8101": (r"钨及其制品|钨制品|\btungsten\s+articles\b", "按8101整组统计，包括钨及其制品、废碎料；不包括2611钨矿砂。", "Heading 8101 covers tungsten and articles thereof, including waste and scrap; it excludes heading 2611 tungsten ores."),
    "2611": (r"钨矿砂|钨矿石|\btungsten\s+ores?(?:\s+and\s+concentrates)?\b", "钨矿砂及其精矿整组，不是钨金属制品。", "The whole tungsten-ores-and-concentrates heading, not tungsten metal articles."),
    "2307": (r"葡萄酒渣|\bwine\s+lees\b", "葡萄酒渣及粗酒石整组，不是葡萄酒。", "The whole wine-lees-and-argol heading, not wine."),
}
_PROCESSED_RUBBER = re.compile(r"天然橡胶(?:轮胎|化学衍生物)|\bnatural\s+rubber\s+(?:tyres?|tires?|derivatives?)\b", re.I)
_PROCESSED_BEANS = re.compile(r"可可豆(?:油|粉|提取物)|\bcocoa\s+beans?\s+(?:oil|powder|extracts?)\b", re.I)
_PROCESSED_WINE = re.compile(r"葡萄酒(?:醋|瓶)|\bwine\s+(?:vinegar|bottles?)\b", re.I)


def reviewed_heading_matches(text: str) -> set[str]:
    """Match reviewed phrases consistently for discovery and request guards."""
    remaining = text
    for processed in (_PROCESSED_RUBBER, _PROCESSED_BEANS, _PROCESSED_WINE):
        remaining = processed.sub(" ", remaining)
    matches = []
    for code, (pattern, _, _) in REVIEWED_HEADINGS.items():
        matches.extend((m.start(), m.end(), code) for m in re.finditer(pattern, remaining, re.I))
    occupied: list[tuple[int, int]] = []
    codes = set()
    for start, end, code in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0])):
        if not any(start < b and end > a for a, b in occupied):
            occupied.append((start, end)); codes.add(code)
    return codes


def validate_reviewed_heading_scope(question: str, code: str) -> None:
    """Do not let a shortened model search erase explicit processing/subsets."""
    explicit = bool(re.search(rf"(?:hs\s*\d*|税号|编码)\s*[:：]?\s*{code}(?!\d)", question, re.I))
    matches = reviewed_heading_matches(question)
    if ((code == "1801" and _PROCESSED_BEANS.search(question)) or
            (code == "2204" and _PROCESSED_WINE.search(question))):
        raise TradeDataError("加工品不能用原料整组金额代替，请查询实际商品或澄清。")
    if code in {"2611", "8101"} and re.search(r"钨|\btungsten\b", question, re.I) and not matches & {"2611", "8101"} and not explicit:
        raise TradeDataError("钨可能指矿砂或钨及其制品，请先澄清商品范围。")
    if code == "4001":
        if _PROCESSED_RUBBER.search(question):
            raise TradeDataError("加工品不能用4001天然胶整组金额代替，请查询相应加工品或澄清。")
        if re.search(r"橡胶|\brubber\b", question, re.I) and "4001" not in matches and not explicit:
            raise TradeDataError("橡胶范围不明确，不能默认只查天然胶整组。")
        if re.search(r"排除其他(?:天然)?胶|不含其他(?:天然)?胶|[仅只](?:统计|看|查)?天然橡胶|natural\s+rubber\s+only|only\s+natural\s+rubber|excluding\s+other\s+(?:natural\s+)?gums", question, re.I):
            raise TradeDataError("4001包含其他天然胶，不能代替仅天然橡胶的子集。")
    if code == "8101" and re.search(r"不含(?:钨)?废(?:碎)?料|排除(?:钨)?废(?:碎)?料|excluding\s+(?:waste|scrap)|without\s+(?:waste|scrap)", question, re.I):
        raise TradeDataError("8101包含废碎料，不能代替排除废料的子集。")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _member(archive: zipfile.ZipFile, name: str) -> str:
    found = [item for item in archive.namelist()
             if item.casefold() == name.casefold()]
    if len(found) != 1:
        raise TradeDataError(f"官方原包缺少唯一的 {name}")
    return found[0]


def _fixed_rows(raw: bytes, width: int, kind: str) -> dict[str, str]:
    result = {}
    for line in raw.splitlines():
        if len(line) != width:
            raise TradeDataError(f"{kind} 定长记录长度不符：{len(line)}")
        code = line[:6].decode("ascii").strip() if kind == "HSDESC" else line[:10].decode("ascii")
        pattern = r"\d{2}|\d{4}|\d{6}" if kind == "HSDESC" else r"\d{10}"
        if not re.fullmatch(pattern, code):
            raise TradeDataError(f"{kind} 商品编码无效：{code}")
        if code in result:
            raise TradeDataError(f"{kind} 商品编码重复：{code}")
        start = 6 if kind == "HSDESC" else 10
        label = line[start:start + 150].decode("latin-1").strip()
        if not label:
            raise TradeDataError(f"{kind} 商品描述为空：{code}")
        result[code] = label
    return result


def build_catalog(root: Path, *, flows: tuple[str, ...] = ("import", "export")) -> dict:
    """Rebuild from audited monthly releases; never promote raw-only months."""
    root = Path(root)
    months = []
    dataset_versions = {}
    for flow in flows:
        if flow not in {"import", "export"}:
            raise TradeDataError("分类目录方向无效")
        repo = TradeDataRepository(root) if flow == "import" else ExportDataRepository(root)
        release = repo.catalog()
        dataset_versions[flow] = release["dataset_version"]
        for entry in release["months"]:
            if entry["status"] != "queryable_aggregate":
                continue
            month = entry.get("month_key") or entry["month"]
            source_name = entry["source_file_name"]
            source = root / ("data/raw/trade-detail" if flow == "import" else "data/raw/trade-export") / source_name
            if not source.is_file() or _sha256(source) != entry["source_sha256"]:
                raise TradeDataError(f"{flow} {month} 官方原包缺失或摘要不符")
            with zipfile.ZipFile(source) as archive:
                group_name, item_name = _member(archive, "HSDESC.TXT"), _member(archive, "CONCORD.TXT")
                group_raw, item_raw = archive.read(group_name), archive.read(item_name)
            groups = _fixed_rows(group_raw, 206, "HSDESC")
            items = _fixed_rows(item_raw, 235, "CONCORD")
            column = "hts10" if flow == "import" else "scheduleb10"
            published_codes: set[str] = set()
            with (root / entry["processed_file"]).open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                if column not in (reader.fieldnames or []):
                    raise TradeDataError(f"{flow} {month} 加工数据缺少商品编码列")
                for row in reader:
                    published_codes.add(row[column])
            unlisted = published_codes - set(items)
            if unlisted:
                raise TradeDataError(f"{flow} {month} 加工数据中有未列入原包 CONCORD 的商品编码")
            content = {"flow": flow, "month": month, "groups": groups, "items": items}
            compressed = gzip.compress(_canonical(content), mtime=0)
            content_sha = _hash_bytes(compressed)
            rel = CATALOG_DIR / "monthly" / f"{flow}_{month}_{content_sha[:12]}.json.gz"
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file() or _sha256(dest) != content_sha:
                temp = dest.with_suffix(".tmp")
                temp.write_bytes(compressed)
                temp.replace(dest)
            months.append({"flow": flow, "month": month, "path": rel.as_posix(),
                           "sha256": content_sha, "source_url": entry["source_url"],
                           "source_sha256": entry["source_sha256"],
                           "members": {"HSDESC.TXT": {"name": group_name, "sha256": _hash_bytes(group_raw)},
                                       "CONCORD.TXT": {"name": item_name, "sha256": _hash_bytes(item_raw)}},
                           "group_count": len(groups), "item_count": len(items),
                           "published_code_count": len(published_codes)})
    months.sort(key=lambda row: (row["flow"], row["month"]))
    zh_path = root / CATALOG_DIR / "zh_hs4_2026.json"
    zh_index = json.loads(zh_path.read_text(encoding="utf-8")) if zh_path.is_file() else None
    if zh_index and (zh_index.get("schema") != "mof-2026-hs4-search-only-v1" or
                     zh_index.get("source_pdf_sha256") != MOF_PDF_SHA256 or
                     not isinstance(zh_index.get("headings"), dict)):
        raise TradeDataError("中文名称索引的来源或格式未通过核验")
    body = {"schema": "census-classification-v1", "dataset_versions": dataset_versions,
            "months": months, "zh_source_url": MOF_URL,
            "zh_source_pdf_sha256": MOF_PDF_SHA256,
            "zh_coverage_hs4_codes": sorted(zh_index["headings"] if zh_index else ZH_HS4),
            "zh_index_sha256": _sha256(zh_path) if zh_index else None}
    body["catalog_version"] = _hash_bytes(_canonical(body))
    dest = root / CATALOG_DIR / "manifest.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".tmp")
    temp.write_bytes(json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    temp.replace(dest)
    return body


class ClassificationCatalog:
    def __init__(self, root: Path):
        self.root = Path(root)
        path = self.root / CATALOG_DIR / "manifest.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TradeDataError("官方商品目录尚未构建或已损坏") from exc
        version = manifest.get("catalog_version")
        unsigned = {key: val for key, val in manifest.items() if key != "catalog_version"}
        if version != _hash_bytes(_canonical(unsigned)) or manifest.get("schema") != "census-classification-v1":
            raise TradeDataError("商品目录版本摘要无效")
        for flow, expected in manifest["dataset_versions"].items():
            repo = TradeDataRepository(self.root) if flow == "import" else ExportDataRepository(self.root)
            if repo.catalog()["dataset_version"] != expected:
                raise TradeDataError("商品目录与当前贸易数据版本不一致，请重建目录")
        self.manifest = manifest
        self.entries = {(row["flow"], row["month"]): row for row in manifest["months"]}
        self.zh_headings = {}
        if manifest.get("zh_index_sha256"):
            zh_path = self.root / CATALOG_DIR / "zh_hs4_2026.json"
            if not zh_path.is_file() or _sha256(zh_path) != manifest["zh_index_sha256"]:
                raise TradeDataError("中文名称索引缺失或摘要不符")
            zh_index = json.loads(zh_path.read_text(encoding="utf-8"))
            if (zh_index.get("schema") != "mof-2026-hs4-search-only-v1" or
                    zh_index.get("source_pdf_sha256") != MOF_PDF_SHA256):
                raise TradeDataError("中文名称索引的来源未通过核验")
            self.zh_headings = zh_index["headings"]

    @property
    def version(self) -> str:
        return self.manifest["catalog_version"]

    def month(self, flow: str, month: str) -> dict:
        entry = self.entries.get((flow, month))
        if not entry:
            raise TradeDataError(f"{flow} {month} 没有对应的官方商品目录")
        path = self.root / entry["path"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise TradeDataError(f"{flow} {month} 商品目录文件摘要不符")
        try:
            content = json.loads(gzip.decompress(path.read_bytes()))
        except (OSError, ValueError) as exc:
            raise TradeDataError("商品目录压缩文件无效") from exc
        if content.get("flow") != flow or content.get("month") != month:
            raise TradeDataError("商品目录月份或方向与清单不一致")
        return content

    def latest_month(self, flow: str) -> str:
        months = [month for (item_flow, month) in self.entries if item_flow == flow]
        if not months:
            raise TradeDataError("所选方向没有已发布的商品目录")
        return max(months)

    def candidate(self, flow: str, month: str, code: str) -> dict | None:
        if flow not in {"import", "export"} or not re.fullmatch(r"\d{4}|\d{6}|\d{8}|\d{10}", code):
            return None
        if len(code) == 8 and flow != "import":
            return None
        content = self.month(flow, month)
        if len(code) == 8:
            children = [name for key, name in content["items"].items() if key.startswith(code)]
            description = (f"HTS8 {code}: all matching 10-digit entries; "
                           f"examples: {'; '.join(children[:3])}" if children else None)
        else:
            description = content["groups"].get(code) if len(code) < 10 else content["items"].get(code)
        if not description:
            return None
        entry = self.entries[(flow, month)]
        zh = ZH_HS4.get(code)
        extracted = self.zh_headings.get(code) if len(code) == 4 else None
        return {"id": f"{flow}:{code}", "flow": flow,
                "level": "HS4" if len(code) == 4 else "HS6" if len(code) == 6 else "HTS8" if len(code) == 8 else
                         "HTS10" if flow == "import" else "ScheduleB10",
                "code": code, "official_en": description,
                "description_kind": "derived_from_10_digit_entries" if len(code) == 8 else "official",
                "zh_label": zh[0] if zh else extracted["label"] if extracted else None,
                "zh_source_url": MOF_URL if zh or extracted else None,
                "zh_pdf_page": zh[1] + 1 if zh else extracted["pdf_page"] if extracted else None,
                "zh_review_status": "spot_checked" if zh else "machine_extracted" if extracted else None,
                "month": month, "source_url": entry["source_url"],
                "child_codes": sum(key.startswith(code) for key in content["items"]),
                "catalog_version": self.version}

    def search(self, question: str, flow: str, *, limit: int = 8) -> list[dict]:
        if flow not in {"import", "export", "both"}:
            return []
        # Both directions can only use the shared HS4/HS6 headings.
        primary = "import" if flow == "both" else flow
        month = self.latest_month(primary)
        content = self.month(primary, month)
        found: dict[str, int] = {}
        for code in reviewed_heading_matches(question):
            if code in content["groups"]:
                found[code] = 200
        for code, (_, _, aliases) in ZH_HS4.items():
            if code in content["groups"] and any(alias in question for alias in aliases):
                found[code] = 100 + max(len(alias) for alias in aliases if alias in question)
        residual = re.sub(
            r"20\d{2}年|\d{1,2}月|最近|最新|美国|中国|进口|出口|进出口|贸易|商品|数据|金额|"
            r"情况|变化|走势|趋势|如何|怎么样|有什么|有何|多少|请问|查询|查一下|看一下|"
            r"我想知道|想了解|今年|去年|本月|上月|同比|环比|的|和|与|及|从|到|对|在|是|啊|呢",
            " ", question)
        chinese_terms = [term for term in re.findall(r"[\u4e00-\u9fff]{2,12}", residual)
                         if 2 <= len(term) <= 12]
        exact_synonym_codes = set()
        for word, codes in ZH_SEARCH_SYNONYMS.items():
            if word in chinese_terms:
                for code in codes:
                    if code in content["groups"]:
                        found[code] = max(found.get(code, 0), 90 + len(word))
                        exact_synonym_codes.add(code)
        def positive_match(term: str, label: str) -> bool:
            for match in re.finditer(re.escape(term), label):
                after = label[match.end():match.end() + 4]
                before = label[max(0, match.start() - 3):match.start()]
                if "除外" not in after and "不含" not in before and "不包括" not in before:
                    return True
            return False

        for code, entry in self.zh_headings.items():
            if exact_synonym_codes and len(chinese_terms) == 1 and chinese_terms[0] in ZH_SEARCH_SYNONYMS:
                if code not in exact_synonym_codes:
                    continue
            if code in content["groups"] and any(positive_match(term, entry["label"]) for term in chinese_terms):
                found[code] = max(found.get(code, 0), max(
                    60 + len(term) + (20 if entry["label"].startswith(term) else 0)
                    for term in chinese_terms if positive_match(term, entry["label"])))
        english = set(re.findall(r"[a-z]{3,}", question.lower())) - {
            "american", "united", "states", "trade", "import", "imports", "export", "exports",
            "recent", "recently", "latest", "change", "changed", "changes", "trend", "trends",
            "what", "about", "from", "with", "last", "month", "months", "year", "years",
            "have", "has", "how", "much", "over", "time", "the", "and"}
        # A single everyday name that exactly names an official HS4 heading
        # should not also return unrelated headings that mention it in an
        # exclusion or a compound product (for example RICE PAPER).
        exact_english_codes = {
            code for code, label in content["groups"].items()
            if len(code) == 4 and len(english) == 1 and label.casefold() == next(iter(english))
        }
        for code, label in content["groups"].items():
            if len(code) != 4 or code[:2] in {"98", "99"}:
                continue
            if exact_english_codes and code not in exact_english_codes:
                continue
            words = set(re.findall(r"[a-z]{3,}", label.lower()))
            score = sum(10 + len(word) for word in english & words)
            if score:
                found[code] = max(found.get(code, 0), score)
        numeric = set(re.findall(r"(?<!\d)(?:\d{4}|\d{6}|\d{8}|\d{10})(?!\d)", question))
        for code in numeric:
            if (code in content["groups"] or code in content["items"] or
                    (len(code) == 8 and flow == "import" and any(key.startswith(code) for key in content["items"]))):
                found[code] = 1000
        results = []
        for code, _ in sorted(found.items(), key=lambda item: (-item[1], item[0])):
            if flow == "both":
                if len(code) > 6 or code not in self.month("export", self.latest_month("export"))["groups"]:
                    continue
            candidate = self.candidate(primary, month, code)
            if candidate:
                candidate["flow"] = flow
                candidate["id"] = f"{flow}:{code}"
                results.append(candidate)
            if len(results) >= limit:
                break
        return results

    def validate_choice(self, product_id: str, version: str, flow: str, months: list[str]) -> dict:
        if version != self.version:
            raise TradeDataError("商品目录版本已变化，请重新选择商品")
        if not isinstance(product_id, str) or not re.fullmatch(r"(?:import|export|both):(\d{4}|\d{6}|\d{8}|\d{10})", product_id):
            raise TradeDataError("商品选择编号无效")
        selected_flow, code = product_id.split(":")
        if selected_flow != flow or (flow == "both" and len(code) > 6):
            raise TradeDataError("商品编码与贸易方向不匹配")
        descriptions: dict[str, set[str]] = {}
        for month in months:
            for direction in (("import", "export") if flow == "both" else (flow,)):
                candidate = self.candidate(direction, month, code)
                if not candidate:
                    raise TradeDataError(f"{direction} {month} 商品编码不在官方目录，请重新选择范围")
                descriptions.setdefault(direction, set()).add(candidate["official_en"])
        if any(len(values) != 1 for values in descriptions.values()):
            raise TradeDataError("所选月份的商品描述发生变化，不能直接合并为同一趋势")
        return self.candidate("import" if flow == "both" else flow, months[-1], code)
