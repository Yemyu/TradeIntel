import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.tradeintel_ai.policy_exposure_tools import (
    POLICY_EXPOSURE_ID,
    PolicyExposureRegistry,
    get_policy_exposure_series,
)
from src.tradeintel_ai.agent import ModelResponse, ModelToolCall, ToolCallingAgent
from src.tradeintel_ai.repository import DataPaths, EvidenceRepository, default_paths


FIELDS = [
    "policy_id", "year", "month", "canonical_hts8", "hts10", "origin_code",
    "origin_name", "import_value_consumption_usd", "detail_row_count",
    "source_url", "source_file_name", "source_sha256",
]


def make_fixture(root: Path, *, include_second_month: bool = True) -> EvidenceRepository:
    policy_dir = root / "data/processed/policy"
    monthly_dir = root / "data/processed/policy_exposure/monthly"
    policy_dir.mkdir(parents=True)
    monthly_dir.mkdir(parents=True)
    event = policy_dir / "section301_review2025_event.csv"
    event.write_text(
        "policy_id,policy_name,importer,target_origin,announcement_date,effective_date,source_url,implementation_source_url,scope_note\n"
        f"{POLICY_EXPOSURE_ID},Test policy,United States,China,2024-12-16,2025-01-01,https://example/p,https://example/i,scope\n",
        encoding="utf-8",
    )
    products = policy_dir / "section301_review2025_products.csv"
    products.write_text(
        "policy_id,raw_hts,canonical_hts8,product_description,product_description_zh,additional_rate_percent,effective_date,source_annex,source_location,source_url,implementation_source_url\n"
        f"{POLICY_EXPOSURE_ID},1234.56.78,12345678,Test product,测试商品,25,2025-01-01,Annex,loc,https://example/p,https://example/i\n"
        f"{POLICY_EXPOSURE_ID},8765.43.21,87654321,Other product,其他商品,50,2025-01-01,Annex,loc,https://example/p,https://example/i\n",
        encoding="utf-8",
    )
    months = [(2025, 1, 20, 5, 30), (2025, 2, 10, 0, 10)] if include_second_month else [(2025, 1, 20, 5, 30)]
    manifest_rows = []
    for year, month, china_value, other_value, second_product in months:
        filename = f"{POLICY_EXPOSURE_ID}_{year}_{month:02d}.csv"
        output = monthly_dir / filename
        source_hash = f"hash-{year}-{month}"
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows([
                {"policy_id": POLICY_EXPOSURE_ID, "year": year, "month": month, "canonical_hts8": "12345678", "hts10": "1234567800", "origin_code": "5700", "origin_name": "CHINA", "import_value_consumption_usd": china_value, "detail_row_count": 1, "source_url": f"https://example/{year}{month}", "source_file_name": f"IMDB{str(year)[2:]}{month:02d}.ZIP", "source_sha256": source_hash},
                {"policy_id": POLICY_EXPOSURE_ID, "year": year, "month": month, "canonical_hts8": "12345678", "hts10": "1234567800", "origin_code": "2010", "origin_name": "MEXICO", "import_value_consumption_usd": other_value, "detail_row_count": 1, "source_url": f"https://example/{year}{month}", "source_file_name": f"IMDB{str(year)[2:]}{month:02d}.ZIP", "source_sha256": source_hash},
                {"policy_id": POLICY_EXPOSURE_ID, "year": year, "month": month, "canonical_hts8": "87654321", "hts10": "8765432100", "origin_code": "2010", "origin_name": "MEXICO", "import_value_consumption_usd": second_product, "detail_row_count": 1, "source_url": f"https://example/{year}{month}", "source_file_name": f"IMDB{str(year)[2:]}{month:02d}.ZIP", "source_sha256": source_hash},
            ])
        manifest_rows.append({
            "policy_id": POLICY_EXPOSURE_ID, "year": year, "month": month,
            "source_url": f"https://example/{year}{month}",
            "source_file_name": f"IMDB{str(year)[2:]}{month:02d}.ZIP",
            "source_sha256": source_hash,
            "total_consumption_value_usd": china_value + other_value + second_product,
            "matched_detail_rows": 3,
        })
    manifest = root / "data/processed/policy_exposure/manifest.json"
    manifest.write_text(json.dumps({"policy_id": POLICY_EXPOSURE_ID, "months": manifest_rows}), encoding="utf-8")
    receipt = {"status": "validated", "policy_id": POLICY_EXPOSURE_ID, "months": [
        {"year": item["year"], "month": item["month"], "archive_sha256": item["source_sha256"],
         "output_sha256": hashlib.sha256((monthly_dir / f"{POLICY_EXPOSURE_ID}_{item['year']}_{item['month']:02d}.csv").read_bytes()).hexdigest()}
        for item in manifest_rows]}
    (manifest.parent / "window_validation_2025-01_2026-07.json").write_text(json.dumps(receipt), encoding="utf-8")
    return EvidenceRepository(DataPaths(root))


class PolicyExposureToolTests(unittest.TestCase):
    def test_query_filters_origin_and_exact_hts8(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = make_fixture(Path(directory))
            result = get_policy_exposure_series(start="2025-01", end="2025-02", repository=repository)
            self.assertEqual(result["status"], "ok")
            self.assertEqual([x["value_usd"] for x in result["data"]["series"]], [20, 10])
            self.assertEqual(result["data"]["total_usd"], 30)
            self.assertEqual(result["data"]["series"][0]["target_share_percent"], 36.3636)

            product = get_policy_exposure_series(
                origin="all_origins", hts8="12345678", start="2025-01", end="2025-02", repository=repository
            )
            self.assertEqual([x["value_usd"] for x in product["data"]["series"]], [25, 10])
            self.assertEqual(product["data"]["product"]["product_description_zh"], "测试商品")

    def test_registry_adds_new_tool_without_changing_frozen_registry_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = PolicyExposureRegistry(make_fixture(Path(directory)))
            self.assertIn("get_policy_exposure_series", registry.names())
            schema = next(item for item in registry.schemas() if item["name"] == "get_policy_exposure_series")
            self.assertEqual(schema["parameters"]["properties"]["hts8"]["pattern"], "^[0-9]{8}$")
            result = registry.call("get_policy_exposure_series", {"start": "2025-01", "end": "2025-01"})
            self.assertEqual(result["status"], "ok")

    def test_unknown_scope_and_missing_month_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = make_fixture(Path(directory), include_second_month=False)
            with self.assertRaises(ValueError):
                get_policy_exposure_series(hts8="11111111", repository=repository)
            result = get_policy_exposure_series(start="2025-01", end="2025-02", repository=repository)
            self.assertFalse(result["data"]["coverage_complete"])
            self.assertEqual(result["data"]["missing_months"], ["2025-02"])
            self.assertIsNone(result["data"]["series"][1]["value_usd"])
            self.assertIsNone(result["data"]["total_usd"])

    def test_outside_verified_window_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = make_fixture(Path(directory))
            with self.assertRaises(ValueError):
                get_policy_exposure_series(start="2024-12", end="2025-01", repository=repository)

    def test_deleted_product_or_changed_amount_is_rejected(self):
        for mutation in ("delete_product", "amount", "wrong_prefix"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repository = make_fixture(root)
                path = root / f"data/processed/policy_exposure/monthly/{POLICY_EXPOSURE_ID}_2025_01.csv"
                with path.open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                if mutation == "delete_product":
                    rows = rows[:2]
                elif mutation == "amount":
                    rows[0]["import_value_consumption_usd"] = "999"
                else:
                    rows[0]["hts10"] = "9999999900"
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
                with self.assertRaises(RuntimeError):
                    get_policy_exposure_series(start="2025-01", end="2025-01", repository=repository)

    def test_tool_calling_agent_can_select_new_case_tool(self):
        class OneToolModel:
            def complete(self, *, messages, tools):
                if any(message.get("role") == "tool" for message in messages):
                    return ModelResponse(text="已取得登记政策的月度贸易暴露数据。")
                self_seen = {item["name"] for item in tools}
                if "get_policy_exposure_series" not in self_seen:
                    raise AssertionError("new-case tool was not exposed to the model")
                return ModelResponse(tool_calls=(ModelToolCall(
                    "exposure", "get_policy_exposure_series",
                    {"start": "2025-01", "end": "2025-01", "origin": "China"},
                ),))

        result = ToolCallingAgent(
            OneToolModel(), registry=PolicyExposureRegistry(EvidenceRepository(default_paths()))
        ).answer("查这项政策 2025 年 1 月中国原产进口额")
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("get_policy_exposure_series", result["model_selected_tools"])
        self.assertTrue(any(item["tool_name"] == "get_policy_exposure_series" for item in result["tool_results"]))


if __name__ == "__main__":
    unittest.main()
