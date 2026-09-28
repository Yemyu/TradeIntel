#!/usr/bin/env python3
"""Exercise the R2 session flow over the real localhost HTTP server.

This is an offline route integration check. It uses no model provider and
keeps all writes inside a copied temporary R2 root.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
from urllib.request import Request, urlopen

from tradeintel_ai.web_app import create_server

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "tmp/r2-20260920/astra-semantic-review-2/temp-root"
POLICY = "r2_semiconductor_2025"
DOC = "docver-cbb131783801bd95"
CANDIDATE = "d252d295ae0280ffd51ec0ed8a92c0c4b3edf1ef971055f44b76d3a52c1b3727"
DATA = "91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b"
PRODUCTS = ["28046100", "38180000"]


def call(base: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    if body is None:
        request = Request(base + path)
    else:
        request = Request(base + path,
                          data=json.dumps(body, ensure_ascii=False).encode(),
                          headers={"Content-Type": "application/json", "Origin": base},
                          method="POST")
    with urlopen(request, timeout=10) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
    if "json" in content_type:
        return response.status, json.loads(raw.decode())
    return response.status, raw.decode()


def main() -> int:
    if not SOURCE_ROOT.is_dir():
        raise SystemExit(f"R2临时根目录不存在：{SOURCE_ROOT}")
    with tempfile.TemporaryDirectory(prefix="r2-http-qa-") as folder:
        root = Path(folder)
        shutil.copytree(SOURCE_ROOT, root, dirs_exist_ok=True)
        shutil.copytree(ROOT / "web", root / "web", dirs_exist_ok=True)
        server = create_server(root=root, host="127.0.0.1", port=0,
                               output_root=root / "runs")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            status, page = call(base, "/announcement-import")
            assert status == 200 and "新公告导入" in page
            status, coverage = call(base, "/api/announcements/coverage/check", {
                "policy_id": POLICY, "doc_version": DOC, "month": "2026-07",
                "requested_codes": PRODUCTS})
            assert status == 200 and coverage["trade_coverage"]["availability"] == "exact"
            session = call(base, "/api/session/create", {})[1]["session"]
            sid = session["session_id"]
            request = {"policy_id": POLICY, "month": "2026-07", "product": "all",
                       "products": PRODUCTS, "focus": "contrast"}
            binding = {"policy_id": POLICY, "doc_version": DOC,
                       "candidate_digest": CANDIDATE}
            started = call(base, "/api/session/task/start", {
                "session_id": sid, "model": "deterministic", "prompt_digest": "r2-http",
                "request": request})[1]
            task_id = started["task_id"]
            confirmed = call(base, "/api/session/request", {
                "session_id": sid, "request": request, "policy_binding": binding})[1]
            assert confirmed["status"] == "confirmed"
            evidence = call(base, "/api/session/task/evidence", {
                "session_id": sid, "task_id": task_id})[1]
            assert evidence["status"] == "evidence_ready"
            generated = call(base, "/api/session/task/generate", {
                "session_id": sid, "task_id": task_id})[1]
            assert generated["status"] == "needs_review"
            reviewed = call(base, "/api/session/task/transition", {
                "session_id": sid, "task_id": task_id, "state": "reviewed",
                "operator": "r2-http-qa", "reason": "QA"})[1]
            assert reviewed["status"] == "reviewed"
            exported_state = call(base, "/api/session/task/transition", {
                "session_id": sid, "task_id": task_id, "state": "exportable",
                "operator": "r2-http-qa", "reason": "QA"})[1]
            assert exported_state["status"] == "exportable"
            status, markdown = call(base, f"/api/session/export?session_id={sid}&task_id={task_id}")
            assert status == 200 and "program-report-a3" not in markdown
            digest = hashlib.sha256(markdown.encode()).hexdigest()
            refreshed = call(base, f"/api/session?session_id={sid}")[1]
            task = next(t for t in refreshed["tasks"].values() if t["task_id"] == task_id)
            assert task["state"] == "exportable"
            assert task["policy_binding"]["doc_version"] == DOC
            result = {"status": "passed", "browser_surface": "localhost HTTP route integration",
                      "page": "/announcement-import", "coverage": "exact 2/2 selected; full scope remains partial",
                      "flow": ["start", "confirm", "evidence_ready", "needs_review", "reviewed",
                               "exportable", "export"], "session_refresh_state": task["state"],
                      "export_sha256": digest, "model_calls": 0}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
