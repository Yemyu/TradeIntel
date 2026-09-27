"""The web app keeps policy/report state separate from its trade data bundle."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.tradeintel_ai.announcement_flow import (
    REQUIRED_FIELDS, confirm_and_enable, load_announcement_store, submit_candidates,
)
from src.tradeintel_ai.trade_classification_catalog import build_catalog
from src.tradeintel_ai.trade_data_repository import TradeDataRepository
from src.tradeintel_ai.web_app import _handle_announcement_import, create_server

FIELDS = ["year", "month", "hts10", "hts8", "china_import_value_consumption_usd",
          "all_origin_import_value_consumption_usd", "china_observed", "all_origin_observed",
          "source_sha256"]


def trade_fixture(root: Path) -> None:
    raw = root / "data/raw/trade-detail/IMDB2607.ZIP"
    raw.parent.mkdir(parents=True)

    def fixed_row(code: str, description: str, width: int) -> bytes:
        prefix = code.ljust(6) if width == 206 else code
        return (prefix + description.ljust(150) +
                " ".ljust(width - len(prefix) - 150)).encode("ascii") + b"\r\n"

    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("hsdesc.txt", fixed_row("1001", "WHEAT AND MESLIN", 206))
        archive.writestr("concord.txt", fixed_row("1001990090", "OTHER WHEAT", 235))
    source_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    output = root / "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv"
    output.parent.mkdir(parents=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow({"year": 2026, "month": 7, "hts10": "1001990090",
                         "hts8": "10019900", "china_import_value_consumption_usd": 4,
                         "all_origin_import_value_consumption_usd": 10,
                         "china_observed": 1, "all_origin_observed": 1,
                         "source_sha256": source_hash})
    (output.parent.parent / "manifest.json").write_text(json.dumps({"months": [{
        "year": 2026, "month": 7, "status": "processed",
        "source_url": "https://www.census.gov/fixture/IMDB2607.ZIP",
        "source_sha256": source_hash,
        "monthly_output": str(output.relative_to(root)),
    }]}), encoding="utf-8")


def _set_trade_value(root: Path, value: int) -> None:
    path = root / "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    rows[0]["all_origin_import_value_consumption_usd"] = str(value)
    rows[0]["china_import_value_consumption_usd"] = str(value)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class SplitTradeDataRootTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="trade-data-root-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.code_root, self.data_root = base / "code", base / "bundle"
        for root, value in ((self.code_root, 999), (self.data_root, 10)):
            trade_fixture(root)
            _set_trade_value(root, value)
            build_catalog(root, flows=("import",))
        (self.data_root / "BUNDLE_MANIFEST.json").write_text("{}", encoding="utf-8")
        self.data_version = TradeDataRepository(self.data_root).catalog()["dataset_version"]
        self.code_version = TradeDataRepository(self.code_root).catalog()["dataset_version"]
        self.assertNotEqual(self.data_version, self.code_version)

    def _start(self):
        server = create_server(root=self.code_root, trade_data_root=self.data_root,
                               host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    @staticmethod
    def _post(base: str, path: str, body: dict) -> dict:
        request = Request(base + path, json.dumps(body).encode(),
                          {"Content-Type": "application/json"})
        with urlopen(request) as response:
            return json.load(response)

    def test_trade_routes_use_external_data_and_report_state_stays_in_code_root(self):
        base = self._start()
        with urlopen(base + "/api/trade/catalog") as response:
            catalog = json.load(response)
        self.assertEqual(catalog["dataset_version"], self.data_version)
        query = self._post(base, "/api/trade/query", {
            "reporter": "US", "flow": "import", "product_code": "10019900",
            "start_month": "2026-07", "end_month": "2026-07",
            "partner": "ALL_ORIGINS", "dataset_version": self.data_version,
        })
        self.assertEqual(query["months"][0]["value_usd"], 10)
        with self.assertRaises(HTTPError) as stale:
            self._post(base, "/api/trade/query", {
                "reporter": "US", "flow": "import", "product_code": "10019900",
                "start_month": "2026-07", "end_month": "2026-07",
                "partner": "ALL_ORIGINS", "dataset_version": self.code_version,
            })
        self.assertEqual(stale.exception.code, 400)
        question = "2026年7月美国小麦进口是多少"
        first = self._post(base, "/api/trade/prepare", {"question": question})
        self.assertEqual(first["status"], "needs_product_choice")
        selected = self._post(base, "/api/trade/prepare", {
            "question": question, "selected_flow": "import",
            "selected_product_id": first["candidates"][0]["id"],
            "catalog_version": first["catalog_version"],
        })
        report = self._post(base, "/api/trade/report", {
            "question": question, "selected_flow": "import",
            "selected_product_id": first["candidates"][0]["id"],
            "catalog_version": first["catalog_version"],
            "dataset_version": selected["dataset_version"],
        })
        self.assertEqual(report["summary"]["latest_value_usd"], 10)
        self.assertEqual(report["scope"]["dataset_version"], self.data_version)
        self.assertEqual(report["ai_status"], "not_requested")
        with urlopen(base + f"/api/trade/report-state?report_id={report['report_id']}") as response:
            restored = json.load(response)
        self.assertEqual(restored["report_sha256"], report["report_sha256"])
        self.assertTrue((self.code_root / ".local/trade-reports" /
                         f"{report['report_id']}.json").is_file())
        self.assertFalse((self.data_root / ".local").exists())

    def test_announcement_uses_code_policy_but_external_statistics(self):
        imported = _handle_announcement_import(self.code_root, {
            "policy_id": "wheat-notice", "source_id": "notice:wheat",
            "url": "https://official.example/wheat",
            "text": "Products of China are covered.\nHTS 10019900 is listed.",
        })
        version = imported["doc_version"]
        store = load_announcement_store(self.code_root, "wheat-notice")
        sections = store["documents"][0]["sections"]

        def citation(needle: str) -> list[dict]:
            section = next(item for item in sections if needle in item["text"])
            return [{"doc_version": version, "section_id": section["id"], "quote": needle}]

        fields = []
        for name in REQUIRED_FIELDS:
            if name == "origin":
                fields.append({"field": name, "status": "known", "value": "China",
                               "evidence": citation("Products of China")})
            elif name == "hts_codes":
                fields.append({"field": name, "status": "known",
                               "value": [{"code": "10019900", "precision": "whole_hts8"}],
                               "evidence": citation("HTS 10019900")})
            else:
                fields.append({"field": name, "status": "unknown", "value": None,
                               "reason": "fixture 未确认"})
        submitted = submit_candidates(self.code_root, "wheat-notice", version, fields)
        confirm_and_enable(self.code_root, "wheat-notice", version, fields,
                           confirmed_by="split-root-test",
                           expected_candidate_digest=submitted["candidate_digest"])
        base = self._start()
        prepared = self._post(base, "/api/announcements/statistics/prepare", {
            "policy_id": "wheat-notice", "doc_version": version,
            "start_month": "2026-07", "end_month": "2026-07",
        })
        self.assertEqual(prepared["dataset_version"], self.data_version)
        result = self._post(base, "/api/announcements/statistics/report", {"prepared": prepared})
        self.assertEqual(result["monthly"][0]["observed_value_usd"], 10)
        self.assertEqual(result["policy"]["doc_version"], version)
        self.assertFalse((self.data_root / ".local").exists())

    def test_explicit_missing_bundle_fails_without_fallback(self):
        with self.assertRaisesRegex(ValueError, "独立贸易数据目录"):
            create_server(root=self.code_root, trade_data_root=self.code_root,
                          host="127.0.0.1", port=0)

    def test_changed_external_version_does_not_reuse_code_root_data(self):
        base = self._start()
        question = "2026年7月美国小麦进口是多少"
        first = self._post(base, "/api/trade/prepare", {"question": question})
        selected = self._post(base, "/api/trade/prepare", {
            "question": question, "selected_flow": "import",
            "selected_product_id": first["candidates"][0]["id"],
            "catalog_version": first["catalog_version"],
        })
        _set_trade_value(self.data_root, 30)
        with self.assertRaises(HTTPError) as stale:
            self._post(base, "/api/trade/report", {
                "question": question, "selected_flow": "import",
                "selected_product_id": first["candidates"][0]["id"],
                "catalog_version": first["catalog_version"],
                "dataset_version": selected["dataset_version"],
            })
        self.assertEqual(stale.exception.code, 400)
        self.assertFalse((self.code_root / ".local/trade-reports").exists())


if __name__ == "__main__":
    unittest.main()
