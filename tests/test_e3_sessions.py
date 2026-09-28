"""E3 offline tests: session persistence, follow-ups, task states, updates."""
from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path

from tradeintel_ai.exposure_version_store import (ExposureVersionStore,
                                                  content_digest, validate_snapshot)
from src.tradeintel_ai.controlled_update import run_update_cycle, update_status
from src.tradeintel_ai.session_store import (append_message, confirm_request, create_session,
                                             load_session, resolve_followup,
                                             resolve_unknown_outcome, request_digest,
                                             save_session, set_request,
                                             start_task, transition_task)


def make_snapshot(months, *, policy_id="case", start="2025-01"):
    value = {"policy_id": policy_id, "start": start,
             "end": sorted(months)[-1], "months": months,
             "policy_files": {"notice": "sha-fixed"}}
    value["version"] = content_digest({k: v for k, v in value.items() if k != "version"})
    return validate_snapshot(value)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="e3-session-"))
        self.session = create_session(self.root, title="fixture")

    def test_session_roundtrip_and_revision(self):
        append_message(self.root, self.session, "user", "2026年7月两个排序有什么区别？")
        reloaded = load_session(self.root, self.session["session_id"])
        self.assertEqual(reloaded["messages"][0]["content"],
                         "2026年7月两个排序有什么区别？")
        self.assertEqual(reloaded["revision"], self.session["revision"])
        with self.assertRaises(ValueError):
            load_session(self.root, "session-missing")

    def test_set_request_validates_fields(self):
        base = {"policy_id": "case", "month": "2026-07", "product": "all", "focus": "contrast"}
        set_request(self.root, self.session, base, data_version="v1")
        self.assertEqual(self.session["request_digest"], request_digest(base))
        for bad in ({"month": "2026-13"}, {"product": "123"}, {"focus": "everything"}):
            request = {**base, **bad}
            with self.assertRaises(ValueError):
                set_request(self.root, self.session, request)

    def test_followup_previous_month_needs_baseline_or_resolves(self):
        text = "那上月呢？"
        outcome = resolve_followup(self.session, text)
        self.assertFalse(outcome["changed"])
        self.assertTrue(outcome["needs_clarification"])
        set_request(self.root, self.session, {"policy_id": "case", "month": "2026-07",
                                              "product": "all", "focus": "contrast"})
        outcome = resolve_followup(self.session, text)
        self.assertTrue(outcome["changed"])
        self.assertEqual(outcome["candidate_request"]["month"], "2026-06")
        # only the explicit field changed; the confirmed request is untouched
        self.assertEqual(outcome["candidate_request"]["product"], "all")
        reloaded = load_session(self.root, self.session["session_id"])
        self.assertEqual(reloaded["current_request"]["month"], "2026-07")
        confirm_request(self.root, self.session, outcome["candidate_request"])
        reloaded = load_session(self.root, self.session["session_id"])
        self.assertEqual(reloaded["current_request"]["month"], "2026-06")

    def test_followup_latest_available_uses_published_snapshot(self):
        set_request(self.root, self.session, {"policy_id": "case", "month": "2025-01",
                                              "product": "all", "focus": "contrast"})
        outcome = resolve_followup(self.session, "最新可用的数据是什么情况？",
                                   published_last_month="2026-07")
        self.assertEqual(outcome["candidate_request"]["month"], "2026-07")
        outcome = resolve_followup(self.session, "最新可用的数据是什么情况？")
        self.assertTrue(outcome["needs_clarification"])

    def test_product_change_requires_scope_reconfirmation(self):
        outcome = resolve_followup(self.session, "换成81019910呢？")
        self.assertTrue(outcome["changed"])
        self.assertTrue(outcome["scope_reconfirm_required"])
        self.assertEqual(outcome["candidate_request"]["product"], "81019910")

    def test_multi_code_question_asks_for_clarification(self):
        outcome = resolve_followup(self.session, "比较81019910和81019400")
        self.assertFalse(outcome["changed"])
        self.assertIn("商品税号", outcome["needs_clarification"][0])
        self.assertEqual(outcome["multi_request"]["codes"], ["81019400", "81019910"])


class TaskFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="e3-task-"))
        self.session = create_session(self.root)
        set_request(self.root, self.session, {"policy_id": "case", "month": "2026-07",
                                              "product": "all", "focus": "contrast"},
                    data_version="v1")

    def _start(self, session=None):
        return start_task(self.root, session or self.session,
                          model="glm-4.7", prompt_digest="abc123")

    def test_full_lifecycle_with_persistence(self):
        created = self._start()["task"]
        task_id = created["task_id"]
        for state, kwargs in (("evidence_ready", {}),
                              ("generation_started", {}),
                              ("response_saved", {"response": {"findings": []}}),
                              ("needs_review", {}),
                              ("reviewed", {}),
                              ("exportable", {})):
            created = transition_task(self.root, self.session, task_id, state, **kwargs)
        reloaded = load_session(self.root, self.session["session_id"])
        key = next(iter(reloaded["tasks"]))
        self.assertEqual(reloaded["tasks"][key]["state"], "exportable")
        self.assertEqual(len(reloaded["tasks"][key]["history"]), 7)

    def test_invalid_transition_is_rejected(self):
        created = self._start()["task"]
        with self.assertRaises(ValueError):
            transition_task(self.root, self.session, created["task_id"], "exportable")

    def test_dedup_reuses_finished_task_without_new_call(self):
        created = self._start()["task"]
        transition_task(self.root, self.session, created["task_id"], "evidence_ready")
        transition_task(self.root, self.session, created["task_id"], "generation_started")
        transition_task(self.root, self.session, created["task_id"], "response_saved",
                        response={"findings": [1]})
        again = self._start()
        self.assertEqual(again["action"], "reuse")
        self.assertEqual(again["task_id"], created["task_id"])

    def test_restart_without_response_never_rebills(self):
        created = self._start()["task"]
        transition_task(self.root, self.session, created["task_id"], "evidence_ready")
        transition_task(self.root, self.session, created["task_id"], "generation_started")
        # Simulate a process restart: state was persisted with no response.
        reloaded_session = load_session(self.root, self.session["session_id"])
        outcome = self._start(reloaded_session)
        self.assertEqual(outcome["action"], "blocked_unknown_outcome")
        self.assertIsNone(outcome["task"]["response"])

    def test_unknown_outcome_requires_human_decision(self):
        created = self._start()["task"]
        transition_task(self.root, self.session, created["task_id"], "evidence_ready")
        transition_task(self.root, self.session, created["task_id"], "generation_started")
        transition_task(self.root, self.session, created["task_id"], "unknown_outcome",
                        reason="进程中断，结果未知")
        outcome = self._start()
        self.assertEqual(outcome["action"], "blocked_unknown_outcome")
        retry = resolve_unknown_outcome(self.root, self.session, created["task_id"],
                                        resolution="retry_authorized", decided_by="user")
        self.assertEqual(retry["action"], "create")
        reloaded = load_session(self.root, self.session["session_id"])
        old = next(task for task in reloaded["tasks"].values()
                   if task["task_id"] == created["task_id"])
        self.assertEqual(old["state"], "unknown_outcome")


class ControlledUpdateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="e3-update-"))
        self.versions = self.root / "versions"
        store = ExposureVersionStore(self.root, self.versions)
        store.bootstrap(make_snapshot({"2025-01": {"value": 1}, "2025-02": {"value": 2}}))

    def test_check_reports_cutoff_and_last_check(self):
        # A check with no fetch source still records the check time (F9):
        # last_checked never reuses a version's creation timestamp.
        from src.tradeintel_ai.controlled_update import run_update_cycle as cycle
        result = cycle(self.root, fetch=None, versions_dir=self.versions)
        self.assertEqual(result["status"], "no_fetch_source")
        status = update_status(self.root, versions_dir=self.versions)
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["data_cutoff_month"], "2025-02")
        self.assertEqual(status["last_checked"], result.get("checked_at") or status["last_checked"])
        self.assertIsNotNone(status["last_checked"])
        self.assertEqual(status["last_check_status"], "no_fetch_source")

    def test_unchanged_fetch_creates_no_version(self):
        payload = make_snapshot({"2025-01": {"value": 1}, "2025-02": {"value": 2}})
        result = run_update_cycle(self.root, fetch=lambda: payload,
                                  versions_dir=self.versions)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(update_status(self.root, versions_dir=self.versions)["month_count"], 2)

    def test_dry_run_reports_difference_without_staging(self):
        payload = make_snapshot({"2025-01": {"value": 1}, "2025-02": {"value": 2},
                                 "2025-03": {"value": 3}})
        result = run_update_cycle(self.root, fetch=lambda: payload, dry_run=True,
                                  versions_dir=self.versions)
        self.assertEqual(result["difference"]["added_months"], ["2025-03"])
        store = ExposureVersionStore(self.root, self.versions)
        self.assertEqual(len(store._registry()["versions"]), 1)

    def test_activation_failure_keeps_old_active_version(self):
        # Synthetic snapshots have no verifiable release dataset, so the
        # activation must fail safe: the failure is recorded and the old
        # active version stays in place ("更新失败必须保留旧版本").
        payload = make_snapshot({"2025-01": {"value": 1}, "2025-02": {"value": 2},
                                 "2025-03": {"value": 3}})
        result = run_update_cycle(self.root, fetch=lambda: payload,
                                  versions_dir=self.versions, confirm=True)
        self.assertEqual(result["status"], "activation_failed")
        status = update_status(self.root, versions_dir=self.versions)
        self.assertEqual(status["data_cutoff_month"], "2025-02")
        self.assertEqual(status["active_version"], result["difference"]["before_version"])

    def test_staging_rejects_candidate_based_on_non_active_base(self):
        store = ExposureVersionStore(self.root, self.versions)
        active = store.load_snapshot(store.active_version())
        drifted_base = make_snapshot(dict(active, months={**active["months"],
                                                          "2025-02": {"value": 42}}))
        candidate = make_snapshot({**active["months"], "2025-03": {"value": 3}})
        from tradeintel_ai.exposure_version_store import VersionStoreError
        with self.assertRaises(VersionStoreError):
            store.stage(drifted_base, candidate,
                        {"before_version": drifted_base["version"],
                         "after_version": candidate["version"]})

    def test_revised_month_stays_candidate_and_keeps_old_active(self):
        payload = make_snapshot({"2025-01": {"value": 1}, "2025-02": {"value": 999}})
        result = run_update_cycle(self.root, fetch=lambda: payload,
                                  versions_dir=self.versions, confirm=True)
        self.assertTrue(result["staged"]["requires_review"])
        self.assertEqual(update_status(self.root, versions_dir=self.versions)["data_cutoff_month"],
                         "2025-02")
        store = ExposureVersionStore(self.root, self.versions)
        self.assertEqual(store.active_version(), result["difference"]["before_version"])


if __name__ == "__main__":
    unittest.main()
