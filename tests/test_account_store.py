from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tap.account_store import (AccountStore, AuthenticationError, AuthorizationError,
                               ConflictError, RateLimitError, ValidationError,
                               SESSION_IDLE_SECONDS, SESSION_SECONDS,
                               hash_password, verify_password)


INITIAL = "Temporary-Password-2026!"
CHANGED = "Changed-Password-2026!"


class AccountStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_hash = hash_password(INITIAL)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "accounts.sqlite")
        self.now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        self.store = AccountStore("sqlite:///" + self.path, allow_sqlite_for_tests=True, clock=lambda: self.now)
        self.store.initialize()
        self.store.bootstrap_admin("kma-admin", self.seed_hash)
        first = self.store.login("kma-admin", INITIAL)
        self.admin = self.store.change_password(first, INITIAL, CHANGED)
        self.a = self.store.create_company(self.admin, "회사 A", "alpha")
        self.b = self.store.create_company(self.admin, "회사 B", "bravo")

    def user(self, role="participant", company=None, suffix="001"):
        company = company or self.a
        record = self.store.create_user(self.admin, company["slug"] + "-" + suffix, "검증 사용자", role, company["id"], INITIAL)
        initial = self.store.login(record["login_id"], INITIAL)
        token = self.store.change_password(initial, INITIAL, CHANGED)
        return record, token

    def project(self, company=None, **overrides):
        config = {"company_id": (company or self.a)["id"], "selected_factors": ["CORE-CO"], "target_level": "manager",
                  "pre_start_date": "2026-09-07", "pre_end_date": "2026-09-09", "training_date": "2026-09-10",
                  "post_start_date": "2026-09-11", "post_end_date": "2026-09-30"}
        config.update(overrides)
        return self.store.create_project(self.admin, "계정 기반 프로젝트", config)

    def assignment(self):
        user, token = self.user()
        project = self.project()
        assignment = self.store.assign_participant(self.admin, project["id"], user["id"])
        return user, token, project, assignment

    def payload(self, project, post=False):
        value = {"responses": {code: 0 if i == 0 else 3 for i, code in enumerate(project["config"]["question_snapshot_codes"])},
                 "current_question": 0, "started_at": self.now, "duration_seconds": 45}
        if post:
            value["post_transfer_responses"] = {"application_opportunity": 3, "supervisor_support": 4,
                                                "resources_authority": 3, "time_process_support": 4,
                                                "barriers": [], "applied_content": ""}
        return value

    def test_password_hash_and_no_production_sqlite_fallback(self):
        self.assertTrue(verify_password(INITIAL, self.seed_hash))
        self.assertFalse(verify_password("wrong", self.seed_hash))
        self.assertNotIn(INITIAL, self.seed_hash)
        self.assertNotEqual(self.seed_hash, hash_password(INITIAL))
        with self.assertRaises(ValidationError):
            hash_password("ab")
        with self.assertRaises(ValidationError):
            AccountStore("sqlite:///" + self.path)
        with self.assertRaises(ValidationError):
            AccountStore("")

    def test_bootstrap_idempotent_and_temporary_password_blocks_every_domain(self):
        self.store.initialize()
        self.assertFalse(self.store.bootstrap_admin("other-admin", self.seed_hash))
        record = self.store.create_user(self.admin, "alpha-mgr", "담당자", "company", self.a["id"], INITIAL)
        token = self.store.login(record["login_id"], INITIAL)
        self.assertTrue(self.store.principal(token)["must_change_password"])
        for method, args in [(self.store.list_companies, ()), (self.store.list_users, ()),
                             (self.store.list_projects, ()), (self.store.list_assignments, ())]:
            with self.subTest(method=method.__name__), self.assertRaises(AuthorizationError):
                method(token, *args)
        self.store.logout(token)
        with self.assertRaises(AuthenticationError):
            self.store.principal(token)

    def test_session_tokens_are_hashed_and_password_change_revokes_all(self):
        _, token = self.user()
        other = self.store.login("alpha-001", CHANGED)
        with closing(sqlite3.connect(self.path)) as conn:
            stored = [r[0] for r in conn.execute("SELECT token_hash FROM tap_sessions")]
        self.assertNotIn(token, stored)
        self.assertNotIn(other, stored)
        replacement = self.store.change_password(token, CHANGED, INITIAL)
        for expired in (token, other):
            with self.assertRaises(AuthenticationError):
                self.store.principal(expired)
        self.assertFalse(self.store.principal(replacement)["must_change_password"])

    def test_login_failures_are_persisted_generic_and_locked(self):
        for name in ("kma-admin", "missing-id"):
            for _ in range(5):
                with self.assertRaisesRegex(AuthenticationError, "ID 또는 비밀번호"):
                    self.store.login(name, "Wrong-Password-2026!")
            reopened = AccountStore("sqlite:///" + self.path, allow_sqlite_for_tests=True, clock=lambda: self.now)
            with self.assertRaises(RateLimitError):
                reopened.login(name, CHANGED)
        self.now += 901
        self.assertEqual(self.store.principal(self.store.login("kma-admin", CHANGED))["role"], "kma")

    def test_idle_and_absolute_session_expiry(self):
        self.now += SESSION_IDLE_SECONDS + 1
        with self.assertRaises(AuthenticationError):
            self.store.principal(self.admin)
        token = self.store.login("kma-admin", CHANGED)
        start = self.now
        while self.now - start < SESSION_SECONDS - 1000:
            self.now += 1000
            self.store.principal(token)
        self.now = start + SESSION_SECONDS + 1
        with self.assertRaises(AuthenticationError):
            self.store.principal(token)

    def test_manager_scope_and_role_escalation_are_rejected(self):
        _, manager = self.user("company", suffix="mgr")
        other, _ = self.user(company=self.b)
        self.assertEqual([c["id"] for c in self.store.list_companies(manager)], [self.a["id"]])
        self.assertNotIn(other["id"], {u["id"] for u in self.store.list_users(manager)})
        for role, company in (("company", self.a), ("kma", self.a), ("participant", self.b)):
            with self.subTest(role=role, company=company["slug"]), self.assertRaises(AuthorizationError):
                self.store.create_user(manager, company["slug"] + "-new", "신규", role, company["id"], INITIAL)
        with self.assertRaises(AuthorizationError):
            self.store.reset_password(manager, other["id"], INITIAL)
        with self.assertRaises(AuthorizationError):
            self.store.set_user_active(manager, other["id"], False)
        with self.assertRaises(AuthorizationError):
            self.store.create_company(manager, "금지", "blocked")

    def test_unique_company_prefixed_login_id(self):
        with self.assertRaises(ValidationError):
            self.store.create_user(self.admin, "001", "사용자", "participant", self.a["id"], INITIAL)
        self.user()
        with self.assertRaises(ConflictError):
            self.store.create_user(self.admin, "ALPHA-001", "중복", "participant", self.a["id"], INITIAL)
        self.user(company=self.b)

    def test_reset_and_deactivation_revoke_existing_sessions(self):
        user, token = self.user()
        self.store.reset_password(self.admin, user["id"], INITIAL)
        with self.assertRaises(AuthenticationError):
            self.store.principal(token)
        replacement = self.store.login(user["login_id"], INITIAL)
        self.assertTrue(self.store.principal(replacement)["must_change_password"])
        self.store.set_user_active(self.admin, user["id"], False)
        with self.assertRaises(AuthenticationError):
            self.store.principal(replacement)
        with self.assertRaisesRegex(AuthenticationError, "ID 또는 비밀번호"):
            self.store.login(user["login_id"], INITIAL)
        self.store.set_user_active(self.admin, user["id"], True)
        with self.assertRaises(AuthenticationError):
            self.store.principal(replacement)

    def test_assignment_tenant_and_participant_isolation(self):
        user, token, project, assignment = self.assignment()
        peer, peer_token = self.user(suffix="002")
        outsider, _ = self.user(company=self.b)
        _, manager_b = self.user("company", company=self.b, suffix="mgr")
        with self.assertRaises(AuthorizationError):
            self.store.assign_participant(self.admin, project["id"], outsider["id"])
        with self.assertRaises(AuthorizationError):
            self.store.load_assessment(peer_token, assignment["id"], "pre")
        with self.assertRaises(AuthorizationError):
            self.store.save_assessment(peer_token, assignment["id"], "pre", self.payload(project), True)
        with self.assertRaises(AuthorizationError):
            self.store.project_results(manager_b, project["id"])
        with self.assertRaises(AuthorizationError):
            self.store.project_results(token, project["id"])
        self.assertEqual(self.store.list_assignments(peer_token), [])
        self.assertEqual(self.store.list_projects(manager_b), [])
        self.assertEqual(self.store.assign_participant(self.admin, project["id"], user["id"])["id"], assignment["id"])

    def test_submission_payload_is_validated_and_completed_is_immutable(self):
        _, token, project, assignment = self.assignment()
        good = self.payload(project)
        for bad in ({**good, "user_id": "forged"}, {"responses": {"unknown": 5}}, {"responses": {next(iter(good["responses"])): True}}, {"responses": {}}):
            with self.subTest(payload=bad), self.assertRaises(ValidationError):
                self.store.save_assessment(token, assignment["id"], "pre", bad, True)
        saved = self.store.save_assessment(token, assignment["id"], "pre", good, True)
        again = self.store.save_assessment(token, assignment["id"], "pre", good, True)
        self.assertEqual(saved["completed_at"], again["completed_at"])
        self.assertEqual(self.store.load_assessment(token, assignment["id"], "pre")["payload"], good)
        with self.assertRaises(ConflictError):
            self.store.save_assessment(token, assignment["id"], "pre", good, False)
        changed = {**good, "duration_seconds": 99}
        with self.assertRaises(ConflictError):
            self.store.save_assessment(token, assignment["id"], "pre", changed, True)

    def test_post_requires_pre_and_followup_and_project_reports_scope(self):
        _, token, project, assignment = self.assignment()
        self.now = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc).timestamp()
        token = self.store.login("alpha-001", CHANGED)
        with self.assertRaises(AuthorizationError):
            self.store.save_assessment(token, assignment["id"], "post", self.payload(project, True), True)
        self.now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        token = self.store.login("alpha-001", CHANGED)
        self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
        self.now = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc).timestamp()
        token = self.store.login("alpha-001", CHANGED)
        with self.assertRaises(ValidationError):
            self.store.save_assessment(token, assignment["id"], "post", self.payload(project), True)
        self.store.save_assessment(token, assignment["id"], "post", self.payload(project, True), True)
        self.admin = self.store.login("kma-admin", CHANGED)
        result = self.store.project_results(self.admin, project["id"])[0]
        self.assertTrue(result["pre_completed"] and result["post_completed"])
        self.assertEqual(result["post_payload"]["post_transfer_responses"]["barriers"], [])

    def test_korean_date_window_and_snapshot_mismatch_fail_closed(self):
        _, token, project, assignment = self.assignment()
        # 15:00 UTC is the next midnight in Korea, after pre_end_date.
        self.now = datetime(2026, 9, 9, 15, 0, tzinfo=timezone.utc).timestamp()
        token = self.store.login("alpha-001", CHANGED)
        with self.assertRaises(AuthorizationError):
            self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
        self.now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        token = self.store.login("alpha-001", CHANGED)
        with patch("tap.account_store.questions_for_factors", return_value=[]), self.assertRaises(ConflictError):
            self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)

    def test_project_configuration_validation_and_server_snapshot(self):
        with self.assertRaises(ValidationError):
            self.project(selected_factors=["NOT-REAL"])
        with self.assertRaises(ValidationError):
            self.project(pre_end_date="2026-09-20")
        project = self.project(question_snapshot_codes=["forged"], question_snapshot_hash="forged", allow_schedule_override=True)
        self.assertNotIn("forged", project["config"]["question_snapshot_codes"])
        self.assertEqual(len(project["config"]["question_snapshot_hash"]), 64)
        self.assertFalse(project["config"]["allow_schedule_override"])

    def test_assignment_deactivation_preserves_account_and_other_project(self):
        user, token, project, assignment = self.assignment()
        second = self.project()
        other = self.store.assign_participant(self.admin, second["id"], user["id"])
        self.store.set_assignment_active(self.admin, assignment["id"], False)
        self.assertEqual(self.store.principal(token)["id"], user["id"])
        self.assertEqual([a["id"] for a in self.store.list_assignments(token)], [other["id"]])
        with self.assertRaises(AuthorizationError):
            self.store.load_assessment(token, assignment["id"], "pre")
        self.assertFalse(self.store.list_assignments(self.admin, project["id"])[0]["active"])
        self.store.set_assignment_active(self.admin, assignment["id"], True)
        self.assertEqual(len(self.store.list_assignments(token)), 2)


class PasswordLengthTests(unittest.TestCase):
    def test_hash_password_accepts_three_through_128_characters(self):
        for invalid in ("", "a", "ab", "a" * 129):
            with self.subTest(length=len(invalid)), self.assertRaisesRegex(ValidationError, "3~128"):
                hash_password(invalid)
        for valid in ("abc", "가나다", "a" * 128):
            with self.subTest(length=len(valid)):
                self.assertTrue(verify_password(valid, hash_password(valid)))

    def test_three_character_passwords_work_for_bootstrap_create_change_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AccountStore("sqlite:///" + str(Path(directory) / "passwords.sqlite"), allow_sqlite_for_tests=True)
            store.initialize()
            self.assertTrue(store.bootstrap_admin("kma-admin", hash_password("abc")))
            initial = store.login("kma-admin", "abc")
            self.assertTrue(store.principal(initial)["must_change_password"])
            admin = store.change_password(initial, "abc", "def")
            company = store.create_company(admin, "비밀번호 검증 회사", "length")
            for invalid in ("ab", "a" * 129):
                with self.subTest(operation="create", length=len(invalid)), self.assertRaises(ValidationError):
                    store.create_user(admin, "length-001", "참여자", "participant", company["id"], invalid)
            user = store.create_user(admin, "length-001", "참여자", "participant", company["id"], "ghi")
            token = store.login(user["login_id"], "ghi")
            for invalid in ("ab", "a" * 129):
                with self.subTest(operation="change", length=len(invalid)), self.assertRaises(ValidationError):
                    store.change_password(token, "ghi", invalid)
                with self.subTest(operation="reset", length=len(invalid)), self.assertRaises(ValidationError):
                    store.reset_password(admin, user["id"], invalid)
            changed = store.change_password(token, "ghi", "jkl")
            self.assertFalse(store.principal(changed)["must_change_password"])
            store.reset_password(admin, user["id"], "mno")
            with self.assertRaises(AuthenticationError):
                store.principal(changed)
            reset = store.login(user["login_id"], "mno")
            self.assertTrue(store.principal(reset)["must_change_password"])
            longest = "x" * 128
            store.change_password(reset, "mno", longest)
            self.assertFalse(store.principal(store.login(user["login_id"], longest))["must_change_password"])


if __name__ == "__main__":
    unittest.main()
