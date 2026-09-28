"""Development-seen policy linkage routes; not a new-announcement holdout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.tradeintel_ai.announcement_flow import (REQUIRED_FIELDS, confirm_and_enable,
                                                  load_announcement_store,
                                                  save_announcement_store,
                                                  submit_candidates)
from src.tradeintel_ai.announcement_linkage import (confirm_linkage_assessment,
                                                    load_linkage_assessment,
                                                    prepare_linkage_scope,
                                                    validate_prepared_linkage_scope)
from src.tradeintel_ai.announcement_context_report import (build_parent_context_report,
                                                           generate_parent_context_record)
from src.tradeintel_ai.announcement_country_context import (build_country_context_report,
                                                           generate_country_context_record)
from src.tradeintel_ai.announcement_source_card import (build_source_fact_card,
                                                       generate_source_fact_record)
from src.tradeintel_ai.policy_documents import build_document, build_document_store
from src.tradeintel_ai.trade_data_repository import TradeDataRepository
from src.tradeintel_ai.trade_report_store import claim_call, get_state, load_record


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AnnouncementLinkageTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="linkage-offline-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self._trade_fixture()

    def _trade_fixture(self, *, missing_child: bool = False,
                       unobserved_child: bool = False) -> None:
        monthly = self.root / "data/processed/trade_hts10/monthly"
        monthly.mkdir(parents=True, exist_ok=True)
        data = monthly / "trade_hts10_2026_07.csv"
        lines = ["year,month,hts10,hts8,china_import_value_consumption_usd,"
                 "china_observed,source_sha256",
                 f"2026,7,2804610010,28046100,100,1,{'a' * 64}",
                 f"2026,7,8413919039,84139190,200,1,{'a' * 64}"]
        if not missing_child:
            lines.append(f"2026,7,8413919046,84139190,100,"
                         f"{0 if unobserved_child else 1},{'a' * 64}")
        data.write_text("\n".join(lines) + "\n", encoding="utf-8")
        manifest = {"months": [
            {"year": 2026, "month": 6, "status": "not_processed"},
            {"year": 2026, "month": 7, "status": "processed",
             "monthly_output": "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv",
             "source_sha256": "a" * 64},
        ]}
        (monthly.parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        trade_version = TradeDataRepository(self.root).catalog()["dataset_version"]
        directory = self.root / "data/processed/trade_classification"
        directory.mkdir(parents=True, exist_ok=True)
        import gzip
        content = gzip.compress(json.dumps({"flow": "import", "month": "2026-07",
                                            "items": {"2804610010": "SILICON",
                                                      "8413919039": "PUMP PARTS A",
                                                      "8413919046": "PUMP PARTS B"}}).encode())
        item_path = directory / "import_2026_07.json.gz"
        item_path.write_bytes(content)
        class_manifest = {"schema": "census-classification-v1",
                          "dataset_versions": {"import": trade_version},
                          "months": [{"flow": "import", "month": "2026-07",
                                      "path": str(item_path.relative_to(self.root)),
                                      "sha256": _hash(content)}]}
        class_manifest["catalog_version"] = _hash(json.dumps(
            class_manifest, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode())
        (directory / "manifest.json").write_text(json.dumps(class_manifest), encoding="utf-8")

    def _case(self, policy_id: str, *, text: str, origin: str = "China",
              codes: list[dict] | None = None,
              scope_fields_reviewed: bool = False) -> tuple[str, str, dict]:
        document = build_document({"policy_id": policy_id,
                                   "sources": [{"id": f"{policy_id}:p1", "text": text,
                                                "url": "https://official.example/notice"}]},
                                  status="disabled")
        doc_version = document["doc_version"]
        store = build_document_store([document], policy_id=policy_id)
        save_announcement_store(self.root, policy_id, store)
        section = document["sections"][0]
        citation = {"doc_version": doc_version, "section_id": section["id"], "quote": text}
        fields = []
        for name in REQUIRED_FIELDS:
            if name == "origin":
                fields.append({"field": name, "status": "known", "value": origin,
                               "evidence": [citation]})
            elif name == "hts_codes" and codes is not None:
                fields.append({"field": name, "status": "known", "value": codes,
                               "evidence": [citation]})
            elif name in {"conditions", "exceptions"} and scope_fields_reviewed:
                fields.append({"field": name, "status": "known", "value": text,
                               "evidence": [citation]})
            else:
                fields.append({"field": name, "status": "unknown", "value": None,
                               "reason": "本合成公告没有确认这一字段"})
        submitted = submit_candidates(self.root, policy_id, doc_version, fields)
        confirm_and_enable(self.root, policy_id, doc_version, fields,
                           confirmed_by="fixture-reviewer",
                           expected_candidate_digest=submitted["candidate_digest"])
        return policy_id, doc_version, citation

    def _proposal(self, relation: str, citation: dict, *, code: str | None = None,
                  origin_alignment: str = "mainland_only", defining: bool = False,
                  dimension: str = "exception_status") -> dict:
        return {"relation": relation, "origin_alignment": origin_alignment,
                "context_code": code,
                "policy_scope_summary": "人工核对的公告对象；不是统计表中的全部货品",
                "unobserved_eligibility": [{"dimension": dimension,
                                            "defines_population": defining,
                                            "description": "贸易月表不能核对这一条件"}],
                "evidence": [citation]}

    def _confirm(self, case: tuple, proposal: dict) -> dict:
        policy_id, doc_version, _ = case
        store = load_announcement_store(self.root, policy_id)
        digest = store["announcement_candidates"][doc_version]["candidate_digest"]
        return confirm_linkage_assessment(self.root, policy_id, doc_version,
                                          proposal, confirmed_by="human-reviewer",
                                          expected_candidate_digest=digest)

    def test_r2_whole_hts8_keeps_old_strict_route(self):
        case = self._case("r2", text="Products of China, HTS 28046100; exceptions apply.",
                          codes=[{"code": "28046100", "precision": "whole_hts8"}])
        self._confirm(case, self._proposal("code_aligned", case[2]))
        prepared = prepare_linkage_scope(self.root, case[0], case[1],
                                         start_month="2026-07", end_month="2026-07")
        self.assertEqual(prepared["route"], "announcement-statistics-report-v1")
        self.assertEqual(prepared["strict_scope"]["selected_codes"], ["28046100"])
        self.assertEqual(prepared["policy_amount_status"], "not_determined")
        self.assertEqual(validate_prepared_linkage_scope(self.root, prepared), prepared)

    def test_ten_digit_exclusion_only_gets_wider_parent_context(self):
        case = self._case("ten-digit", text="Products of China, exclusion at HTS 8413919039.",
                          codes=[{"code": "8413919039", "precision": "hts10_partial"}])
        with self.assertRaisesRegex(ValueError, "完整 HTS8"):
            self._confirm(case, self._proposal("code_aligned", case[2]))
        with self.assertRaisesRegex(ValueError, "推导"):
            self._confirm(case, self._proposal("parent_context", case[2], code="38180000"))
        self._confirm(case, self._proposal("parent_context", case[2], code="84139190"))
        prepared = prepare_linkage_scope(self.root, case[0], case[1],
                                         start_month="2026-07", end_month="2026-07")
        self.assertEqual(prepared["route"], "announcement-context-report-v1:parent")
        self.assertIn("包含公告未覆盖货品", prepared["statistical_population"])
        self.assertNotIn("policy_exposure_usd", prepared)
        self.assertEqual(validate_prepared_linkage_scope(self.root, prepared), prepared)

    def _parent_prepared(self, *, code: str = "8413919039",
                         precision: str = "hts10_partial",
                         policy_id: str = "parent-report") -> dict:
        case = self._case(policy_id, text=f"Products of China, exclusion at HTS {code}.",
                          codes=[{"code": code, "precision": precision}])
        parent = code[:6] if precision == "hs6_only" else code[:8]
        self._confirm(case, self._proposal("parent_context", case[2], code=parent))
        return prepare_linkage_scope(self.root, case[0], case[1],
                                     start_month="2026-07", end_month="2026-07")

    def test_parent_context_report_is_whole_group_and_readable_after_save(self):
        prepared = self._parent_prepared()
        report = build_parent_context_report(self.root, prepared)
        self.assertEqual(report["kind"], "announcement-context-report-v1")
        self.assertEqual(report["monthly"][0]["whole_parent_value_usd"], 300)
        self.assertEqual(report["monthly"][0]["status"], "complete_observed")
        self.assertEqual(report["policy_amount_status"], "not_determined")
        self.assertIn("not_policy_coverage", report["scope"]["amount_semantics"])
        self.assertEqual(report["monthly"][0]["month_change_status"], "not_comparable")
        saved = generate_parent_context_record(self.root, prepared)
        loaded = load_record(self.root, saved["report_id"])
        self.assertEqual(loaded["report"], report)
        self.assertEqual(get_state(self.root, saved["report_id"])["report_sha256"],
                         saved["report_sha256"])
        self.assertFalse(saved["explanation"]["available"])

    def test_hs6_parent_context_uses_the_confirmed_parent_code(self):
        prepared = self._parent_prepared(code="841391", precision="hs6_only",
                                         policy_id="hs6-parent")
        report = build_parent_context_report(self.root, prepared)
        self.assertEqual(report["scope"]["context_code"], "841391")
        self.assertEqual(report["monthly"][0]["whole_parent_value_usd"], 300)

    def test_parent_context_incomplete_child_withholds_amount(self):
        for index, fixture in enumerate(({"missing_child": True},
                                         {"unobserved_child": True})):
            with self.subTest(fixture=fixture):
                self._trade_fixture(**fixture)
                prepared = self._parent_prepared(policy_id=f"parent-incomplete-{index}")
                report = build_parent_context_report(self.root, prepared)
                item = report["monthly"][0]
                self.assertEqual(item["status"], "incomplete_observation")
                self.assertIsNone(item["whole_parent_value_usd"])
                self.assertIsNone(item["month_change_usd"])
                self.assertEqual(len(item["missing_hts10"] + item["unobserved_hts10"]), 1)

    def test_parent_context_rejects_stale_prepare_and_wrong_route(self):
        prepared = self._parent_prepared()
        prepared["statistical_population"] = "政策覆盖金额"
        with self.assertRaises(ValueError):
            generate_parent_context_record(self.root, prepared)
        self.assertFalse(list((self.root / ".local/trade-reports").glob("*.json")))
        wrong = {**prepared, "route": "announcement-context-report-v1:country"}
        with self.assertRaisesRegex(ValueError, "上层商品"):
            build_parent_context_report(self.root, wrong)

    def test_china_hong_kong_notice_is_mainland_subset_only(self):
        case = self._case("broad-goods", text="Broad goods of China and Hong Kong, with exceptions.",
                          origin="China and Hong Kong", scope_fields_reviewed=True)
        with self.assertRaisesRegex(ValueError, "不符"):
            self._confirm(case, self._proposal("country_context", case[2]))
        proposal = self._proposal("country_context", case[2],
                                  origin_alignment="mainland_subset_of_china_hk")
        self._confirm(case, proposal)
        prepared = prepare_linkage_scope(self.root, case[0], case[1],
                                         start_month="2026-07", end_month="2026-07")
        self.assertEqual(prepared["route"], "announcement-context-report-v1:country")
        self.assertFalse(prepared["hong_kong_included_in_statistics"])
        self.assertEqual(prepared["country_month_reconciliation"], "pending")
        self.assertIn("非公告适用金额", prepared["statistical_population"])

    def _country_raw_fixture(self) -> Path:
        import gzip
        from zipfile import ZipFile
        raw_dir = self.root / "data/raw/trade-detail"
        raw_dir.mkdir(parents=True, exist_ok=True)
        archive = raw_dir / "IMDB2607.ZIP"
        def detail(code: str, country: str, value: int) -> bytes:
            line = bytearray(b" " * 688)
            line[:10] = code.encode()
            line[10:14] = country.encode()
            line[22:28] = b"202607"
            line[73:88] = f"{value:>15}".encode()
            return bytes(line) + b"\n"
        countries = ("0001" + " " * 7 + f"{'CHINA':<50}" + "\n"
                     + "0002" + " " * 7 + f"{'HONG KONG':<50}" + "\n")
        with ZipFile(archive, "w") as out:
            out.writestr("COUNTRY.TXT", countries)
            out.writestr("IMP_DETL.TXT", b"".join([
                detail("8413919039", "0001", 100),
                detail("8413919039", "0002", 900),
                detail("8413919046", "0002", 50)]))
        source_hash = _hash(archive.read_bytes())
        source_url = "https://official.example/IMDB2607.ZIP"
        output = self.root / "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv"
        header = ("year,month,hts10,hts8,china_import_value_consumption_usd,"
                  "all_origin_import_value_consumption_usd,china_observed,all_origin_observed,"
                  "china_detail_row_count,all_origin_detail_row_count,source_url,"
                  "source_file_name,source_sha256")
        output.write_text("\n".join([
            header,
            f"2026,7,8413919039,84139190,100,1000,1,1,1,2,{source_url},IMDB2607.ZIP,{source_hash}",
            f"2026,7,8413919046,84139190,0,50,0,1,0,1,{source_url},IMDB2607.ZIP,{source_hash}",
        ]) + "\n", encoding="utf-8")
        manifest = {"months": [{"year": 2026, "month": 7, "status": "processed",
                                "source_url": source_url, "source_file_name": "IMDB2607.ZIP",
                                "source_sha256": source_hash,
                                "monthly_output": str(output.relative_to(self.root)),
                                "raw_archive_retained_after_processing": True,
                                "raw_detail_rows": 3, "output_rows": 2,
                                "unique_hts10_count": 2,
                                "raw_china_value_usd": 100,
                                "raw_all_origin_value_usd": 1050}]}
        (output.parent.parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        trade_version = TradeDataRepository(self.root).catalog()["dataset_version"]
        directory = self.root / "data/processed/trade_classification"
        item_path = directory / "import_2026_07.json.gz"
        content = gzip.compress(json.dumps({"flow": "import", "month": "2026-07",
                                            "items": {"8413919039": "PUMP PARTS A",
                                                      "8413919046": "PUMP PARTS B"}}).encode())
        item_path.write_bytes(content)
        class_manifest = {"schema": "census-classification-v1",
                          "dataset_versions": {"import": trade_version},
                          "months": [{"flow": "import", "month": "2026-07",
                                      "path": str(item_path.relative_to(self.root)),
                                      "sha256": _hash(content)}]}
        class_manifest["catalog_version"] = _hash(json.dumps(
            class_manifest, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode())
        (directory / "manifest.json").write_text(json.dumps(class_manifest), encoding="utf-8")
        return archive

    def _country_prepared(self) -> dict:
        case = self._case("country-report", text="Broad goods of China and Hong Kong, with exceptions.",
                          origin="China and Hong Kong", scope_fields_reviewed=True)
        self._confirm(case, self._proposal("country_context", case[2],
                                          origin_alignment="mainland_subset_of_china_hk"))
        return prepare_linkage_scope(self.root, case[0], case[1],
                                     start_month="2026-07", end_month="2026-07")

    def test_country_context_reconciles_raw_source_and_excludes_hong_kong(self):
        self._country_raw_fixture()
        prepared = self._country_prepared()
        report = build_country_context_report(self.root, prepared)
        self.assertEqual(report["monthly"][0]["china_mainland_import_value_usd"], 100)
        self.assertEqual(report["monthly"][0]["all_origin_import_value_usd"], 1050)
        self.assertFalse(report["scope"]["hong_kong_included_in_statistics"])
        self.assertEqual(report["policy_amount_status"], "not_determined")
        saved = generate_country_context_record(self.root, prepared)
        self.assertEqual(load_record(self.root, saved["report_id"])["report"], report)
        self.assertFalse(saved["explanation"]["available"])

    def test_country_context_rejects_changed_raw_source(self):
        archive = self._country_raw_fixture()
        prepared = self._country_prepared()
        archive.write_bytes(archive.read_bytes() + b"altered")
        with self.assertRaisesRegex(ValueError, "原始月包"):
            build_country_context_report(self.root, prepared)
        self.assertFalse(list((self.root / ".local/trade-reports").glob("*.json")))

    def test_country_context_rejects_changed_processed_csv(self):
        self._country_raw_fixture()
        prepared = self._country_prepared()
        output = self.root / "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv"
        output.write_text(output.read_text(encoding="utf-8").replace(",100,1000,", ",101,1000,"),
                          encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "版本|变化"):
            build_country_context_report(self.root, prepared)
        self.assertFalse(list((self.root / ".local/trade-reports").glob("*.json")))

    def test_postal_and_pharma_get_source_card_without_trade_chart(self):
        cases = [
            ("postal", "Postal goods of China not exceeding $800.", "shipment_value"),
            ("pharma", "Pharmaceutical goods of China requiring firm approval.",
             "firm_qualification"),
        ]
        for name, text, dimension in cases:
            with self.subTest(name=name):
                case = self._case(name, text=text)
                proposal = self._proposal("no_statistical_link", case[2],
                                          defining=True, dimension=dimension)
                self._confirm(case, proposal)
                prepared = prepare_linkage_scope(self.root, case[0], case[1])
                self.assertEqual(prepared["route"], "source_fact_card_only")
                self.assertEqual(prepared["months"], [])
                self.assertIsNone(prepared["statistical_population"])
                with self.assertRaisesRegex(ValueError, "不能请求"):
                    prepare_linkage_scope(self.root, case[0], case[1], start_month="2026-07")
                with self.assertRaisesRegex(ValueError, "中国大陆贸易背景"):
                    build_country_context_report(self.root, prepared)
                card = build_source_fact_card(self.root, prepared)
                self.assertEqual(card["context_type"], "source_only")
                self.assertEqual(card["monthly"], [])
                self.assertEqual(card["chart_status"], "not_available")
                self.assertEqual(card["policy_amount_status"], "not_determined")
                self.assertTrue(any(item["dimension"] == dimension
                                    for item in card["scope"]["unobserved_eligibility"]))
                self.assertEqual(len(card["policy"]["confirmed_fields"]), len(REQUIRED_FIELDS))
                saved = generate_source_fact_record(self.root, prepared)
                self.assertEqual(load_record(self.root, saved["report_id"])["report"], card)
                self.assertFalse(saved["explanation"]["available"])
                with self.assertRaisesRegex(ValueError, "不支持模型解读"):
                    claim_call(self.root, saved["report_id"], saved["report_sha256"],
                               model="test", config_sha256="0" * 64,
                               request_sha256="0" * 64)

    def test_source_card_rejects_wrong_route_and_reconfirmed_assessment(self):
        case = self._case("source-stale", text="Postal goods of China below $800.")
        first = self._proposal("no_statistical_link", case[2],
                               defining=True, dimension="shipment_value")
        self._confirm(case, first)
        prepared = prepare_linkage_scope(self.root, case[0], case[1])
        revised = self._proposal("no_statistical_link", case[2],
                                 defining=True, dimension="shipment_value")
        revised["policy_scope_summary"] = "新确认的邮寄货品范围"
        self._confirm(case, revised)
        with self.assertRaisesRegex(ValueError, "已变化"):
            generate_source_fact_record(self.root, prepared)
        self.assertFalse(list((self.root / ".local/trade-reports").glob("*.json")))
        with self.assertRaisesRegex(ValueError, "原文事实卡"):
            build_source_fact_card(self.root, {**prepared, "route": "announcement-context-report-v1:country"})

    def test_postal_population_cannot_be_promoted_to_country_context(self):
        case = self._case("postal-country", text="Postal shipments of China below $800.")
        proposal = self._proposal("country_context", case[2],
                                  defining=True, dimension="shipping_method")
        with self.assertRaisesRegex(ValueError, "国家总量"):
            self._confirm(case, proposal)

    def test_wrong_origin_unknown_origin_and_missing_hk_quote_rejected(self):
        other = self._case("other-origin", text="Goods of Mexico, HTS 28046100.", origin="Mexico")
        with self.assertRaisesRegex(ValueError, "不符"):
            self._confirm(other, self._proposal("country_context", other[2]))
        china = self._case("no-hk-quote", text="Broad goods of China.")
        with self.assertRaisesRegex(ValueError, "涉及香港"):
            self._confirm(china, self._proposal(
                "country_context", china[2], origin_alignment="mainland_subset_of_china_hk"))

    def test_hong_kong_in_original_cannot_be_hidden_by_mainland_label(self):
        case = self._case("hk-hidden", text="Goods of China, including Hong Kong.",
                          scope_fields_reviewed=True)
        with self.assertRaisesRegex(ValueError, "涉及香港"):
            self._confirm(case, self._proposal("country_context", case[2]))

    def test_country_context_rejects_unreviewed_conditions(self):
        case = self._case("conditions-unknown", text="Broad goods of China with exceptions.")
        with self.assertRaisesRegex(ValueError, "逐项确认"):
            self._confirm(case, self._proposal("country_context", case[2]))

    def test_stale_candidate_source_and_quote_fail_closed(self):
        case = self._case("stale", text="Goods of China, HTS 28046100.",
                          codes=[{"code": "28046100", "precision": "whole_hts8"}])
        bad = self._proposal("code_aligned", case[2])
        bad["evidence"] = [{**case[2], "quote": "not in the notice"}]
        with self.assertRaisesRegex(ValueError, "引文"):
            self._confirm(case, bad)
        self._confirm(case, self._proposal("code_aligned", case[2]))
        store = load_announcement_store(self.root, case[0])
        store["announcement_candidates"][case[1]]["candidate"]["candidate_digest"] = "0" * 64
        save_announcement_store(self.root, case[0], store)
        with self.assertRaises(ValueError):
            load_linkage_assessment(self.root, case[0], case[1])
        store = load_announcement_store(self.root, case[0])
        store["documents"][0]["sections"][0]["text"] = "modified notice"
        with self.assertRaisesRegex(ValueError, "doc_version"):
            save_announcement_store(self.root, case[0], store)

    def test_unqueryable_month_and_tampered_prepare_are_rejected(self):
        case = self._case("months", text="Goods of China, except HTS 8413919039.",
                          codes=[{"code": "8413919039", "precision": "hts10_partial"}])
        self._confirm(case, self._proposal("parent_context", case[2], code="84139190"))
        with self.assertRaisesRegex(ValueError, "未发布"):
            prepare_linkage_scope(self.root, case[0], case[1],
                                  start_month="2026-06", end_month="2026-07")
        prepared = prepare_linkage_scope(self.root, case[0], case[1],
                                         start_month="2026-07", end_month="2026-07")
        prepared["statistical_population"] = "政策影响额"
        with self.assertRaisesRegex(ValueError, "已变化"):
            validate_prepared_linkage_scope(self.root, prepared)

    def test_malformed_relation_and_condition_are_controlled_rejections(self):
        case = self._case("malformed", text="Goods of China.")
        for key, value in (("relation", []), ("origin_alignment", {})):
            proposal = self._proposal("no_statistical_link", case[2], defining=True)
            proposal[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self._confirm(case, proposal)
        proposal = self._proposal("no_statistical_link", case[2], defining=True)
        proposal["unobserved_eligibility"][0]["dimension"] = []
        with self.assertRaises(ValueError):
            self._confirm(case, proposal)

    def test_reconfirmed_assessment_invalidates_old_prepared_scope(self):
        case = self._case("reconfirm", text="Goods of China, except HTS 8413919039.",
                          codes=[{"code": "8413919039", "precision": "hts10_partial"}])
        first = self._proposal("parent_context", case[2], code="84139190")
        self._confirm(case, first)
        prepared = prepare_linkage_scope(self.root, case[0], case[1],
                                         start_month="2026-07", end_month="2026-07")
        revised = self._proposal("parent_context", case[2], code="84139190")
        revised["policy_scope_summary"] = "重新人工确认的更窄文字条件"
        self._confirm(case, revised)
        with self.assertRaisesRegex(ValueError, "已变化"):
            validate_prepared_linkage_scope(self.root, prepared)


if __name__ == "__main__":
    unittest.main()
