"""Offline HTTP checks for the four confirmed notice-to-trade routes."""
from __future__ import annotations

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.tradeintel_ai.web_app import create_server
from tests import test_announcement_linkage as linkage_fixture


class AnnouncementLinkageHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = linkage_fixture.AnnouncementLinkageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.server = create_server(root=self.root, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def post(self, route: str, body: dict) -> dict:
        request = Request(self.base + route, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request) as response:
            return json.loads(response.read())

    def get(self, route: str, params: dict) -> dict:
        with urlopen(self.base + route + "?" + urlencode(params)) as response:
            return json.loads(response.read())

    def confirm(self, case: tuple, proposal: dict) -> dict:
        from src.tradeintel_ai.announcement_flow import load_announcement_store
        store = load_announcement_store(self.root, case[0])
        digest = store["announcement_candidates"][case[1]]["candidate_digest"]
        return self.post("/api/announcements/linkage/confirm", {
            "policy_id": case[0], "doc_version": case[1],
            "proposal": proposal, "confirmed_by": "fixture-reviewer",
            "candidate_digest": digest})

    def test_parent_confirm_prepare_generate_and_refresh(self):
        case = self.fixture._case("http-parent", text="Products of China, exclusion at HTS 8413919039.",
                                  codes=[{"code": "8413919039", "precision": "hts10_partial"}])
        confirmed = self.confirm(case, self.fixture._proposal(
            "parent_context", case[2], code="84139190"))
        self.assertEqual(self.get("/api/announcements/linkage/assessment", {
            "policy_id": case[0], "doc_version": case[1]})["assessment_digest"],
            confirmed["assessment_digest"])
        prepared = self.post("/api/announcements/linkage/prepare", {
            "policy_id": case[0], "doc_version": case[1],
            "start_month": "2026-07", "end_month": "2026-07"})
        self.assertEqual(prepared["route"], "announcement-context-report-v1:parent")
        saved = self.post("/api/announcements/linkage/report", {"prepared": prepared})
        self.assertEqual(saved["monthly"][0]["whole_parent_value_usd"], 300)
        self.assertEqual(self.get("/api/trade/report-state", {"report_id": saved["report_id"]})
                         ["report_sha256"], saved["report_sha256"])
        prepared["statistical_population"] = "政策覆盖额"
        with self.assertRaises(HTTPError) as changed:
            self.post("/api/announcements/linkage/report", {"prepared": prepared})
        self.assertEqual(changed.exception.code, 422)
        changed.exception.close()

    def test_no_statistical_link_never_queries_trade(self):
        case = self.fixture._case("http-postal", text="Postal shipments from China below $800.")
        self.confirm(case, self.fixture._proposal("no_statistical_link", case[2],
                                                  defining=True, dimension="shipping_method"))
        prepared = self.post("/api/announcements/linkage/prepare", {
            "policy_id": case[0], "doc_version": case[1]})
        self.assertEqual(prepared["route"], "source_fact_card_only")
        saved = self.post("/api/announcements/linkage/report", {"prepared": prepared})
        self.assertEqual(saved["monthly"], [])
        self.assertEqual(saved["chart_status"], "not_available")
        with self.assertRaises(HTTPError) as month:
            self.post("/api/announcements/linkage/prepare", {
                "policy_id": case[0], "doc_version": case[1],
                "start_month": "2026-07"})
        self.assertEqual(month.exception.code, 422)
        month.exception.close()

    def test_country_context_reconciles_source_via_http(self):
        self.fixture._country_raw_fixture()
        case = self.fixture._case(
            "http-country", text="Broad goods of China and Hong Kong, with exceptions.",
            origin="China and Hong Kong", scope_fields_reviewed=True)
        self.confirm(case, self.fixture._proposal(
            "country_context", case[2], origin_alignment="mainland_subset_of_china_hk"))
        prepared = self.post("/api/announcements/linkage/prepare", {
            "policy_id": case[0], "doc_version": case[1],
            "start_month": "2026-07", "end_month": "2026-07"})
        self.assertEqual(prepared["route"], "announcement-context-report-v1:country")
        saved = self.post("/api/announcements/linkage/report", {"prepared": prepared})
        self.assertEqual(saved["monthly"][0]["china_mainland_import_value_usd"], 100)
        self.assertFalse(saved["scope"]["hong_kong_included_in_statistics"])
        self.assertEqual(self.get("/api/trade/report-state", {"report_id": saved["report_id"]})
                         ["report_sha256"], saved["report_sha256"])

    def test_whole_code_routes_to_existing_statistics_report(self):
        case = self.fixture._case(
            "http-whole", text="Products of China, HTS 28046100; exceptions apply.",
            codes=[{"code": "28046100", "precision": "whole_hts8"}])
        self.confirm(case, self.fixture._proposal("code_aligned", case[2]))
        prepared = self.post("/api/announcements/linkage/prepare", {
            "policy_id": case[0], "doc_version": case[1],
            "start_month": "2026-07", "end_month": "2026-07"})
        self.assertEqual(prepared["route"], "announcement-statistics-report-v1")
        saved = self.post("/api/announcements/linkage/report", {"prepared": prepared})
        self.assertEqual(saved["kind"], "announcement-statistics-report-v1")
        self.assertEqual(saved["scope"]["selected_codes"], ["28046100"])


if __name__ == "__main__":
    unittest.main()
