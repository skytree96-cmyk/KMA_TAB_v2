from __future__ import annotations

from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from tap.account_store import AccountStore, AuthorizationError, ConflictError, ValidationError, hash_password
from tap.data import load_questions
from tests import test_account_store as fixtures


class AccountCatalogTests(unittest.TestCase):
    # The production scrypt cost is covered separately; use a low cost only in
    # these isolated catalog/dashboard fixtures so their DB checks run quickly.
    def setUp(self):
        cost = patch("tap.account_store._SCRYPT_N", 16)
        cost.start()
        self.addCleanup(cost.stop)
        self.seed_hash = hash_password(fixtures.INITIAL)
        fixtures.AccountStoreTests.setUp(self)

    user = fixtures.AccountStoreTests.user
    project = fixtures.AccountStoreTests.project
    payload = fixtures.AccountStoreTests.payload

    def test_question_edit_permissions_revision_validation_and_persistence(self):
        _, manager = self.user("company", suffix="mgr")
        _, participant = self.user()
        original = load_questions()[0].copy()
        code = original["question_code"]
        initial = next(row for row in self.store.list_question_bank(self.admin) if row["question_code"] == code)
        self.assertEqual(initial["revision"], 0)
        self.assertIsNone(initial["updated_by"])
        for actor in (manager, participant):
            with self.subTest(actor=actor[:4]), self.assertRaises(AuthorizationError):
                self.store.list_question_bank(actor)
            with self.subTest(actor=actor[:4]), self.assertRaises(AuthorizationError):
                self.store.save_question_text(actor, code, "권한 없는 수정", 0)
        for text in ("", " ", "가" * 2001, None):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                self.store.save_question_text(self.admin, code, text, 0)
        for revision in (-1, True, 1.0, None):
            with self.subTest(revision=revision), self.assertRaises(ValidationError):
                self.store.save_question_text(self.admin, code, "문구", revision)
        with self.assertRaises(ValidationError):
            self.store.save_question_text(self.admin, "UNKNOWN", "문구", 0)
        updated = self.store.save_question_text(self.admin, code, "  새 운영 문구  ", 0)
        self.assertEqual(updated["revised_text"], "새 운영 문구")
        self.assertEqual(updated["revision"], 1)
        self.assertEqual(updated["updated_by"], "kma-admin")
        self.assertEqual(updated["updated_at"], self.now)
        reopened = AccountStore("sqlite:///" + self.path, allow_sqlite_for_tests=True, clock=lambda: self.now)
        reopened.initialize()
        self.assertEqual(next(row for row in reopened.list_question_bank(self.admin) if row["question_code"] == code), updated)
        with self.assertRaises(ConflictError):
            reopened.save_question_text(self.admin, code, "오래된 화면의 수정", 0)
        newest = reopened.save_question_text(self.admin, code, "가" * 2000, 1)
        self.assertEqual(newest["revision"], 2)
        self.assertEqual(len(newest["revised_text"]), 2000)
        self.assertEqual(load_questions()[0], original)
        with closing(sqlite3.connect(self.path)) as conn:
            events = conn.execute("SELECT actor_id,target_id FROM tap_audit_events WHERE event='save_question_text'").fetchall()
        self.assertEqual(events, [(self.store.principal(self.admin)["id"], code)] * 2)

    def test_question_edits_apply_to_new_projects_and_preserve_existing_snapshots(self):
        user, token = self.user()
        old = self.project()
        old_snapshot = old["config"]["question_snapshot"]
        code = old_snapshot[0]["question_code"]
        self.store.save_question_text(self.admin, code, "첫 번째 운영 문구", 0)
        new = self.project(question_snapshot=[{"revised_text": "forged"}])
        self.assertEqual(new["config"]["question_snapshot"][0]["revised_text"], "첫 번째 운영 문구")
        self.assertNotEqual(old["config"]["question_snapshot_hash"], new["config"]["question_snapshot_hash"])
        self.assertNotEqual(old["config"]["full_question_snapshot_hash"], new["config"]["full_question_snapshot_hash"])
        self.store.save_question_text(self.admin, code, "두 번째 운영 문구", 1)
        reopened = AccountStore("sqlite:///" + self.path, allow_sqlite_for_tests=True, clock=lambda: self.now)
        stored = {row["id"]: row for row in reopened.list_projects(self.admin)}
        self.assertEqual(stored[old["id"]]["config"], old["config"])
        self.assertEqual(stored[new["id"]]["config"], new["config"])
        for project in (old, new):
            assignment = reopened.assign_participant(self.admin, project["id"], user["id"])
            saved = reopened.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
            self.assertTrue(saved["completed"])
        self.assertEqual(old["config"]["question_snapshot"], old_snapshot)

    def test_dashboard_counts_are_scoped_without_assessment_payloads(self):
        _, manager_a = self.user("company", suffix="mgr")
        _, manager_b = self.user("company", company=self.b, suffix="mgrb")
        first, token = self.user()
        second, _ = self.user(suffix="002")
        other, _ = self.user(company=self.b)
        day = "2026-09-08"
        full = self.project(**{key: day for key in ("pre_start_date", "pre_end_date", "training_date", "post_start_date", "post_end_date")})
        empty = self.project()
        foreign = self.project(company=self.b)
        assignment = self.store.assign_participant(self.admin, full["id"], first["id"])
        removed = self.store.assign_participant(self.admin, full["id"], second["id"])
        self.store.set_assignment_active(self.admin, removed["id"], False)
        self.store.assign_participant(self.admin, foreign["id"], other["id"])
        self.store.save_assessment(token, assignment["id"], "pre", self.payload(full), True)
        self.store.save_assessment(token, assignment["id"], "post", self.payload(full, True), True)
        with patch.object(self.store, "_execute", wraps=self.store._execute) as execute:
            admin = self.store.dashboard_summary(self.admin)
        self.assertFalse(any("payload_json" in call.args[1] for call in execute.call_args_list))
        self.assertEqual((admin["companies_count"], admin["company_users_count"], admin["participant_users_count"]), (2, 2, 3))
        self.assertEqual(len(admin["projects"]), 3)
        summary_a = self.store.dashboard_summary(manager_a)
        summary_b = self.store.dashboard_summary(manager_b)
        self.assertEqual((summary_a["companies_count"], summary_a["company_users_count"], summary_a["participant_users_count"]), (1, 1, 2))
        self.assertEqual((summary_b["companies_count"], summary_b["company_users_count"], summary_b["participant_users_count"]), (1, 1, 1))
        own = {row["id"]: row for row in summary_a["projects"]}
        self.assertEqual(set(own), {full["id"], empty["id"]})
        self.assertEqual([row["id"] for row in summary_b["projects"]], [foreign["id"]])
        self.assertEqual((own[full["id"]]["assigned"], own[full["id"]]["pre_completed"], own[full["id"]]["post_completed"]), (1, 1, 1))
        self.assertEqual(own[empty["id"]]["assigned"], 0)
        self.assertEqual(own[full["id"]]["company_name"], self.a["name"])
        self.assertEqual(own[full["id"]]["config"], full["config"])
        with self.assertRaises(AuthorizationError):
            self.store.dashboard_summary(token)
        with patch.object(self.store, "_execute", wraps=self.store._execute) as execute:
            results = self.store.project_results(manager_a, full["id"])
        payload_queries = [call.args[1] for call in execute.call_args_list if "payload_json FROM tap_assessments" in call.args[1]]
        self.assertEqual(len(payload_queries), 1)
        by_id = {row["id"]: row for row in results}
        self.assertEqual(set(by_id), {assignment["id"], removed["id"]})
        self.assertEqual(by_id[assignment["id"]]["pre_payload"], self.payload(full))
        self.assertEqual(by_id[assignment["id"]]["post_payload"], self.payload(full, True))
        self.assertFalse(by_id[removed["id"]]["active"])
        self.assertIsNone(by_id[removed["id"]]["pre_payload"])
        self.assertIsNone(by_id[removed["id"]]["post_payload"])
        with self.assertRaises(AuthorizationError):
            self.store.project_results(manager_b, full["id"])
