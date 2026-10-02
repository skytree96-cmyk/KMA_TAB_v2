from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import json
import tempfile
import unittest

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
        self.a = self.store.create_company(self.admin, "회사 A", "0123456789")
        self.b = self.store.create_company(self.admin, "회사 B", "1234567890")

    def user(self, role="participant", company=None, suffix="001", profile=None):
        company = company or self.a
        login_id = company["slug"] + "-" + suffix if role == "participant" else suffix
        record = self.store.create_user(self.admin, login_id, "검증 사용자", role, company["id"], INITIAL, profile=profile)
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
        record = self.store.create_user(self.admin, "mgr", "담당자", "company", self.a["id"], INITIAL)
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
        other = self.store.login("0123456789-001", CHANGED)
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
        other, _ = self.user(company=self.b, suffix="101")
        self.assertEqual([c["id"] for c in self.store.list_companies(manager)], [self.a["id"]])
        self.assertNotIn(other["id"], {u["id"] for u in self.store.list_users(manager)})
        for role, company in (("company", self.a), ("kma", self.a), ("participant", self.b)):
            with self.subTest(role=role, company=company["slug"]), self.assertRaises(AuthorizationError):
                self.store.create_user(manager, "new-user", "신규", role, company["id"], INITIAL)
        with self.assertRaises(AuthorizationError):
            self.store.reset_password(manager, other["id"], INITIAL)
        with self.assertRaises(AuthorizationError):
            self.store.set_user_active(manager, other["id"], False)
        with self.assertRaises(AuthorizationError):
            self.store.create_company(manager, "금지", "2222222222")

    def test_manager_and_prefixed_participant_ids_remain_unique(self):
        manager, token = self.user("company", suffix="mgr")
        self.assertEqual(manager["login_id"], "mgr")
        self.assertEqual(self.store.principal(token)["login_id"], "mgr")
        for company in (self.a, self.b):
            with self.subTest(company=company["id"]), self.assertRaises(ConflictError):
                self.store.create_user(self.admin, "mgr", "중복 담당자", "company", company["id"], INITIAL)
        participant, participant_token = self.user()
        other, _ = self.user(company=self.b, suffix="001")
        self.assertEqual(participant["login_id"], "0123456789-001")
        self.assertEqual(other["login_id"], "1234567890-001")
        self.assertEqual(self.store.principal(participant_token)["login_id"], participant["login_id"])
        with self.assertRaises(ConflictError):
            self.store.create_user(self.admin, participant["login_id"], "중복 참여자", "participant", self.a["id"], INITIAL)

    def test_custom_participant_ids_preserve_uniqueness_and_company_scope(self):
        _, manager = self.user("company", suffix="mgr")
        _, outsider = self.user("company", company=self.b, suffix="mgrb")
        for login_id in ("001", "custom.person"):
            with self.subTest(login_id=login_id):
                participant = self.store.create_user(manager, login_id, "직접 지정 참여자", "participant", self.a["id"], INITIAL)
                self.assertEqual(participant["login_id"], login_id)
                token = self.store.login(login_id, INITIAL)
                self.assertEqual(self.store.principal(token)["company_id"], self.a["id"])
                self.assertIn(participant["id"], {row["id"] for row in self.store.list_users(manager)})
                self.assertNotIn(participant["id"], {row["id"] for row in self.store.list_users(outsider)})
                for company in (self.a, self.b):
                    with self.subTest(company=company["id"]), self.assertRaises(ConflictError):
                        self.store.create_user(self.admin, login_id, "중복 참여자", "participant", company["id"], INITIAL)
                with self.assertRaises(AuthorizationError):
                    self.store.reset_password(outsider, participant["id"], INITIAL)
        with self.assertRaises(AuthorizationError):
            self.store.create_user(manager, "other.person", "다른 회사", "participant", self.b["id"], INITIAL)

    def test_registration_number_requires_exactly_ten_ascii_digits(self):
        self.assertEqual(self.a["slug"], "0123456789")
        self.assertEqual(self.a["registration_number"], "0123456789")
        invalid_numbers = ("123456789", "12345678901", "123456789a", "１２３４５６７８９０",
                           "١٢٣٤٥٦٧٨٩٠", "123-45-6789", " 1234567890", "1234567890 ", 1234567890)
        for number in invalid_numbers:
            with self.subTest(number=number), self.assertRaises(ValidationError):
                self.store.create_company(self.admin, "잘못된 회사", number)
            with self.subTest(update=number), self.assertRaises(ValidationError):
                self.store.set_company_registration_number(self.admin, self.a["id"], number)
        with self.assertRaises(ConflictError):
            self.store.create_company(self.admin, "중복 회사", self.a["slug"])
        with self.assertRaises(ConflictError):
            self.store.set_company_registration_number(self.admin, self.a["id"], self.b["slug"])
        self.assertEqual(self.store.list_companies(self.admin)[0]["slug"], "0123456789")

    def test_registration_correction_requires_kma_and_preserves_existing_data(self):
        user, token, project, assignment = self.assignment()
        _, manager = self.user("company", suffix="mgr")
        saved = self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
        # Simulate an existing alphabetic company code and a legacy login ID.
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE tap_companies SET slug='legacy' WHERE id=?", (self.a["id"],))
            conn.execute("UPDATE tap_users SET login_id='legacy-001' WHERE id=?", (user["id"],))
            conn.commit()
        self.store.initialize()
        self.assertEqual(self.store.list_companies(self.admin)[0]["slug"], "legacy")
        for actor in (manager, token):
            with self.subTest(actor=actor[:4]), self.assertRaises(AuthorizationError):
                self.store.set_company_registration_number(actor, self.a["id"], "0000000001")
        updated = self.store.set_company_registration_number(self.admin, self.a["id"], "0000000001")
        self.assertEqual(updated["id"], self.a["id"])
        self.assertEqual(updated["name"], self.a["name"])
        self.assertEqual(updated["registration_number"], "0000000001")
        self.assertEqual(self.store.principal(token)["login_id"], "legacy-001")
        self.assertEqual(self.store.principal(self.store.login("legacy-001", CHANGED))["id"], user["id"])
        self.assertEqual(self.store.list_projects(token)[0]["id"], project["id"])
        self.assertEqual(self.store.list_projects(token)[0]["company_id"], self.a["id"])
        self.assertEqual(self.store.list_assignments(token)[0]["id"], assignment["id"])
        self.assertEqual(self.store.load_assessment(token, assignment["id"], "pre")["payload"], saved["payload"])
        with closing(sqlite3.connect(self.path)) as conn:
            events = conn.execute("SELECT actor_id,target_id FROM tap_audit_events WHERE event='set_company_registration_number'").fetchall()
        self.assertEqual(events, [(self.store.principal(self.admin)["id"], self.a["id"])])

    def test_optional_profile_persists_and_respects_company_scope(self):
        profile = {"department": " 인재개발팀 ", "job_title": " 과장 ", "email": " person@example.com ", "phone": " +82 10-1234-5678 "}
        expected = {key: value.strip() for key, value in profile.items()}
        participant, token = self.user(profile=profile)
        _, manager = self.user("company", suffix="mgr")
        _, outsider = self.user("company", company=self.b, suffix="mgrb")
        reopened = AccountStore("sqlite:///" + self.path, allow_sqlite_for_tests=True, clock=lambda: self.now)
        self.assertEqual({key: participant[key] for key in expected}, expected)
        self.assertEqual({key: reopened.principal(token)[key] for key in expected}, expected)
        managed = next(row for row in reopened.list_users(manager) if row["id"] == participant["id"])
        self.assertEqual({key: managed[key] for key in expected}, expected)
        self.assertNotIn(participant["id"], {row["id"] for row in reopened.list_users(outsider)})
        empty, _ = self.user(suffix="002")
        self.assertTrue(all(empty[key] == "" for key in expected))

    def test_profile_rejects_unknown_fields_bad_formats_and_control_characters(self):
        bad_profiles = ["profile", {"role": "kma"}, {"department": None}, {"department": "x" * 101},
                        {"job_title": "x" * 81}, {"email": "x" * 255}, {"phone": "1" * 41},
                        {"email": "no-address"}, {"phone": "010-ABCD-1234"}, {"phone": "０１０１２３４５６７８"}]
        for key in ("department", "job_title", "email", "phone"):
            bad_profiles.extend([{key: "bad\nvalue"}, {key: "bad\x7fvalue"}])
        for profile in bad_profiles:
            with self.subTest(profile=profile), self.assertRaises(ValidationError):
                self.store.create_user(self.admin, "0123456789-invalid", "잘못된 정보", "participant", self.a["id"], INITIAL, profile=profile)
        boundary, _ = self.user(suffix="boundary", profile={"department": "가" * 100, "job_title": "나" * 80, "email": "", "phone": ""})
        self.assertEqual(len(boundary["department"]), 100)
        self.assertEqual(len(boundary["job_title"]), 80)

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
        outsider, _ = self.user(company=self.b, suffix="101")
        _, manager_b = self.user("company", company=self.b, suffix="mgrb")
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
        token = self.store.login("0123456789-001", CHANGED)
        with self.assertRaises(AuthorizationError):
            self.store.save_assessment(token, assignment["id"], "post", self.payload(project, True), True)
        self.now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        token = self.store.login("0123456789-001", CHANGED)
        self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
        self.now = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc).timestamp()
        token = self.store.login("0123456789-001", CHANGED)
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
        token = self.store.login("0123456789-001", CHANGED)
        with self.assertRaises(AuthorizationError):
            self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
        self.now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        token = self.store.login("0123456789-001", CHANGED)
        corrupted = {**project["config"], "question_snapshot": []}
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE tap_projects SET config_json=? WHERE id=?", (json.dumps(corrupted), project["id"]))
            conn.commit()
        with self.assertRaises(ConflictError):
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

    def test_schedule_accepts_equal_boundaries_and_rejects_reversed_dates(self):
        for overrides in ({"pre_end_date": "2026-09-10"},
                          {"post_start_date": "2026-09-10"},
                          {"pre_end_date": "2026-09-10", "post_start_date": "2026-09-10"}):
            with self.subTest(accepted=overrides):
                project = self.project(**overrides)
                self.assertTrue(all(project["config"][key] == value for key, value in overrides.items()))
        for overrides in ({"pre_start_date": "2026-09-10"},
                          {"pre_end_date": "2026-09-11"},
                          {"post_start_date": "2026-09-09"},
                          {"post_end_date": "2026-09-10"}):
            with self.subTest(rejected=overrides), self.assertRaises(ValidationError):
                self.project(**overrides)

    def test_same_day_pre_and_post_require_pre_completion(self):
        user, token = self.user()
        day = "2026-09-08"
        project = self.project(**{key: day for key in ("pre_start_date", "pre_end_date", "training_date", "post_start_date", "post_end_date")})
        assignment = self.store.assign_participant(self.admin, project["id"], user["id"])
        with self.assertRaises(AuthorizationError):
            self.store.save_assessment(token, assignment["id"], "post", self.payload(project, True), True)
        self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
        self.store.save_assessment(token, assignment["id"], "post", self.payload(project, True), True)
        result = self.store.project_results(self.admin, project["id"])[0]
        self.assertTrue(result["pre_completed"] and result["post_completed"])

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


class AccountProfileMigrationTests(unittest.TestCase):
    def test_old_schema_gains_empty_profile_columns_without_changing_existing_user(self):
        schema = (Path(__file__).resolve().parents[1] / "database" / "account_schema.sql").read_text(encoding="utf-8")
        schema = schema.replace(" department TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '',\n", "")
        schema = schema.replace(" email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',\n", "")
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "legacy.sqlite")
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript(schema)
                conn.execute("INSERT INTO tap_users(id,login_id,display_name,role,password_hash,created_at) VALUES (?,?,?,?,?,?)",
                             ("existing-admin-id", "existing-admin", "기존 관리자", "kma", hash_password("kma"), 1))
                conn.commit()
                self.assertNotIn("department", {row[1] for row in conn.execute("PRAGMA table_info(tap_users)")})
            store = AccountStore("sqlite:///" + path, allow_sqlite_for_tests=True)
            store.initialize()
            store.initialize()
            principal = store.principal(store.login("existing-admin", "kma"))
            self.assertEqual(principal["id"], "existing-admin-id")
            self.assertEqual(principal["login_id"], "existing-admin")
            self.assertEqual(principal["display_name"], "기존 관리자")
            self.assertTrue(all(principal[key] == "" for key in ("department", "job_title", "email", "phone")))


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
            company = store.create_company(admin, "비밀번호 검증 회사", "3456789012")
            for invalid in ("ab", "a" * 129):
                with self.subTest(operation="create", length=len(invalid)), self.assertRaises(ValidationError):
                    store.create_user(admin, "3456789012-user", "참여자", "participant", company["id"], invalid)
            user = store.create_user(admin, "3456789012-user", "참여자", "participant", company["id"], "ghi")
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
