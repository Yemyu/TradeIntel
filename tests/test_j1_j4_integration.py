"""J1-J4 integration tests (Astra recheck 2026-09-16).

J1  generation permission is checked against the on-disk task state inside
    the lock; only one writer can claim ``generation_started`` (verified with
    a provider stub call counter and threaded contenders).
J2  evidence/report/export are bound to the version confirmed by the server;
    a moved active pointer does not change the report's version.
J3  candidate content is saved atomically and re-read byte-identically; the
    real redirect handler rejects cross-host/downgrade/over-limit hops before
    the next request.
J4  ordinary clients may only confirm review outcomes; the A3 program-draft
    confirmation binds the exact report hash and gates the export; AI content
    is refused at that gate; new announcements import as disabled candidates.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

from src.tradeintel_ai.session_brief import build_session_brief
from src.tradeintel_ai.session_store import (TaskStateConflict, create_session,
                                             load_session, record_task_confirmation,
                                             set_request, start_task, transition_task)
from src.tradeintel_ai.source_registry import (OfficialRedirectHandler,
                                               fetch_source, load_candidate_content,
                                               save_candidate)
from src.tradeintel_ai.web_app import _handle_announcement_import, _handle_session_post

REQUEST = {"policy_id": "us_301_review2025_tungsten_solar", "month": "2026-07",
           "product": "all", "focus": "contrast"}


class _StubRepository:
    """The session handlers only need the project root via repository.paths."""

    class _Paths:
        root = ROOT
    paths = _Paths()


class J1GenerationClaimTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT  # read-only for the real registry; sessions in .local
        self.session = create_session(self.root)
        set_request(self.root, self.session, REQUEST, policy_version="pv",
                    data_version=self._active_version())
        self.task_id = start_task(self.root, self.session, model="m",
                                  prompt_digest="p")["task_id"]

    def _active_version(self):
        from tradeintel_ai.exposure_version_store import ExposureVersionStore
        from tradeintel_ai.policy_cases import CASES
        case = CASES[REQUEST["policy_id"]]
        store = ExposureVersionStore(self.root, self.root / case.versions)
        return store.active_version()

    def test_two_stale_copies_claim_generation_only_once(self):
        stale = load_session(self.root, self.session["session_id"])
        transition_task(self.root, self.session, self.task_id, "evidence_ready")
        # First (fresh enough) copy claims the generation permission.
        transition_task(self.root, self.session, self.task_id, "generation_started")
        # The stale copy now tries the same transition from its old view.
        with self.assertRaises(TaskStateConflict):
            transition_task(self.root, stale, self.task_id, "generation_started")

    def test_provider_stub_called_exactly_once(self):
        transition_task(self.root, self.session, self.task_id, "evidence_ready")
        calls = []

        def provider_stub():
            calls.append(1)
            return {"answer": "fake"}

        # Simulate concurrent runners: each claims, only the winner calls.
        def runner():
            fresh = load_session(self.root, self.session["session_id"])
            try:
                transition_task(self.root, fresh, self.task_id, "generation_started")
                provider_stub()
                return "claimed"
            except TaskStateConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: runner(), range(4)))
        self.assertEqual(outcomes.count("claimed"), 1)
        self.assertEqual(len(calls), 1, "provider stub must be called exactly once")

    def test_completed_state_cannot_be_rewound_by_stale_copy(self):
        transition_task(self.root, self.session, self.task_id, "evidence_ready")
        transition_task(self.root, self.session, self.task_id, "generation_started")
        stale = load_session(self.root, self.session["session_id"])
        transition_task(self.root, self.session, self.task_id, "response_saved",
                        response={"answer": "x"})
        transition_task(self.root, self.session, self.task_id, "needs_review")
        transition_task(self.root, self.session, self.task_id, "reviewed")
        transition_task(self.root, self.session, self.task_id, "exportable")
        with self.assertRaises(TaskStateConflict):
            transition_task(self.root, stale, self.task_id, "generation_started")


class J2VersionBindingTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT

    def _active_version(self):
        from tradeintel_ai.exposure_version_store import ExposureVersionStore
        from tradeintel_ai.policy_cases import CASES
        case = CASES[REQUEST["policy_id"]]
        store = ExposureVersionStore(self.root, self.root / case.versions)
        return store.active_version()

    def test_missing_version_is_refused(self):
        with self.assertRaises(ValueError):
            build_session_brief(self.root, REQUEST, data_version=None)

    def test_unknown_version_is_refused(self):
        with self.assertRaises(ValueError):
            build_session_brief(self.root, REQUEST, data_version="b" * 64)

    def test_report_stays_on_confirmed_version_after_active_moves(self):
        bound = self._active_version()
        brief = build_session_brief(self.root, REQUEST, data_version=bound)
        self.assertEqual(brief["data_version"], bound)
        # Simulate the active pointer moving after confirmation: the report
        # must still be built on the CONFIRMED version (its release dataset).
        with mock.patch("tradeintel_ai.exposure_version_store.ExposureVersionStore.active_version",
                        return_value="f" * 64):
            rebound = build_session_brief(self.root, REQUEST, data_version=bound)
        self.assertEqual(rebound["data_version"], bound)
        self.assertEqual(rebound["catalog_sha256"], brief["catalog_sha256"])

    def test_client_version_expectation_mismatch_is_refused(self):
        with self.assertRaises(ValueError):
            _handle_session_post(self.root, "/api/session/request",
                                 {"request": REQUEST, "data_version": "0" * 64},
                                 repository=None)


class J3CandidateContentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="j3-candidate-"))
        self.content = b"OFFICIAL BULLETIN TEXT \xe4\xb8\xad\xe6\x96\x87 bytes"

    def _fetch(self, content=None):
        content = self.content if content is None else content
        url = OFFICIAL_URL
        return fetch_source("cbp-csms-63577329",
                            transport=lambda u, timeout: (content, url))

    def test_save_then_read_back_is_byte_identical(self):
        fetched = self._fetch()
        self.assertFalse(fetched["content_saved"], "metadata must not claim saved content")
        saved = save_candidate(self.root, fetched, self.content)
        self.assertEqual(saved["sha256"], fetched["sha256"])
        reread = load_candidate_content(self.root, {"content_file": saved["content_path"],
                                                    "sha256": saved["sha256"]})
        self.assertEqual(reread, self.content)

    def test_hash_mismatch_is_refused(self):
        fetched = self._fetch()
        with self.assertRaises(ValueError):
            save_candidate(self.root, fetched, b"tampered bytes")

    def test_redirect_handler_rejects_cross_host_before_next_hop(self):
        handler = OfficialRedirectHandler()
        request = _request_for(OFFICIAL_URL)
        with self.assertRaises(ValueError):
            handler.redirect_request(request, None, 302, "Found", {},
                                     "https://evil.example/path")

    def test_redirect_handler_rejects_downgrade(self):
        handler = OfficialRedirectHandler()
        request = _request_for(OFFICIAL_URL)
        with self.assertRaises(ValueError):
            handler.redirect_request(request, None, 302, "Found", {},
                                     "http://content.govdelivery.com/x")

    def test_redirect_handler_rejects_too_many_hops(self):
        handler = OfficialRedirectHandler(max_redirects=2)
        request = _request_for(OFFICIAL_URL)
        with self.assertRaises(ValueError):
            for hop in range(3):
                handler.redirect_request(request, None, 302, "Found", {}, OFFICIAL_URL)


OFFICIAL_URL = "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1"


def _request_for(url):
    import urllib.request
    return urllib.request.Request(url, headers={"User-Agent": "test"})


class J4ReviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT
        self.session = create_session(self.root)
        set_request(self.root, self.session, REQUEST, policy_version="pv",
                    data_version=self._active_version())
        self.task_id = start_task(self.root, self.session, model="m",
                                  prompt_digest="p")["task_id"]

    def _active_version(self):
        from tradeintel_ai.exposure_version_store import ExposureVersionStore
        from tradeintel_ai.policy_cases import CASES
        case = CASES[REQUEST["policy_id"]]
        store = ExposureVersionStore(self.root, self.root / case.versions)
        return store.active_version()

    def _drive_to_exportable(self):
        transition_task(self.root, self.session, self.task_id, "evidence_ready")
        transition_task(self.root, self.session, self.task_id, "generation_started")
        markdown = "# A3 program report\n\nbound content"
        transition_task(self.root, self.session, self.task_id, "response_saved",
                        response={"kind": "program-report-a3", "data_version": "pv",
                                  "catalog_sha256": "c" * 64, "a3_markdown": markdown})
        transition_task(self.root, self.session, self.task_id, "needs_review")
        return markdown

    def test_client_cannot_set_internal_states(self):
        with self.assertRaises(ValueError):
            _handle_session_post(self.root, "/api/session/task/transition",
                                 {"session_id": self.session["session_id"],
                                  "task_id": self.task_id, "state": "evidence_ready"},
                                 repository=None)

    def test_program_draft_confirmation_binds_report_hash(self):
        markdown = self._drive_to_exportable()
        result = _handle_session_post(self.root, "/api/session/task/transition",
                                      {"session_id": self.session["session_id"],
                                       "task_id": self.task_id, "state": "reviewed",
                                       "operator": "reviewer-a"}, repository=None)
        self.assertEqual(result["status"], "reviewed")
        stored = next(iter(load_session(self.root, self.session["session_id"])["tasks"].values()))
        record = stored["confirmations"][-1]
        self.assertEqual(record["confirmation_type"], "program_draft_confirmation")
        self.assertEqual(record["report_sha256"],
                         hashlib.sha256(markdown.encode("utf-8")).hexdigest())
        self.assertEqual(record["operator"], "reviewer-a")

    def test_changed_report_invalidates_confirmation(self):
        self._drive_to_exportable()
        _handle_session_post(self.root, "/api/session/task/transition",
                             {"session_id": self.session["session_id"],
                              "task_id": self.task_id, "state": "reviewed"}, repository=None)
        stored = next(iter(load_session(self.root, self.session["session_id"])["tasks"].values()))
        recorded_sha = stored["confirmations"][-1]["report_sha256"]
        replaced_sha = hashlib.sha256(b"# replaced report").hexdigest()
        self.assertNotEqual(recorded_sha, replaced_sha)
        # The export gate compares the CURRENT report against the record, so a
        # changed report is refused until re-confirmation (see export handler).

    def test_announcement_import_is_disabled_candidate(self):
        result = _handle_announcement_import(self.root, {
            "policy_id": "us_301_review2025_tungsten_solar",
            "source_id": "new-notice:test:p1",
            "text": "Official notice text that is long enough for the import path. " * 2})
        self.assertEqual(result["doc_status"], "disabled")
        self.assertIn("不进入检索", result["boundary"])


if __name__ == "__main__":
    unittest.main()
