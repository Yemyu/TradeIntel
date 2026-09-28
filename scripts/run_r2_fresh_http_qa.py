#!/usr/bin/env python3
"""Rehearse a fresh R2 import and statistics report over localhost HTTP.

The pinned official HTML and published trade data are read only. All state is
created under a temporary directory and no model provider is contacted.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.run_r2_migration import (POLICY_ID, SOURCE_ID, SOURCE_URL,
                                      build_fields, extract_text)
from tradeintel_ai.announcement_flow import load_announcement_store
from tradeintel_ai.web_app import create_server


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "tmp/r2-20260920/2025-23912.html"


def request(base: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    headers = {"Origin": base, "Content-Type": "application/json"} if body is not None else {}
    req = Request(base + path, data=(json.dumps(body, ensure_ascii=False).encode()
                                   if body is not None else None), headers=headers,
                  method="POST" if body is not None else "GET")
    try:
        response = urlopen(req, timeout=180)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read().decode("utf-8")
        return response.status, (json.loads(raw) if "json" in response.headers.get("Content-Type", "")
                                 else raw)


def checked(base: str, path: str, body: dict | None = None) -> dict:
    status, payload = request(base, path, body)
    if status != 200 or not isinstance(payload, dict):
        raise AssertionError(f"{path}: HTTP {status}: {str(payload)[:400]}")
    return payload


def server_for(root: Path):
    server = create_server(root=root, host="127.0.0.1", port=0, output_root=root / "runs")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def stop(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true",
                        help="Keep the isolated localhost page open until Enter is pressed")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="r2-fresh-http-qa-") as directory:
        root = Path(directory)
        processed = root / "data/processed"
        processed.mkdir(parents=True)
        # Report generation only reads these published catalogs and files.
        for name in ("trade_hts10", "trade_scheduleb10", "trade_classification"):
            (processed / name).symlink_to(PROJECT / "data/processed" / name,
                                          target_is_directory=True)
        (root / "web").symlink_to(PROJECT / "web", target_is_directory=True)
        server, thread, base = server_for(root)
        try:
            status, page = request(base, "/announcement-import")
            assert status == 200 and "新公告导入" in page
            status, refusal = request(base, "/api/announcements/import", {
                "policy_id": POLICY_ID, "source_id": SOURCE_ID,
                "text": "x" * 262_144})
            assert status == 400 and refusal.get("message") == "请求体过大"
            status, refusal = request(base, "/api/announcements/statistics/prepare", {
                "policy_id": POLICY_ID, "doc_version": "x" * 16_384})
            assert status == 400 and refusal.get("message") == "请求体过大"
            imported = checked(base, "/api/announcements/import", {
                "policy_id": POLICY_ID, "source_id": SOURCE_ID,
                "url": SOURCE_URL, "text": extract_text(SOURCE),
                "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            })
            doc = imported["doc_version"]
            assert imported["doc_status"] == "disabled"
            store = load_announcement_store(root, POLICY_ID)
            assert store["documents"][0]["status"] == "disabled"
            template = checked(base, "/api/announcements/template", {
                "policy_id": POLICY_ID, "doc_version": doc})
            assert len(template["fields"]) == 13
            status, refusal = request(base, "/api/announcements/statistics/prepare", {
                "policy_id": POLICY_ID, "doc_version": doc})
            assert status == 422, f"disabled 公告不得生成统计报告：HTTP {status}: {refusal}"

            fields = build_fields(store, doc)
            submitted = checked(base, "/api/announcements/submit", {
                "policy_id": POLICY_ID, "doc_version": doc, "fields": fields})
            assert submitted["status"] == "candidate_ready"
            changed = deepcopy(fields)
            changed[0]["value"] = "unconfirmed change"
            status, _ = request(base, "/api/announcements/enable", {
                "policy_id": POLICY_ID, "doc_version": doc, "fields": changed,
                "candidate_digest": submitted["candidate_digest"]})
            assert status == 422, "确认前改字段不得启用"
            enabled = checked(base, "/api/announcements/enable", {
                "policy_id": POLICY_ID, "doc_version": doc, "fields": fields,
                "candidate_digest": submitted["candidate_digest"],
                "operator": "r2-fresh-http-qa"})
            assert enabled["status"] == "enabled" and enabled["rebind_required"]
            assert enabled["coverage"]["trade_coverage"] == "not_checked"
            prepared = checked(base, "/api/announcements/statistics/prepare", {
                "policy_id": POLICY_ID, "doc_version": doc,
                "start_month": "2025-08", "end_month": "2026-07"})
            assert len(prepared["selected_codes"]) == 18
            bad = deepcopy(prepared)
            bad["selected_codes"] = bad["selected_codes"][:1]
            status, _ = request(base, "/api/announcements/statistics/report", {"prepared": bad})
            assert status == 422, "改过的确认范围不得生成报告"
            generated = checked(base, "/api/announcements/statistics/report", {"prepared": prepared})
            report_id = generated["report_id"]
            state = checked(base, f"/api/trade/report-state?report_id={report_id}")
            report = state
            assert report["kind"] == "announcement-statistics-report-v1"
            assert report["policy"]["doc_version"] == doc
            assert report["policy"]["candidate_digest"] == submitted["candidate_digest"]
            assert report["policy"]["rate_evidence_scope"] == "source_document_only"
            assert report["policy"]["current_applicability_status"] == "not_verified"
            assert report["scope"]["selected_codes"] == prepared["selected_codes"]
            assert len(report["monthly"]) == 12
            assert report["policy_amount_status"] == "not_determined"
            assert report["monthly"][-1]["month"] == "2026-07"
            assert report["monthly"][-1]["observed_value_usd"] == 71062824
            assert state["explanation"]["status"] == "not_requested"
            status, preview = request(base, f"/preview/?announcement_report_id={report_id}")
            assert status == 200 and "TradeIntel" in preview
        finally:
            stop(server, thread)

        server, thread, base = server_for(root)
        try:
            restored = checked(base, f"/api/trade/report-state?report_id={report_id}")
            assert restored["report_sha256"] == state["report_sha256"]
            assert restored == state
            stored = load_announcement_store(root, POLICY_ID)
            assert stored["documents"][0]["status"] == "enabled"
            assert stored["announcement_candidates"][doc]["candidate_digest"] == submitted["candidate_digest"]
            print(json.dumps({"status": "passed", "source": str(SOURCE),
                              "doc_version": doc, "fields_confirmed": len(fields),
                              "selected_codes": len(prepared["selected_codes"]),
                              "months": len(report["monthly"]),
                              "latest_observed_usd": report["monthly"][-1]["observed_value_usd"],
                              "report_sha256": state["report_sha256"],
                              "restart_restored": True, "model_calls": 0,
                              "data_writes": "temporary directory only"},
                             ensure_ascii=False, indent=2), flush=True)
            if args.inspect:
                print(f"PREVIEW_URL={base}/preview/?announcement_report_id={report_id}#report",
                      flush=True)
                input("Inspect the isolated page, then press Enter to stop the server: ")
        finally:
            stop(server, thread)


if __name__ == "__main__":
    main()
