from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
import unittest

from tap.account_store import AuthorizationError, ValidationError, hash_password
# Import the module, not the class: a TestCase name here would run the whole store suite again.
from tests import test_account_store as store_tests

CHANGED, INITIAL = store_tests.CHANGED, store_tests.INITIAL


def _events(path: str) -> list[dict]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM tap_audit_events ORDER BY created_at,rowid")]


class AccessRecordTests(unittest.TestCase):
    # Borrow the store fixtures without re-running the store tests here.
    setUp = store_tests.AccountStoreTests.setUp
    user = store_tests.AccountStoreTests.user
    project = store_tests.AccountStoreTests.project
    assignment = store_tests.AccountStoreTests.assignment
    payload = store_tests.AccountStoreTests.payload

    @classmethod
    def setUpClass(cls):
        cls.seed_hash = hash_password(INITIAL)

    def test_staff_logins_are_recorded_with_the_first_forwarded_address(self):
        manager, _ = self.user("company", suffix="manager-a")
        participant, _ = self.user()
        self.store.login(manager["login_id"], CHANGED, client="203.0.113.7, 10.0.0.1")
        self.store.login(participant["login_id"], CHANGED, client="198.51.100.2")
        self.store.login("kma-admin", CHANGED, client="<script>")
        logins = [row for row in _events(self.path) if row["event"] == "login"]
        actors = [row["actor_id"] for row in logins]
        self.assertIn(manager["id"], actors)
        self.assertNotIn(participant["id"], actors)
        last_manager = [row for row in logins if row["actor_id"] == manager["id"]][-1]
        self.assertEqual(json.loads(last_manager["detail"]), {"ip": "203.0.113.7"})
        self.assertEqual(logins[-1]["detail"], "{}")

    def test_report_access_names_the_person_and_rejects_other_projects(self):
        user, _, project, assignment = self.assignment()
        self.store.record_report_access(self.admin, project["id"], "view_individual_report", assignment["id"], client="203.0.113.9")
        self.store.record_report_access(self.admin, project["id"], "download_organization_pdf")
        rows = [row for row in _events(self.path) if row["event"] in {"view_individual_report", "download_organization_pdf"}]
        self.assertEqual(rows[0]["target_id"], user["id"])
        self.assertEqual(json.loads(rows[0]["detail"]), {"project_id": project["id"], "ip": "203.0.113.9"})
        self.assertEqual(rows[1]["target_id"], project["id"])
        other = self.project()
        with self.assertRaises(AuthorizationError):
            self.store.record_report_access(self.admin, other["id"], "view_individual_report", assignment["id"])
        with self.assertRaises(ValidationError):
            self.store.record_report_access(self.admin, project["id"], "view_individual_report")
        with self.assertRaises(ValidationError):
            self.store.record_report_access(self.admin, project["id"], "export_everything", assignment["id"])
        _, manager_b = self.user("company", company=self.b, suffix="manager-b")
        with self.assertRaises(AuthorizationError):
            self.store.record_report_access(manager_b, project["id"], "download_organization_pdf")

    def test_only_kma_reviews_the_month_with_names_projects_and_addresses(self):
        user, _, project, assignment = self.assignment()
        self.store.record_report_access(self.admin, project["id"], "download_individual_pdf", assignment["id"], client="203.0.113.5")
        events = self.store.access_events(self.admin, self.now - 3600, self.now + 3600)
        download = next(row for row in events if row["event"] == "download_individual_pdf")
        self.assertEqual((download["actor_login"], download["target_login"], download["project_name"], download["ip"]),
                         ("kma-admin", user["login_id"], project["name"], "203.0.113.5"))
        self.assertEqual(self.store.access_events(self.admin, self.now + 3600, self.now + 7200), [])
        _, manager = self.user("company", suffix="manager-a")
        with self.assertRaises(AuthorizationError):
            self.store.access_events(manager, self.now - 3600, self.now + 3600)

    def test_answers_are_deleted_a_year_after_the_post_deadline(self):
        _, token, project, assignment = self.assignment()
        self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
        # post_end_date is 2026-09-30, so the last day kept is 2027-09-30 (Korean date).
        self.now = datetime(2027, 9, 30, 14, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.store.purge_expired_assessments(), 0)
        self.now = datetime(2027, 9, 30, 15, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.store.purge_expired_assessments(), 1)
        self.assertEqual(self.store.purge_expired_assessments(), 0)
        admin = self.store.login("kma-admin", CHANGED)
        result = self.store.project_results(admin, project["id"])[0]
        self.assertFalse(result["pre_completed"])
        self.assertIsNone(result["pre_payload"])
        config = next(row for row in self.store.list_projects(admin) if row["id"] == project["id"])["config"]
        self.assertEqual(config["responses_purged_at"], "2027-10-01")
        purge = [row for row in _events(self.path) if row["event"] == "purge_assessments"]
        self.assertEqual(len(purge), 1)
        self.assertIsNone(purge[0]["actor_id"])
        self.assertEqual(json.loads(purge[0]["detail"])["count"], "1")

    def test_old_audit_tables_gain_the_detail_column(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("CREATE TABLE old_audit AS SELECT id,actor_id,event,target_id,created_at FROM tap_audit_events")
            conn.execute("DROP TABLE tap_audit_events")
            conn.execute("ALTER TABLE old_audit RENAME TO tap_audit_events")
            conn.commit()
        self.store.initialize()
        with closing(sqlite3.connect(self.path)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(tap_audit_events)")}
        self.assertIn("detail", columns)
        self.store.login("kma-admin", CHANGED, client="203.0.113.1")


class RetentionScheduleTests(unittest.TestCase):
    def test_one_background_purge_per_day(self):
        import threading
        from unittest.mock import patch
        import tap.account_retention as retention

        done = threading.Event()

        class Store:
            calls = 0

            def purge_expired_assessments(self):
                Store.calls += 1
                done.set()
                return 0

        with patch.object(retention, "_last_started", 0.0):
            self.assertTrue(retention.schedule_purge(Store(), clock=lambda: 100_000.0))
            self.assertTrue(done.wait(5))
            self.assertFalse(retention.schedule_purge(Store(), clock=lambda: 100_000.0 + 3600))
            self.assertTrue(retention.schedule_purge(Store(), clock=lambda: 100_000.0 + 86_400))
        self.assertGreaterEqual(Store.calls, 1)

    def test_a_failed_purge_stays_out_of_the_page(self):
        import tap.account_retention as retention

        class Broken:
            def purge_expired_assessments(self):
                raise RuntimeError("db down")

        with self.assertLogs(retention.LOGGER, "WARNING"):
            retention._purge(Broken())


class AccessLogScreenTests(unittest.TestCase):
    def test_rows_read_in_korean_with_system_actor_for_purges(self):
        from tap.account_access_log import event_rows
        when = datetime(2026, 11, 5, 0, 30, tzinfo=timezone.utc).timestamp()
        rows = event_rows([
            {"event": "download_individual_pdf", "created_at": when, "actor_name": "KMA 관리자", "actor_login": "kma-admin",
             "actor_role": "kma", "company_name": None, "target_name": "홍길동", "target_login": "a-001",
             "project_name": "리더십 과정", "ip": "203.0.113.5", "count": ""},
            {"event": "purge_assessments", "created_at": when, "actor_name": None, "actor_login": None, "actor_role": None,
             "company_name": None, "target_name": None, "target_login": None, "project_name": "리더십 과정", "ip": "", "count": "12"},
        ])
        self.assertEqual(rows[0]["일시"], "2026-11-05 09:30:00")
        self.assertEqual((rows[0]["행위"], rows[0]["대상"], rows[0]["역할"]), ("개인 리포트 PDF 내려받기", "홍길동 · a-001", "KMA 관리자"))
        self.assertEqual((rows[1]["계정"], rows[1]["대상"]), ("시스템", "응답 12건"))


if __name__ == "__main__":
    unittest.main()
