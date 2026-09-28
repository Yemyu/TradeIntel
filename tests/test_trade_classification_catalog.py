import csv
import hashlib
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.tradeintel_ai.trade_classification_catalog import ClassificationCatalog, MOF_PDF_SHA256, build_catalog
from src.tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question


FIELDS = ["year", "month", "hts10", "hts8", "china_import_value_consumption_usd",
          "all_origin_import_value_consumption_usd", "china_observed", "all_origin_observed",
          "source_sha256"]


def _row(code: str, description: str, width: int) -> bytes:
    prefix = code.ljust(6) if width == 206 else code
    return (prefix + description.ljust(150) + " ".ljust(width - len(prefix) - 150)).encode("ascii") + b"\r\n"


def fixture(root: Path) -> None:
    raw = root / "data/raw/trade-detail/IMDB2607.ZIP"
    raw.parent.mkdir(parents=True)
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("hsdesc.txt", _row("1001", "WHEAT AND MESLIN", 206) +
                         _row("8517", "TELEPHONE SETS AND OTHER APPARATUS", 206))
        archive.writestr("concord.txt", _row("1001990090", "OTHER WHEAT", 235) +
                         _row("8517130000", "SMARTPHONES", 235))
    source_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    monthly = root / "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv"
    monthly.parent.mkdir(parents=True)
    with monthly.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(dict(year=2026, month=7, hts10="1001990090", hts8="10019900",
                             china_import_value_consumption_usd=4,
                             all_origin_import_value_consumption_usd=10,
                             china_observed=1, all_origin_observed=1, source_sha256=source_sha))
    manifest = {"months": [{"year": 2026, "month": 7, "status": "processed",
                            "source_url": "https://www.census.gov/fixture/IMDB2607.ZIP",
                            "source_sha256": source_sha,
                            "monthly_output": str(monthly.relative_to(root))}]}
    (monthly.parent.parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class ClassificationCatalogTests(unittest.TestCase):
    def test_rice_alias_and_exact_heading_do_not_offer_excluded_goods(self):
        catalog = object.__new__(ClassificationCatalog)
        catalog.zh_headings = {
            "1006": {"label": "稻谷及大米"},
            "1104": {"label": "其他加工谷物，但稻谷、大米除外"},
        }
        catalog.latest_month = lambda flow: "2026-07"
        catalog.month = lambda flow, month: {"groups": {
            "1006": "RICE",
            "1104": "CEREAL GRAINS OTHERWISE WORKED, EXCEPT RICE",
            "1905": "BREAD AND RICE PAPER",
        }, "items": {}}
        catalog.candidate = lambda flow, month, code: {"code": code, "flow": flow}
        for question in ("美国稻米进口最近有什么变化？", "美国稻谷进口最近有什么变化？",
                         "How have U.S. rice imports changed recently?"):
            with self.subTest(question=question):
                self.assertEqual([item["code"] for item in catalog.search(question, "import")], ["1006"])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        fixture(self.root)
        build_catalog(self.root, flows=("import",))

    def test_name_requires_choice_and_report_uses_chosen_scope(self):
        question = "2026年7月美国小麦进口是多少"
        result = prepare_trade_question(self.root, question)
        self.assertEqual(result["status"], "needs_product_choice")
        self.assertEqual([(item["code"], item["official_en"]) for item in result["candidates"]],
                         [("1001", "WHEAT AND MESLIN")])
        choice = result["candidates"][0]
        proposal = prepare_trade_question(self.root, question,
                                          selected_product_id=choice["id"],
                                          catalog_version=result["catalog_version"])
        self.assertEqual(proposal["status"], "ready")
        report = generate_trade_report(self.root, question, selected_flow="import",
                                       dataset_version=proposal["dataset_version"],
                                       selected_product_id=choice["id"],
                                       catalog_version=result["catalog_version"])
        self.assertEqual(report["summary"]["latest_value_usd"], 10)
        self.assertEqual(report["scope"]["official_product_en"], "WHEAT AND MESLIN")

    def test_forged_choice_and_stale_catalog_cannot_generate_report(self):
        question = "2026年7月美国小麦进口是多少"
        result = prepare_trade_question(self.root, question)
        for product_id, version in (("import:9999", result["catalog_version"]),
                                    ("export:1001", result["catalog_version"]),
                                    ("import:1001", "0" * 64)):
            with self.subTest(product_id=product_id, version=version), self.assertRaises(ValueError):
                prepare_trade_question(self.root, question,
                                       selected_product_id=product_id, catalog_version=version)

    def test_machine_extracted_chinese_name_is_search_only(self):
        index = self.root / "data/processed/trade_classification/zh_hs4_2026.json"
        index.write_text(json.dumps({"schema": "mof-2026-hs4-search-only-v1",
                                     "source_pdf_sha256": MOF_PDF_SHA256,
                                     "headings": {"8517": {"label": "电话机及智能手机", "pdf_page": 12}}}),
                         encoding="utf-8")
        build_catalog(self.root, flows=("import",))
        result = prepare_trade_question(self.root, "2026年7月美国智能手机进口")
        self.assertEqual(result["status"], "needs_product_choice")
        candidate = result["candidates"][0]
        self.assertEqual((candidate["code"], candidate["official_en"],
                          candidate["zh_review_status"]),
                         ("8517", "TELEPHONE SETS AND OTHER APPARATUS", "machine_extracted"))

    def test_source_or_index_tampering_is_rejected(self):
        index = self.root / "data/processed/trade_classification/manifest.json"
        body = json.loads(index.read_text(encoding="utf-8"))
        monthly = self.root / body["months"][0]["path"]
        monthly.write_bytes(monthly.read_bytes() + b"x")
        with self.assertRaisesRegex(ValueError, "摘要不符"):
            prepare_trade_question(self.root, "2026年7月美国小麦进口是多少")

    def test_http_requires_confirmed_candidate_for_report(self):
        from src.tradeintel_ai.web_app import create_server
        server = create_server(root=self.root, host="127.0.0.1", port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(path, body):
            request = Request(f"http://127.0.0.1:{server.server_port}{path}",
                              json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urlopen(request) as response:
                return json.load(response)

        question = "2026年7月美国小麦进口是多少"
        choice = post("/api/trade/prepare", {"question": question})
        selected = choice["candidates"][0]
        proposal = post("/api/trade/prepare", {"question": question, "selected_flow": "import",
                                                "selected_product_id": selected["id"],
                                                "catalog_version": choice["catalog_version"]})
        request = {"question": question, "selected_flow": "import",
                   "dataset_version": proposal["dataset_version"]}
        with self.assertRaises(HTTPError):
            post("/api/trade/report", request)
        report = post("/api/trade/report", {**request, "selected_product_id": selected["id"],
                                              "catalog_version": choice["catalog_version"]})
        self.assertEqual(report["summary"]["latest_value_usd"], 10)


if __name__ == "__main__":
    unittest.main()
