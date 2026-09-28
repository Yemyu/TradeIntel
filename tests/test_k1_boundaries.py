"""K1 boundary tests (execution plan 2026-09-16, per Astra J-acceptance).

K1a announcement import path safety (allowlist + containment + concurrency).
K1b A3 export gate compares the FULL confirmation binding (report hash,
    data_version, catalog digest, response kind); metadata-only changes also
    invalidate.  Shared gate function tested at route level.
K1c task/evidence supports both orders (confirm-then-start and
    start-then-confirm) with server-side digest/version verification.
K1d a legal session with a mismatched client version expectation reaches the
    version check and is refused there.
"""
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]

from src.tradeintel_ai.session_store import (create_session, load_session,
                                             save_session, set_request, start_task)
from src.tradeintel_ai.web_app import (_handle_announcement_import,
                                       _handle_session_post, _program_draft_gate)

REQUEST = {"policy_id": "us_301_review2025_tungsten_solar", "month": "2026-07",
           "product": "all", "focus": "contrast"}


def _active_version():
    from tradeintel_ai.exposure_version_store import ExposureVersionStore
    from tradeintel_ai.policy_cases import CASES
    case = CASES[REQUEST["policy_id"]]
    store = ExposureVersionStore(ROOT, ROOT / case.versions)
    return store.active_version()


class K1aAnnouncementPathTests(unittest.TestCase):
    """Path-traversal and injection counter-examples; no network needed."""

    def _import(self, policy_id):
        return _handle_announcement_import(tempfile.mkdtemp(prefix="k1a-"), {
            "policy_id": policy_id, "source_id": "notice:test:p1",
            "text": "Official notice text long enough for the import path check."})

    def test_dotdot_is_refused(self):
        with self.assertRaises(ValueError):
            self._import("../evil")

    def test_absolute_path_is_refused(self):
        with self.assertRaises(ValueError):
            self._import("/abs/path")

    def test_separator_is_refused(self):
        with self.assertRaises(ValueError):
            self._import("a/b")

    def test_backslash_is_refused(self):
        with self.assertRaises(ValueError):
            self._import("a\\b")

    def test_empty_policy_id_is_refused(self):
        with self.assertRaises(ValueError):
            self._import("")

    def test_overlong_policy_id_is_refused(self):
        with self.assertRaises(ValueError):
            self._import("a" * 65)

    def test_dotdot_inside_long_id_is_refused(self):
        with self.assertRaises(ValueError):
            self._import("case..2026")

    def test_concurrent_imports_keep_both_documents(self):
        root = Path(tempfile.mkdtemp(prefix="k1a-concurrent-"))
        payloads = [{"policy_id": "case", "source_id": f"notice:{i}",
                     "text": f"Official notice number {i} with enough body text."}
                    for i in range(2)]
        errors = []

        def run(payload):
            try:
                _handle_announcement_import(root, payload)
            except Exception as exc:  # pragma: no cover - surfaced via assertion
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(p,)) for p in payloads]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        store = __import__("json").loads(
            (root / ".local" / "announcement-docs" / "case.json").read_text(encoding="utf-8"))
        self.assertEqual(len({d["doc_version"] for d in store["documents"]}), 2)


class K1bProgramDraftGateTests(unittest.TestCase):
    def _task(self, *, data_version="v1", catalog="c" * 64, kind="program-report-a3",
              markdown="# A3 body"):
        task = {"response": {"kind": kind, "data_version": data_version,
                             "catalog_sha256": catalog, "a3_markdown": markdown}}
        task["confirmations"] = [{
            "confirmation_type": "program_draft_confirmation",
            "report_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            "data_version": data_version, "catalog_sha256": catalog,
            "response_kind": kind, "operator": "reviewer"}]
        return task

    def test_full_match_passes(self):
        self.assertIsNone(_program_draft_gate(self._task()))

    def test_changed_body_is_refused(self):
        task = self._task()
        task["response"]["a3_markdown"] = "# replaced"
        self.assertIsNotNone(_program_draft_gate(task))

    def test_metadata_only_change_is_refused(self):
        task = self._task()
        task["response"]["data_version"] = "v2"  # body untouched
        self.assertIsNotNone(_program_draft_gate(task))

    def test_catalog_only_change_is_refused(self):
        task = self._task()
        task["response"]["catalog_sha256"] = "d" * 64
        self.assertIsNotNone(_program_draft_gate(task))

    def test_kind_change_is_refused(self):
        task = self._task()
        task["response"]["kind"] = "ai-answer"
        self.assertIsNotNone(_program_draft_gate(task))

    def test_missing_confirmation_is_refused(self):
        task = self._task()
        task["confirmations"] = []
        self.assertIsNotNone(_program_draft_gate(task))

    def test_confirmation_kind_mismatch_is_refused(self):
        task = self._task()
        task["confirmations"][-1]["response_kind"] = "other"
        self.assertIsNotNone(_program_draft_gate(task))

    def test_ai_content_is_refused_even_when_confirmed(self):
        task = self._task(kind="ai-answer")
        task["confirmations"][-1]["response_kind"] = "ai-answer"
        self.assertIn("逐项审阅", _program_draft_gate(task))


class K1cEvidenceOrderTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT

    def _handler(self, path, payload):
        return _handle_session_post(self.root, path, payload, repository=None)

    def test_order_a_start_then_confirm_then_evidence(self):
        session = create_session(self.root)
        created = self._handler("/api/session/task/start", {
            "session_id": session["session_id"], "prompt_digest": "p",
            "request": REQUEST})
        self.assertEqual(created["status"], "create")
        self._handler("/api/session/request", {
            "session_id": session["session_id"], "request": REQUEST,
            "data_version": _active_version()})
        result = self._handler("/api/session/task/evidence", {
            "session_id": session["session_id"], "task_id": created["task_id"]})
        self.assertEqual(result["status"], "evidence_ready")
        self.assertEqual(result["bound_version"], _active_version())

    def test_order_b_confirm_then_start_then_evidence(self):
        session = create_session(self.root)
        self._handler("/api/session/request", {
            "session_id": session["session_id"], "request": REQUEST,
            "data_version": _active_version()})
        created = self._handler("/api/session/task/start", {
            "session_id": session["session_id"], "prompt_digest": "p",
            "request": REQUEST})
        result = self._handler("/api/session/task/evidence", {
            "session_id": session["session_id"], "task_id": created["task_id"]})
        self.assertEqual(result["status"], "evidence_ready")

    def test_confirmed_request_changed_without_reconfirm_is_refused(self):
        session = create_session(self.root)
        self._handler("/api/session/request", {
            "session_id": session["session_id"], "request": REQUEST,
            "data_version": _active_version()})
        created = self._handler("/api/session/task/start", {
            "session_id": session["session_id"], "prompt_digest": "p",
            "request": REQUEST})
        # The handler moved the on-disk session; reload before the next write.
        session = load_session(self.root, session["session_id"])
        other = dict(REQUEST, month="2026-06")
        set_request(self.root, session, other, data_version=_active_version())
        with self.assertRaises(ValueError):
            self._handler("/api/session/task/evidence", {
                "session_id": session["session_id"], "task_id": created["task_id"]})

    def test_bound_version_changed_on_disk_is_refused(self):
        session = create_session(self.root)
        self._handler("/api/session/request", {
            "session_id": session["session_id"], "request": REQUEST,
            "data_version": _active_version()})
        created = self._handler("/api/session/task/start", {
            "session_id": session["session_id"], "prompt_digest": "p",
            "request": REQUEST})
        # Simulate a re-confirmation that changed only the bound version.
        fresh = load_session(self.root, session["session_id"])
        fresh["data_version"] = "f" * 64
        save_session(self.root, fresh)
        with self.assertRaises(ValueError):
            self._handler("/api/session/task/evidence", {
                "session_id": session["session_id"], "task_id": created["task_id"]})


class K1dVersionExpectationRouteTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT

    def test_legal_session_with_wrong_version_reaches_version_check(self):
        session = create_session(self.root)
        with self.assertRaises(ValueError) as caught:
            _handle_session_post(self.root, "/api/session/request", {
                "session_id": session["session_id"], "request": REQUEST,
                "data_version": "0" * 64}, repository=None)
        self.assertIn("期望与服务器登记版本不一致", str(caught.exception))

    def test_legal_session_with_matching_version_is_confirmed(self):
        session = create_session(self.root)
        result = _handle_session_post(self.root, "/api/session/request", {
            "session_id": session["session_id"], "request": REQUEST,
            "data_version": _active_version()}, repository=None)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["bound_version"], _active_version())


if __name__ == "__main__":
    unittest.main()
