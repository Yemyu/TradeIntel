"""One frozen HTTP replay of the pre-registered FR-2025-16733 case."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "src"))
from tradeintel_ai.web_app import create_server  # noqa: E402

HERE = Path(__file__).resolve().parent
CASE = PROJECT / "tmp/unseen-linkage-case2-20260927"
PACKET = CASE / "frozen-packet"
RUN = CASE / "product-replay-1"
PREREG = PROJECT / "docs/handoff/UNSEEN_LINKAGE_CASE2_PREREG_20260927.zh-CN.md"
REFERENCE_SHA = "d403ac77ac89a998847a2b9bad810705aec54a2d85923724f828eb27c1be2675"
SOURCE_SHA = "deb739fb211f977566c0a0aba29d9d110d8701dbbeab2b99ef6f778603134183"
TEXT_SHA = "c138297f650b0713f6275fa4be1cb78719915fb8926f06d61692a0370dc6d31f"
PREREG_SHA = "0e1094a2dd2ec48c729df8b2c4f2b1a7f9ff13e65d392913bb9e460b5df6595c"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pins() -> dict[str, str]:
    pinned = {
        "reference": (HERE / "reference.json", REFERENCE_SHA),
        "source": (CASE / "2025-16733.htm", SOURCE_SHA),
        "text": (PACKET / "source-text.txt", TEXT_SHA),
        "prereg": (PREREG, PREREG_SHA),
    }
    for line in PROJECT.joinpath("docs/handoff/UNSEEN_LINKAGE_CASE_PREREG_20260927.zh-CN.md").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (src/[^ ]+|web/[^ ]+|data/[^ ]+)", line)
        if match:
            expected, relative = match.groups()
            if relative == "web/design-preview/live.js":
                expected = "93ab1cf4e4c73c7b8847f85c6ffe44230b758196206cdba2cee2d8d3989ce752"
            pinned[relative] = (PROJECT / relative, expected)
    if len(pinned) != 20:
        raise AssertionError(f"Expected 16 product/data pins and four case pins; found {len(pinned)}")
    for name, (path, expected) in pinned.items():
        actual = sha(path)
        if actual != expected:
            raise AssertionError(f"Frozen input changed: {name}: {actual}")
    return {name: expected for name, (_, expected) in pinned.items()}


def http(base: str, path: str, body: dict | None = None):
    req = Request(base + path,
                  data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                  headers={"Origin": base, "Content-Type": "application/json"} if body is not None else {},
                  method="POST" if body is not None else "GET")
    try:
        response = urlopen(req, timeout=40)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read().decode("utf-8")
        content_type = response.headers.get("Content-Type", "")
        return response.status, json.loads(raw) if "json" in content_type else raw


def checked(base: str, path: str, body: dict | None = None):
    status, result = http(base, path, body)
    if status != 200:
        raise AssertionError(f"{path}: HTTP {status}: {str(result)[:500]}")
    return result


def save(name: str, value) -> None:
    (RUN / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def start():
    server = create_server(root=RUN, host="127.0.0.1", port=0, output_root=RUN / "runs")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def citation(quote_text: str, sections: list[dict], doc_version: str) -> dict:
    found = [section for section in sections if quote_text in section["text"]]
    if len(found) != 1:
        raise AssertionError(f"Reference quote missing/ambiguous: {quote_text[:80]}")
    return {"doc_version": doc_version, "section_id": found[0]["section_id"], "quote": quote_text}


def assert_fields(reference_fields: list, actual_fields: list):
    if len(actual_fields) != 13:
        raise AssertionError(f"13 fields required; got {len(actual_fields)}")
    by_name = {item["field"]: item for item in actual_fields}
    for expected in reference_fields:
        got = by_name[expected["field"]]
        for key in ("status", "value"):
            if got[key] != expected[key]:
                raise AssertionError(f"{expected['field']} {key} changed")
        if got.get("reason") != expected.get("reason"):
            raise AssertionError(f"{expected['field']} unknown reason changed")
        if [item["quote"] for item in got.get("evidence", [])] != expected["quotes"]:
            raise AssertionError(f"{expected['field']} quotation changed")


def main():
    pins = verify_pins()
    if RUN.exists():
        raise RuntimeError(f"First-run evidence already exists: {RUN}")
    RUN.mkdir(parents=True)
    (RUN / "web").symlink_to(PROJECT / "web", target_is_directory=True)
    save("input-pins.json", pins)
    reference = json.loads((HERE / "reference.json").read_text(encoding="utf-8"))
    text = (PACKET / "source-text.txt").read_text(encoding="utf-8")
    policy_id = reference["policy_id"]
    stage = "start"
    server = thread = None
    try:
        server, thread, base = start()
        stage = "import"
        imported = checked(base, "/api/announcements/import", {
            "policy_id": policy_id, "source_id": reference["source_id"],
            "url": reference["source_url"], "text": text,
            "sha256": reference["source_file_sha256"]})
        save("01-import.json", imported)
        assert imported["doc_status"] == "disabled"
        doc_version = imported["doc_version"]
        stage = "template"
        template = checked(base, "/api/announcements/template", {
            "policy_id": policy_id, "doc_version": doc_version})
        save("02-template.json", template)
        sections = template["sections"]
        assert len(sections) == 25, f"Expected 25 imported sections, got {len(sections)}"
        fields = []
        for item in reference["fields"]:
            row = {"field": item["field"], "status": item["status"], "value": item["value"]}
            if item["status"] == "unknown":
                row["reason"] = item["reason"]
            else:
                row["evidence"] = [citation(q, sections, doc_version) for q in item["quotes"]]
            fields.append(row)
        assert_fields(reference["fields"], fields)
        save("03-fields-submitted.json", fields)
        stage = "submit"
        submitted = checked(base, "/api/announcements/submit", {
            "policy_id": policy_id, "doc_version": doc_version, "fields": fields})
        save("04-submitted.json", submitted)
        assert submitted["status"] == "candidate_ready"
        stage = "enable"
        enabled = checked(base, "/api/announcements/enable", {
            "policy_id": policy_id, "doc_version": doc_version,
            "fields": fields, "candidate_digest": submitted["candidate_digest"],
            "operator": "astra-reference-replay"})
        save("05-enabled.json", enabled)
        assert enabled["status"] == "enabled"
        stage = "confirm"
        proposal = deepcopy(reference["linkage"])
        proposal["evidence"] = [citation(q, sections, doc_version) for q in proposal.pop("quotes")]
        confirmed = checked(base, "/api/announcements/linkage/confirm", {
            "policy_id": policy_id, "doc_version": doc_version,
            "proposal": proposal, "confirmed_by": "astra-reference-replay",
            "candidate_digest": submitted["candidate_digest"]})
        save("06-confirmed.json", confirmed)
        stage = "prepare"
        prepared = checked(base, "/api/announcements/linkage/prepare", {
            "policy_id": policy_id, "doc_version": doc_version})
        save("07-prepared.json", prepared)
        assert prepared["route"] == reference["expected"]["route"]
        assert prepared["months"] == []
        stage = "report"
        result = checked(base, "/api/announcements/linkage/report", {"prepared": prepared})
        save("08-report-response.json", result)
        report_id = result["report_id"]
        stage = "read-state"
        state = checked(base, "/api/trade/report-state?report_id=" + quote(report_id))
        save("09-state.json", state)
        assert state["report_sha256"] == result["report_sha256"]
        assert state["kind"] == reference["expected"]["kind"]
        assert state["context_type"] == reference["expected"]["context_type"]
        assert state["monthly"] == [] and state["chart_status"] == "not_available"
        assert state["policy_amount_status"] == "not_determined"
        assert state["policy"]["current_applicability_status"] == "not_verified"
        assert state["policy"]["rate_evidence_scope"] == "source_document_only"
        assert_fields(reference["fields"], state["policy"]["confirmed_fields"])
        assert state["policy"]["evidence"] == proposal["evidence"]
        assert state["scope"]["dataset_id"] is None
        assert not (RUN / "data").exists(), "Source-only replay unexpectedly created trade data"
        stage = "restart"
        stop(server, thread)
        server = thread = None
        server, thread, base = start()
        restored = checked(base, "/api/trade/report-state?report_id=" + quote(report_id))
        save("10-restored-state.json", restored)
        assert restored == state
        setup = checked(base, "/api/announcements/linkage/setup?policy_id=" + quote(policy_id)
                        + "&doc_version=" + quote(doc_version))
        save("11-restored-setup.json", setup)
        assert_fields(reference["fields"], setup["fields"])
        status, page = http(base, "/preview/?announcement_report_id=" + quote(report_id))
        assert status == 200 and "TradeIntel" in page
        save("result.json", {"status": "passed_http_and_restart", "case_id": reference["case_id"],
                             "report_id": report_id, "report_sha256": state["report_sha256"],
                             "doc_version": doc_version, "field_count": 13,
                             "route": prepared["route"], "chart_status": state["chart_status"],
                             "monthly_count": 0, "model_calls": 0,
                             "trade_data_root_present": False, "browser_check": "pending"})
        print(json.dumps({"status": "passed_http_and_restart", "report_id": report_id,
                          "url": base + "/preview/?announcement_report_id=" + quote(report_id)},
                         ensure_ascii=False), flush=True)
        if "--inspect" in sys.argv:
            try:
                input("Browser inspection running; press Enter to stop isolated server: ")
            except EOFError:
                pass
    except Exception as exc:
        error = {"status": "failed_first_run", "stage": stage,
                 "error_type": type(exc).__name__, "error": str(exc), "model_calls": 0}
        save("harness-error.json", error)
        raise
    finally:
        if server is not None:
            stop(server, thread)


if __name__ == "__main__":
    main()
